"""Signed review artifacts, with a separate purpose/key from access tokens.

Verification is read-only and does not consume a quote. Confirmation revalidates
provider pricing before locks, then reloads state and repeats verification/overlap
checks under mutation locks before committing. Format 2 binds a persisted revision
as well as the related-state fingerprint; neither consumes a quote by itself.
"""

import hashlib
import hmac
import json
from collections.abc import Sequence
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Literal
from uuid import uuid4

import jwt
from fastapi import HTTPException
from jwt.exceptions import InvalidTokenError
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from app.models.hotel import Hotel
from app.models.payment import Payment
from app.models.reservation import Reservation
from app.models.room_type import RoomType
from app.schemas.hotel_schema import HotelRevalidationRequest, HotelRevalidationResponse
from app.schemas.reservation_change_schema import MAX_CHANGE_QUOTE_LENGTH, ReservationChangeQuoteResponse
from app.services.reservation_change_validation import validate_reservation_change_eligibility
from app.utilities import auth
from app.utilities.reservation_change_serialization import canonical_money

QUOTE_LIFETIME = timedelta(minutes=10)
QUOTE_PURPOSE = "reservation_change_quote"
QUOTE_AUDIENCE = "likehome:reservation-change"
QUOTE_HEADER_TYPE = "likehome-reservation-change+jwt"
QUOTE_FORMAT_VERSION = 2
QUOTE_MONEY_FIELDS = (
    "current_price_per_night", "provider_base_total", "provider_total_with_taxes_fees",
    "likehome_reservation_total", "likehome_payment_amount",
)


class _SignedContext(HotelRevalidationRequest):
    """Historical artifact parsing; live request validation still rejects past dates."""

    @model_validator(mode="after")
    def valid_stay(self) -> "_SignedContext":
        if self.check_out_date <= self.check_in_date:
            raise ValueError("Check-out must follow check-in")
        return self


class _SignedQuote(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sub: str = Field(pattern=r"^[1-9][0-9]*$")
    type: Literal["reservation_change_quote"]
    version: int = Field(strict=True, ge=QUOTE_FORMAT_VERSION, le=QUOTE_FORMAT_VERSION)
    iss: Literal["likehome"]
    aud: Literal["likehome:reservation-change"]
    jti: str = Field(pattern=r"^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$")
    iat: int = Field(strict=True, ge=0)
    exp: int = Field(strict=True, ge=0)
    reservation_id: int = Field(strict=True, gt=0)
    reservation_revision: int = Field(strict=True, ge=0, le=4294967295)
    hotel_id: int = Field(strict=True, gt=0)
    state_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    context: _SignedContext
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
        def canonical(column):
            value = getattr(record, column.name)
            if value is not None and (column.name in ("total_price", "amount", "price_per_night") or isinstance(value, Decimal)):
                return canonical_money(value)
            return value.isoformat() if isinstance(value, date) else value

        return {
            column.name: canonical(column)
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
    # Sign fixed cent strings and return the same normalized values as numbers.
    pricing = quote.model_dump(mode="json")
    for field in QUOTE_MONEY_FIELDS:
        if pricing[field] is not None:
            pricing[field] = canonical_money(getattr(quote, field))
    normalized_quote = HotelRevalidationResponse.model_validate(pricing)
    claims = _SignedQuote(
        sub=str(user_id), type=QUOTE_PURPOSE, version=QUOTE_FORMAT_VERSION, iss="likehome", aud=QUOTE_AUDIENCE,
        jti=str(uuid4()), iat=int(issued_at.timestamp()), exp=int(expiration.timestamp()),
        reservation_id=reservation.reservation_id, reservation_revision=reservation.revision, hotel_id=hotel.hotel_id,
        state_fingerprint=reservation_change_fingerprint(reservation, room_type, hotel, payment),
        context=context.model_dump(), quote=normalized_quote,
    )
    payload = claims.model_dump(mode="json")
    payload["quote"] = pricing
    token = jwt.encode(
        payload, key, algorithm=algorithm, headers={"typ": QUOTE_HEADER_TYPE},
    )
    if len(token) > MAX_CHANGE_QUOTE_LENGTH:
        raise HTTPException(status_code=502, detail="Hotel rate service returned an oversized change quote")
    return ReservationChangeQuoteResponse(
        reservation_id=reservation.reservation_id, quote_id=token, expires_at=expiration, quote=normalized_quote,
    )


def decode_change_quote_claims(token: str) -> _SignedQuote:
    """Verify signature/purpose/version/structure, without authorizing application.

    This intentionally does not check current expiry or reservation state: an
    expired quote may identify an exact persisted successful receipt. New uses
    MUST call verify_reservation_change_quote, including its time/state guards.
    """
    key, algorithm = _signing_parameters()
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
        for field in QUOTE_MONEY_FIELDS:
            value = getattr(claims.quote, field)
            expected = canonical_money(value) if value is not None else None
            if payload["quote"].get(field) != expected:
                raise invalid
    except (InvalidTokenError, ValidationError, ValueError, TypeError) as exc:
        raise invalid from exc
    if claims.exp - claims.iat != int(QUOTE_LIFETIME.total_seconds()):
        raise invalid
    return claims


def verify_reservation_change_quote(
    token: str,
    *, reservation: Reservation, room_type: RoomType, hotel: Hotel,
    payments: Sequence[Payment], user_id: int, context: HotelRevalidationRequest,
    now: datetime | None = None,
) -> ReservationChangeQuoteResponse:
    """Check a signed review against current owned state, context and UTC expiry."""
    claims = decode_change_quote_claims(token)
    current_time = _utc_now(now)
    invalid = HTTPException(status_code=409, detail="Change quote is invalid, expired, or stale; review a new quote")
    if (
        claims.iat > current_time.timestamp() or claims.exp <= current_time.timestamp()
        or claims.sub != str(user_id) or claims.reservation_id != reservation.reservation_id
        or isinstance(reservation.revision, bool) or not isinstance(reservation.revision, int)
        or claims.reservation_revision != reservation.revision
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
