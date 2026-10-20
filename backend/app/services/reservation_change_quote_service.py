"""Read-only US7.2 reviews, not confirmation or financial authorization.

The versioned acknowledgement is opaque to API clients, authenticated with a
domain-separated HMAC key, and NOT encrypted. It contains no guest/contact/auth
data. Treat the entire value as sensitive and never log it. Its embedded context
allows later verification without writing a quote cache or changing contracts.

Future confirmation MUST authenticate the customer again; verify exact token
bytes, signature, purpose, owner/path and expiry; compare its full snapshot with
fresh authoritative rows under the coordinated writer locks/revision protocol;
revalidate the embedded context and same property with the provider; compare the
accepted dates and cent amounts against BOTH reviewed and fresh quotes; enforce
overlap/eligibility; and atomically persist an exact-request receipt before any
mutation can be retried. Hash the original UTF-8 acknowledgement bytes without
trimming/re-encoding for receipt identity. A committed historical retry needs a
separately designed receipt-first protocol and signing-key retention policy.

Current main has no reservation revision. This format's version is NOT a fake
revision. Snapshot equality alone cannot detect intervening changes that revert;
do not activate confirmation until every writer participates in freshness and
idempotency protection. A new revision-aware format may require a fresh review.
The verifier below authenticates a review only; it never authorizes a mutation.
"""

import base64
import binascii
import hmac
import json
import secrets
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.config.config import Config
from app.config.constants import Constants
from app.repositories import reservation_change_quote_dao as quote_dao
from app.schemas.hotel_schema import HotelRevalidationRequest, HotelRevalidationResponse
from app.schemas.reservation_change_schema import (
    MAX_CHANGE_QUOTE_LENGTH,
    MAX_SAFE_ID,
    ReservationChangeQuoteResponse,
    ReservationChangeReviewRequest,
)
from app.services import hotel_service

_DOMAIN = b"LikeHome/US7.2/reservation-change-review/v1"
_PREFIX = "lh-review-v1"
_TTL_SECONDS = 600
_CENT = Decimal("0.01")
_MAX_MONEY = Decimal("99999999.99")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False).encode("utf-8")


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _decode(value: str) -> bytes:
    decoded = base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)
    if _encode(decoded) != value:
        raise ValueError("Noncanonical acknowledgement encoding")
    return decoded


def _signing_key() -> bytes:
    # An asymmetric JWT public key must never become a public HMAC secret.
    secret = Config.JWT_SECRET_KEY
    if (Config.JWT_ALGORITHM not in ("HS256", "HS384", "HS512")
            or not isinstance(secret, str) or len(secret.encode("utf-8")) < 32
            or "-----BEGIN" in secret):
        raise HTTPException(status_code=503, detail="Change quote signing is not configured")
    return hmac.digest(secret.encode("utf-8"), _DOMAIN + b"/signing-key", "sha256")


def _mac(key: bytes, unsigned: str) -> str:
    return _encode(hmac.digest(key, _DOMAIN + b"\x00" + unsigned.encode("ascii"), "sha256"))


def _positive_id(value: object) -> bool:
    return type(value) is int and 0 < value <= MAX_SAFE_ID


def _amount(value: object) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        raise ValueError("Invalid money")
    amount = Decimal(str(value))
    if (not amount.is_finite() or not 0 < amount <= _MAX_MONEY
            or amount != amount.quantize(_CENT)):
        raise ValueError("Invalid money")
    return amount


def _cents(value: Decimal) -> Decimal:
    return value.quantize(_CENT, rounding=ROUND_HALF_UP)


def _snapshot(rows) -> dict:
    if not rows:
        # Identical response for absence and another customer's reservation.
        raise HTTPException(status_code=404, detail="Reservation not found")
    row = rows[0]
    if row["status"] != "confirmed":
        raise HTTPException(status_code=409, detail="Reservation cannot be changed")
    if (len(rows) != 1 or row["payment_type"] != "booking"
            or row["payment_status"] not in ("pending", "paid")):
        raise HTTPException(status_code=409, detail="Reservation payment state is ambiguous")
    try:
        ids = ("reservation_id", "user_id", "room_type_id", "resolved_room_type_id",
               "hotel_id", "resolved_hotel_id", "payment_id")
        if any(not _positive_id(row[key]) for key in ids):
            raise ValueError("Missing identity")
        token = row["hotel_token"]
        if (not isinstance(token, str) or not token or len(token) > 255
                or any(char.isspace() or ord(char) < 32 for char in token)
                or token.lower().startswith(("legacy:", "partner:"))):
            raise ValueError("Untrusted property")
        start, end = row["check_in_date"], row["check_out_date"]
        if type(start) is not date or type(end) is not date or end <= start:
            raise ValueError("Invalid stored stay")
        total = _amount(row["total_price"])
        payment = _amount(row["amount"])
        nightly = _amount(row["price_per_night"])
        # Existing booking creation applies tax to the reservation obligation.
        if payment != _cents(total * Decimal(str(Constants.SALE_TAX))):
            raise ValueError("Inconsistent original obligation")
    except (ValueError, TypeError, InvalidOperation):
        raise HTTPException(status_code=409, detail="Reservation state cannot be verified") from None
    return {
        "reservation_id": row["reservation_id"], "user_id": row["user_id"],
        "room_type_id": row["room_type_id"], "hotel_id": row["hotel_id"],
        "property_token": token, "status": row["status"],
        "check_in_date": start.isoformat(), "check_out_date": end.isoformat(),
        "reservation_total": format(total, ".2f"), "price_per_night": format(nightly, ".2f"),
        "booking_payment_id": row["payment_id"], "booking_payment_status": row["payment_status"],
        "booking_payment_amount": format(payment, ".2f"),
    }


def _validated_quote(value: object, info: HotelRevalidationRequest) -> HotelRevalidationResponse:
    try:
        raw = value.model_dump() if isinstance(value, HotelRevalidationResponse) else value
        if not isinstance(raw, dict):
            raise ValueError("Invalid response")
        # Check raw values before Pydantic can coerce booleans or fractional counts.
        for field in ("adults", "children", "number_of_nights", "guest_capacity"):
            if type(raw.get(field)) is not int:
                raise ValueError("Invalid count")
        money_fields = ("current_price_per_night", "provider_base_total",
                        "likehome_reservation_total", "likehome_payment_amount")
        amounts = {field: _amount(raw.get(field)) for field in money_fields}
        all_in = raw.get("provider_total_with_taxes_fees")
        if all_in is not None and _amount(all_in) < amounts["provider_base_total"]:
            raise ValueError("Inconsistent provider total")
        quote = HotelRevalidationResponse.model_validate(raw)
        nights = (info.check_out_date - info.check_in_date).days
        if (quote.property_token != info.property_token
                or quote.check_in_date != info.check_in_date or quote.check_out_date != info.check_out_date
                or quote.adults != info.adults or quote.children != info.children
                or quote.currency != info.currency or quote.number_of_nights != nights
                or not _positive_id(quote.guest_capacity) or quote.guest_capacity < info.adults + info.children
                or not quote.hotel_name.strip() or len(quote.hotel_name) > 255 or not quote.source.strip()
                or quote.price_changed is not None):
            raise ValueError("Mismatched quote context")
        base = amounts["provider_base_total"]
        reservation_total = _cents(base * Decimal(str(Constants.SERVICE_FEE)))
        if (amounts["current_price_per_night"] != _cents(base / nights)
                or amounts["likehome_reservation_total"] != reservation_total
                or amounts["likehome_payment_amount"] != _cents(reservation_total * Decimal(str(Constants.SALE_TAX)))):
            raise ValueError("Inconsistent LikeHome pricing")
        return quote
    except (ValueError, TypeError, InvalidOperation, ValidationError):
        raise HTTPException(status_code=502, detail="Hotel rate service returned an unverifiable quote") from None


def verify_review_acknowledgement(
    quote_id: str, *, user_id: int, reservation_id: int,
) -> dict:
    """Verify an issued review; callers MUST still perform the module's freshness checks.

    Never normalize or decode/re-encode the supplied identifier before verifying.
    This helper deliberately accepts neither JWTs nor expired unconsumed reviews.
    It is not a confirmation route, receipt lookup, or mutation permission.
    """
    invalid = HTTPException(status_code=409, detail="Change quote is invalid or expired; request a new review")
    if not isinstance(quote_id, str) or not 0 < len(quote_id) <= MAX_CHANGE_QUOTE_LENGTH:
        raise invalid
    key = _signing_key()
    try:
        prefix, payload, signature = quote_id.split(".")
        unsigned = prefix + "." + payload
        if prefix != _PREFIX or not hmac.compare_digest(_mac(key, unsigned), signature):
            raise ValueError("Invalid signature")
        # Reject alternate spellings, padding, whitespace and noncanonical JSON.
        data = json.loads(_decode(payload))
        if _encode(_canonical(data)) != payload or not isinstance(data, dict):
            raise ValueError("Invalid payload")
        issued, expires = data["issued_at"], data["expires_at"]
        now = _now().timestamp()
        if (type(issued) is not int or type(expires) is not int
                or expires - issued != _TTL_SECONDS or not issued <= now < expires
                or data["purpose"] != _PREFIX
                or not _positive_id(data["user_id"]) or data["user_id"] != user_id
                or not _positive_id(data["reservation_id"]) or data["reservation_id"] != reservation_id):
            raise ValueError("Invalid scope or lifetime")
        return data
    except (ValueError, TypeError, KeyError, UnicodeError, binascii.Error):
        raise invalid from None


def create_change_quote(
    db: Session, reservation_id: int, review: ReservationChangeReviewRequest, user_id: int,
) -> ReservationChangeQuoteResponse:
    """Return a current provider quote without any persistent writes or row locks."""
    if not _positive_id(reservation_id):
        raise HTTPException(status_code=422, detail="Invalid reservation ID")
    # Revalidate even an already constructed model (e.g. an internal caller).
    try:
        review = ReservationChangeReviewRequest.model_validate(review.model_dump())
    except ValidationError:
        raise HTTPException(status_code=422, detail="Invalid reservation change review") from None
    try:
        snapshot = _snapshot(quote_dao.get_owned_review_rows(db, reservation_id, user_id))
    except SQLAlchemyError:
        raise HTTPException(status_code=503, detail="Reservation review is temporarily unavailable") from None
    key = _signing_key()
    try:
        info = HotelRevalidationRequest(property_token=snapshot["property_token"], **review.model_dump())
    except ValidationError:
        raise HTTPException(status_code=422, detail="Invalid reservation change review") from None
    try:
        quote = _validated_quote(hotel_service.revalidate_hotel(info), info)
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=502, detail="Hotel rate service is temporarily unavailable") from None
    issued = _now().replace(microsecond=0)
    expires = issued + timedelta(seconds=_TTL_SECONDS)
    data = {
        "purpose": _PREFIX, "issued_at": int(issued.timestamp()), "expires_at": int(expires.timestamp()),
        "nonce": secrets.token_hex(16), "user_id": user_id, "reservation_id": reservation_id,
        "snapshot": snapshot, "review": review.model_dump(mode="json"), "quote": quote.model_dump(mode="json"),
    }
    unsigned = _PREFIX + "." + _encode(_canonical(data))
    quote_id = unsigned + "." + _mac(key, unsigned)
    if len(quote_id) > MAX_CHANGE_QUOTE_LENGTH:
        raise HTTPException(status_code=502, detail="Hotel rate service returned an unverifiable quote")
    return ReservationChangeQuoteResponse(
        reservation_id=reservation_id, quote_id=quote_id,
        expires_at=expires, quote=quote,
    )
