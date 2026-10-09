"""Signed review artifacts, with a separate purpose/key from access tokens.

Verification is read-only and does not consume a quote. Increment 3 must reload
state and repeat verification/overlap checks under the mutation locks, then
freshly revalidate pricing before committing. A fingerprint detects changed
current state; it is not a persistent revision counter or replay ledger.
"""

import hashlib
import hmac
import json
from collections.abc import Sequence
from datetime import date, datetime, timedelta, timezone
from typing import Literal
from uuid import uuid4

import jwt
from fastapi import HTTPException
from jwt.exceptions import InvalidTokenError
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.models.hotel import Hotel
from app.models.payment import Payment
from app.models.reservation import Reservation
from app.models.room_type import RoomType
from app.schemas.hotel_schema import HotelRevalidationRequest, HotelRevalidationResponse
from app.schemas.reservation_change_schema import MAX_CHANGE_QUOTE_LENGTH, ReservationChangeQuoteResponse
from app.services.reservation_change_validation import validate_reservation_change_eligibility
from app.utilities import auth

QUOTE_LIFETIME = timedelta(minutes=10)
QUOTE_PURPOSE = "reservation_change_quote"
QUOTE_AUDIENCE = "likehome:reservation-change"
QUOTE_HEADER_TYPE = "likehome-reservation-change+jwt"


class _SignedQuote(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sub: str = Field(pattern=r"^[1-9][0-9]*$")
    type: Literal["reservation_change_quote"]
    version: int = Field(strict=True, ge=1, le=1)
    iss: Literal["likehome"]
    aud: Literal["likehome:reservation-change"]
    jti: str = Field(min_length=1, max_length=255)
    iat: int = Field(strict=True, ge=0)
    exp: int = Field(strict=True, ge=0)
    reservation_id: int = Field(strict=True, gt=0)
    hotel_id: int = Field(strict=True, gt=0)
    state_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    context: HotelRevalidationRequest
    quote: HotelRevalidationResponse


def _signing_parameters() -> tuple[bytes, str]:
    secret = auth.JWT_SECRET_KEY
    algorithm = auth.JWT_ALGORITHM
    if (
        not isinstance(secret, str) or len(secret.encode("utf-8")) < 32
        or algorithm not in ("HS256", "HS384", "HS512")
    ):
        raise HTTPException(status_code=500, detail="Reservation change quote signing is not configured securely")
    key = hmac.new(
        secret.encode("utf-8"), b"likehome:reservation-change-quote:v1", hashlib.sha512,
    ).digest()
    return key, algorithm


def ensure_change_quote_signing_configured() -> None:
    """Fail before spending provider quota if the existing signer is unavailable."""
    _signing_parameters()


def _utc_now(now: datetime | None) -> datetime:
    value = now if now is not None else datetime.now(timezone.utc)
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Quote validation requires a timezone-aware clock")
    return value.astimezone(timezone.utc)


def reservation_change_fingerprint(
    reservation: Reservation, room_type: RoomType, hotel: Hotel, payment: Payment,
) -> str:
    """Hash persisted original fields, including payment state and associations."""
    def snapshot(record):
        return {
            column.name: value.isoformat() if isinstance(value := getattr(record, column.name), date) else value
            for column in record.__table__.columns
        }

    state = {
        "reservation": snapshot(reservation), "room_type": snapshot(room_type),
        "hotel": snapshot(hotel), "payment": snapshot(payment),
    }
    encoded = json.dumps(state, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _context_matches_quote(info: HotelRevalidationRequest, quote: HotelRevalidationResponse) -> bool:
    return (
        all(getattr(info, field) == getattr(quote, field) for field in (
            "property_token", "check_in_date", "check_out_date", "adults", "children", "currency",
        ))
        and quote.number_of_nights == (info.check_out_date - info.check_in_date).days
    )


def _property_matches(
    reservation: Reservation, room_type: RoomType, hotel: Hotel, context: HotelRevalidationRequest,
) -> bool:
    return (
        reservation.room_type_id == room_type.room_type_id and room_type.hotel_id == hotel.hotel_id
        and isinstance(hotel.hotel_token, str) and context.property_token == hotel.hotel_token.strip()
    )


def issue_reservation_change_quote(
    *, reservation: Reservation, room_type: RoomType, hotel: Hotel, payment: Payment,
    user_id: int, context: HotelRevalidationRequest, quote: HotelRevalidationResponse,
    now: datetime | None = None,
) -> ReservationChangeQuoteResponse:
    """Sign the trusted quote after the caller has loaded/validated all payments."""
    key, algorithm = _signing_parameters()
    validate_reservation_change_eligibility(reservation, [payment], user_id)
    if not _property_matches(reservation, room_type, hotel, context) or not _context_matches_quote(context, quote):
        raise HTTPException(status_code=409, detail="Change quote context could not be verified")
    issued_at = _utc_now(now).replace(microsecond=0)
    expiration = issued_at + QUOTE_LIFETIME
    claims = _SignedQuote(
        sub=str(user_id), type=QUOTE_PURPOSE, version=1, iss="likehome", aud=QUOTE_AUDIENCE,
        jti=str(uuid4()), iat=int(issued_at.timestamp()), exp=int(expiration.timestamp()),
        reservation_id=reservation.reservation_id, hotel_id=hotel.hotel_id,
        state_fingerprint=reservation_change_fingerprint(reservation, room_type, hotel, payment),
        context=context, quote=quote,
    )
    token = jwt.encode(
        claims.model_dump(mode="json"), key, algorithm=algorithm, headers={"typ": QUOTE_HEADER_TYPE},
    )
    if len(token) > MAX_CHANGE_QUOTE_LENGTH:
        raise HTTPException(status_code=502, detail="Hotel rate service returned an oversized change quote")
    return ReservationChangeQuoteResponse(
        reservation_id=reservation.reservation_id, quote_id=token, expires_at=expiration, quote=quote,
    )


def verify_reservation_change_quote(
    token: str,
    *, reservation: Reservation, room_type: RoomType, hotel: Hotel,
    payments: Sequence[Payment], user_id: int, context: HotelRevalidationRequest,
    now: datetime | None = None,
) -> ReservationChangeQuoteResponse:
    """Verify a review against freshly loaded owned state and expected context.

    Time claims are checked explicitly against an injectable UTC clock after
    signature verification, so exact expiry boundaries are deterministic.
    """
    key, algorithm = _signing_parameters()
    current_time = _utc_now(now)
    invalid = HTTPException(status_code=409, detail="Change quote is invalid, expired, or stale; review a new quote")
    if not isinstance(token, str) or not 0 < len(token) <= MAX_CHANGE_QUOTE_LENGTH:
        raise invalid
    try:
        header = jwt.get_unverified_header(token)
        if header.get("typ") != QUOTE_HEADER_TYPE:
            raise invalid
        payload = jwt.decode(
            token, key, algorithms=[algorithm], audience=QUOTE_AUDIENCE, issuer="likehome",
            options={
                "require": list(_SignedQuote.model_fields),
                "verify_exp": False, "verify_iat": False,
            },
        )
        claims = _SignedQuote.model_validate(payload)
    except (InvalidTokenError, ValidationError, ValueError, TypeError) as exc:
        raise invalid from exc
    if (
        claims.exp - claims.iat != int(QUOTE_LIFETIME.total_seconds())
        or claims.iat > current_time.timestamp() or claims.exp <= current_time.timestamp()
        or claims.sub != str(user_id) or claims.reservation_id != reservation.reservation_id
        or claims.hotel_id != hotel.hotel_id
        or not _property_matches(reservation, room_type, hotel, context)
        or claims.context.model_dump() != context.model_dump()
        or not _context_matches_quote(claims.context, claims.quote)
    ):
        raise invalid
    payment = validate_reservation_change_eligibility(reservation, payments, user_id)
    if not hmac.compare_digest(
        claims.state_fingerprint, reservation_change_fingerprint(reservation, room_type, hotel, payment),
    ):
        raise invalid
    return ReservationChangeQuoteResponse(
        reservation_id=reservation.reservation_id, quote_id=token,
        expires_at=datetime.fromtimestamp(claims.exp, timezone.utc), quote=claims.quote,
    )
