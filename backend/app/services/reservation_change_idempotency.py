"""Read-only persisted receipt recognition, not reservation-change confirmation.

An exact committed receipt can outlive its quote and original reservation state.
Missing receipts do NOT authorize applying a quote. The confirmation service
repeats this lookup under reservation locks and runs fresh time/state/provider
validation before mutation. Nothing is inserted, updated, flushed or committed here.
"""

import hashlib
import hmac
import json
from datetime import datetime

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.reservation_change_event import ReservationChangeEvent
from app.repositories import booking_dao
from app.schemas.reservation_change_schema import ReservationChangeConfirmRequest
from app.utilities.reservation_change_quote import (
    _utc_now, decode_change_quote_claims,
)
from app.utilities.reservation_change_serialization import canonical_money


def signed_quote_sha256(token: str) -> bytes:
    """Hash exact signed bytes; never log or persist the raw token."""
    return hashlib.sha256(token.encode("utf-8")).digest()


def confirmation_request_sha256(
    request: ReservationChangeConfirmRequest, *, reservation_id: int, user_id: int,
) -> bytes:
    """Bind normalized acceptance, dates, token and authenticated/path identity."""
    payload = {
        "purpose": "reservation-change-confirmation:v2",
        "reservation_id": reservation_id, "user_id": user_id,
        "quote_sha256": signed_quote_sha256(request.quote_id).hex(),
        "check_in_date": request.check_in_date.isoformat(),
        "check_out_date": request.check_out_date.isoformat(),
        "accept_quote": request.accept_quote,
        "price_per_night": canonical_money(request.price_per_night),
        "accepted_payment_amount": canonical_money(request.accepted_payment_amount),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(encoded).digest()


def _conflict() -> HTTPException:
    return HTTPException(status_code=409, detail="Change quote receipt is invalid or conflicts with the committed request")


def _request_claims(request, reservation_id, user_id, now):
    claims = decode_change_quote_claims(request.quote_id)
    if (
        type(user_id) is not int or type(reservation_id) is not int
        or claims.sub != str(user_id) or claims.reservation_id != reservation_id
        or claims.iat > _utc_now(now).timestamp()
        or claims.context.check_in_date != request.check_in_date
        or claims.context.check_out_date != request.check_out_date
    ):
        raise _conflict()
    return claims


def _matching_hash(stored: bytes, expected: bytes) -> bool:
    return isinstance(stored, bytes) and len(stored) == 32 and hmac.compare_digest(stored, expected)


def verify_committed_change_receipt(
    record: ReservationChangeEvent | None, request: ReservationChangeConfirmRequest,
    *, reservation_id: int, user_id: int, now: datetime | None = None,
) -> dict | None:
    """Pure verification; return a detached JSON receipt or None for no event.

    Neither current reservation revision nor quote expiry invalidates a matching
    historical success. Signature, format, identity and persisted request/token
    hashes remain mandatory. This result authorizes no new reservation write.
    """
    claims = _request_claims(request, reservation_id, user_id, now)
    if record is None:
        return None
    if (
        record.user_id != user_id or record.reservation_id != reservation_id
        or record.quote_jti != claims.jti or record.revision_before != claims.reservation_revision
        or record.revision_after != record.revision_before + 1
        or not _matching_hash(record.quote_sha256, signed_quote_sha256(request.quote_id))
        or not _matching_hash(record.request_sha256, confirmation_request_sha256(
            request, reservation_id=reservation_id, user_id=user_id,
        ))
    ):
        raise _conflict()
    if not isinstance(record.response_json, dict) or not record.response_json:
        raise _conflict()
    try:
        # Validate stored JSON and return a deep copy, never the mutable ORM dict.
        return json.loads(json.dumps(record.response_json, allow_nan=False))
    except (TypeError, ValueError) as exc:
        raise _conflict() from exc


def get_committed_change_receipt(
    db: Session, request: ReservationChangeConfirmRequest,
    *, reservation_id: int, user_id: int, now: datetime | None = None,
) -> dict | None:
    """Owner-scoped database lookup; deliberately no locks or writes yet."""
    claims = _request_claims(request, reservation_id, user_id, now)
    record = booking_dao.get_owned_change_event_by_quote_jti(db, claims.jti, reservation_id, user_id)
    return verify_committed_change_receipt(
        record, request, reservation_id=reservation_id, user_id=user_id, now=now,
    )
