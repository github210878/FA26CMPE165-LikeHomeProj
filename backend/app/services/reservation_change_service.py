"""Trusted review and atomic confirmation; confirmation is not publicly routed.

The caller supplies the customer ID established by existing authentication and a
dedicated request Session. Adjustment settlement/cancellation integration must
be completed before registering confirmation as a customer endpoint.
"""

from datetime import datetime, timezone
from decimal import Decimal
import re

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.hotel import Hotel
from app.models.room_type import RoomType
from app.models.reservation_change_event import ReservationChangeEvent
from app.models.reservation_change_adjustment import ReservationChangeAdjustment
from app.repositories import booking_dao
from app.schemas.hotel_schema import HotelRevalidationRequest
from app.schemas.reservation_change_adjustment_schema import ReservationChangeAdjustmentRecord
from app.schemas.reservation_change_schema import (
    ReservationChangeConfirmRequest,
    ReservationChangeReceiptRequest,
    ReservationChangeQuoteResponse,
    ReservationChangeReviewRequest,
    ReservationChangeRevalidationContext,
)
from app.services import hotel_service, reservation_change_idempotency
from app.services.reservation_change_validation import (
    build_change_revalidation_request,
    validate_change_quote_acceptance,
    validate_reservation_change_eligibility,
)
from app.utilities.reservation_change_quote import (
    QUOTE_MONEY_FIELDS,
    decode_change_quote_claims,
    ensure_change_quote_signing_configured,
    issue_reservation_change_quote,
    verify_reservation_change_quote,
)
from app.utilities.reservation_change_serialization import canonical_money


def quote_reservation_change(
    db: Session, request: ReservationChangeReviewRequest, reservation_id: int, user_id: int,
) -> ReservationChangeQuoteResponse:
    records = booking_dao.get_owned_reservation_for_change(db, reservation_id, user_id)
    if records is None:
        raise HTTPException(status_code=404, detail="Reservation not found")
    reservation, room_type, hotel, payments = records
    payment = validate_reservation_change_eligibility(reservation, payments, user_id)
    context = ReservationChangeRevalidationContext(**request.model_dump(exclude={"check_in_date", "check_out_date"}))
    info = build_change_revalidation_request(reservation, room_type, hotel, request, context)
    if booking_dao.check_if_user_booked_by_date_range(
        db, user_id, info.check_in_date, info.check_out_date, exclude_reservation_id=reservation_id,
    ):
        raise HTTPException(status_code=400, detail="User already has a booking that overlaps with the given date.")
    # This precheck does not reserve dates. Confirmation must repeat it under locks.
    ensure_change_quote_signing_configured()
    quote = hotel_service.revalidate_hotel(info)
    return issue_reservation_change_quote(
        reservation=reservation, room_type=room_type, hotel=hotel, payment=payment,
        user_id=user_id, context=info, quote=quote,
    )


def _require_active_user(db, user_id, *, lock=False):
    check = booking_dao.lock_user_for_booking if lock else booking_dao.is_active_booking_user
    if type(user_id) is not int or not check(db, user_id):
        raise HTTPException(status_code=401, detail="User is inactive or does not exist",
                            headers={"WWW-Authenticate": "Bearer"})


def _check_unsettled_charges(adjustments):
    if any(row.kind == "charge" and row.status in ("pending", "failed") for row in adjustments):
        raise HTTPException(status_code=409, detail="An earlier additional charge must be settled before another change")


def _confirmation_context(reservation, room, hotel, request, claims):
    reconfirmed = ReservationChangeRevalidationContext(
        **claims.context.model_dump(include={"q", "adults", "children", "currency", "gl", "hl"}),
    )
    return build_change_revalidation_request(reservation, room, hotel, request, reconfirmed)


def _verify_review(request, records, user_id, claims, now):
    reservation, room, hotel, payments = records
    validate_reservation_change_eligibility(reservation, payments, user_id)
    context = _confirmation_context(reservation, room, hotel, request, claims)
    reviewed = verify_reservation_change_quote(
        request.quote_id, reservation=reservation, room_type=room, hotel=hotel,
        payments=payments, user_id=user_id, context=context, now=now,
    )
    return context, reviewed


def _check_overlap(db, reservation_id, user_id, request):
    if booking_dao.check_if_user_booked_by_date_range(
        db, user_id, request.check_in_date, request.check_out_date,
        exclude_reservation_id=reservation_id,
    ):
        raise HTTPException(status_code=409, detail="User already has a booking that overlaps with the given date.")


def _previous_obligation(db, reservation, payment):
    latest = booking_dao.get_latest_reservation_change(db, reservation.reservation_id)
    if latest is None:
        return Decimal(canonical_money(payment.amount))
    # The immutable history identifies the last revised obligation, even when
    # the original paid booking amount is intentionally unchanged.
    if (
        latest.user_id != reservation.user_id or latest.booking_payment_id != payment.payment_id
        or latest.revision_after > reservation.revision
        or latest.new_room_type_id != reservation.room_type_id
        or latest.new_check_in_date != reservation.check_in_date
        or latest.new_check_out_date != reservation.check_out_date
        or canonical_money(latest.new_reservation_total) != canonical_money(reservation.total_price)
        or (payment.payment_status == "pending"
            and canonical_money(latest.new_payment_obligation) != canonical_money(payment.amount))
    ):
        raise HTTPException(status_code=409, detail="Reservation financial history could not be verified")
    return Decimal(canonical_money(latest.new_payment_obligation))


def _change_uniqueness_conflict(exc):
    """Recognize only the event's two uniqueness guards, never arbitrary errors."""
    original = exc.orig
    message = str(original)
    if getattr(original, "sqlite_errorname", None) == "SQLITE_CONSTRAINT_UNIQUE":
        return message in (
            "UNIQUE constraint failed: reservation_change_events.quote_jti",
            "UNIQUE constraint failed: reservation_change_events.reservation_id, reservation_change_events.revision_after",
        )
    return (
        bool(original.args) and original.args[0] == 1062
        and re.search(r"for key ['`](?:[^'`]*\.)?uq_change_(?:quote_jti|reservation_revision)['`]", message) is not None
    )


def _persist_change(db, request, reservation, room, hotel, payment, claims, fresh, user_id):
    previous = _previous_obligation(db, reservation, payment)
    obligation = Decimal(canonical_money(fresh.likehome_payment_amount))
    total = Decimal(canonical_money(fresh.likehome_reservation_total))
    if previous <= 0 or Decimal(canonical_money(reservation.total_price)) <= 0 or reservation.revision >= 4294967295:
        raise HTTPException(status_code=409, detail="Reservation financial state or revision is unsupported")
    difference = obligation - previous
    # Use the same immutable rate-record strategy as creation. Never change a
    # shared room's price, description or hotel, and never create another Hotel.
    target_room = RoomType(
        hotel_id=hotel.hotel_id, type_name="Lowest available rate",
        description=f"Provider: {fresh.source[:480]}",
        price_per_night=float(Decimal(canonical_money(fresh.current_price_per_night))),
    )
    room_id = booking_dao.is_room_type_in_db(db, target_room)
    if room_id is None:
        room_id = booking_dao.stage_booking_record(db, target_room).room_type_id
    fresh_json = fresh.model_dump(mode="json")
    for field in QUOTE_MONEY_FIELDS:
        value = getattr(fresh, field)
        fresh_json[field] = canonical_money(value) if value is not None else None
    change = ReservationChangeEvent(
        reservation_id=reservation.reservation_id, user_id=user_id, booking_payment_id=payment.payment_id,
        quote_jti=claims.jti, quote_sha256=reservation_change_idempotency.signed_quote_sha256(request.quote_id),
        request_sha256=reservation_change_idempotency.confirmation_request_sha256(
            request, reservation_id=reservation.reservation_id, user_id=user_id,
        ),
        original_state_sha256=bytes.fromhex(claims.state_fingerprint),
        revision_before=reservation.revision, revision_after=reservation.revision + 1,
        old_room_type_id=room.room_type_id, new_room_type_id=room_id,
        old_check_in_date=reservation.check_in_date, old_check_out_date=reservation.check_out_date,
        new_check_in_date=request.check_in_date, new_check_out_date=request.check_out_date,
        old_reservation_total=Decimal(canonical_money(reservation.total_price)), new_reservation_total=total,
        old_payment_obligation=previous, new_payment_obligation=obligation,
        booking_payment_status_before=payment.payment_status, currency=fresh.currency,
        context_json=claims.context.model_dump(mode="json"), fresh_quote_json=fresh_json, response_json={},
        quote_issued_at=datetime.fromtimestamp(claims.iat, timezone.utc).replace(tzinfo=None),
        quote_expires_at=datetime.fromtimestamp(claims.exp, timezone.utc).replace(tzinfo=None),
    )
    reservation.check_in_date = request.check_in_date
    reservation.check_out_date = request.check_out_date
    reservation.room_type_id = room_id
    reservation.total_price = float(total)
    reservation.revision += 1
    if payment.payment_status == "pending":
        payment.amount = float(obligation)
    booking_dao.stage_booking_record(db, change)
    adjustment = None
    if payment.payment_status == "paid" and difference:
        entry = ReservationChangeAdjustmentRecord(
            change_id=change.change_id, kind="charge" if difference > 0 else "credit",
            amount=abs(difference), status="pending" if difference > 0 else "recorded",
        )
        adjustment = booking_dao.stage_booking_record(db, ReservationChangeAdjustment(**entry.model_dump()))
    # Receipt money stays in canonical cents, including exact public retries.
    # Financial summary and payment APIs retain their numeric money contracts.
    receipt = {
        "change_id": change.change_id, "reservation_id": reservation.reservation_id,
        "revision": reservation.revision, "room_type_id": room_id,
        "check_in_date": request.check_in_date.isoformat(), "check_out_date": request.check_out_date.isoformat(),
        "reservation_total": canonical_money(total), "payment_obligation": canonical_money(obligation),
        "previous_payment_obligation": canonical_money(previous), "payment_difference": canonical_money(difference),
        "booking_payment_id": payment.payment_id, "booking_payment_status": payment.payment_status,
        "adjustment": None if adjustment is None else {
            "adjustment_id": adjustment.adjustment_id, "kind": adjustment.kind,
            "amount": canonical_money(adjustment.amount), "status": adjustment.status,
        },
    }
    change.response_json = receipt
    db.flush()
    return receipt


def confirm_reservation_change(
    db: Session, request: ReservationChangeConfirmRequest, reservation_id: int, user_id: int,
    *, now: datetime | None = None,
) -> dict:
    """Apply one signed review atomically, with one provider call for a new use.

    Exact committed retries can use ReceiptRequest for historical date parsing.
    Unconsumed requests ALWAYS pass the normal future-date schema. The optional
    aware clock is for deterministic tests; production rechecks time after waits.
    """
    try:
        request = ReservationChangeReceiptRequest.model_validate(request.model_dump())
        with db.no_autoflush:
            _require_active_user(db, user_id)
            records = booking_dao.get_owned_reservation_for_change(db, reservation_id, user_id)
            if records is None:
                raise HTTPException(status_code=404, detail="Reservation not found")
            receipt = reservation_change_idempotency.get_committed_change_receipt(
                db, request, reservation_id=reservation_id, user_id=user_id, now=now,
            )
            if receipt is not None:
                db.rollback()
                return receipt
            request = ReservationChangeConfirmRequest.model_validate(request.model_dump())
            claims = decode_change_quote_claims(request.quote_id)
            context, reviewed = _verify_review(request, records, user_id, claims, now)
            _check_unsettled_charges(booking_dao.get_adjustments_for_change(db, reservation_id))
            _check_overlap(db, reservation_id, user_id, request)
            validate_change_quote_acceptance(request, reviewed, reviewed.quote,
                                            reservation_id=reservation_id, user_id=user_id,
                                            quote_owner_user_id=int(claims.sub), now=now)
        # No mutation locks are acquired during this external call.
        fresh = hotel_service.revalidate_hotel(HotelRevalidationRequest(**context.model_dump()))
        validate_change_quote_acceptance(request, reviewed, fresh, reservation_id=reservation_id,
                                        user_id=user_id, quote_owner_user_id=int(claims.sub), now=now)
        # Clear earlier authentication/ownership reads and their RR snapshot.
        db.rollback()
        _require_active_user(db, user_id, lock=True)
        reservation = booking_dao.lock_reservation_for_change(db, reservation_id, user_id)
        if reservation is None:
            raise HTTPException(status_code=404, detail="Reservation not found")
        payments = booking_dao.lock_payments_for_change(db, reservation_id)
        adjustments = booking_dao.get_adjustments_for_change(db, reservation_id, lock=True)
        receipt = reservation_change_idempotency.get_committed_change_receipt(
            db, request, reservation_id=reservation_id, user_id=user_id, now=now,
        )
        if receipt is not None:
            db.rollback()
            return receipt
        room = db.get(RoomType, reservation.room_type_id, populate_existing=True)
        hotel = db.get(Hotel, room.hotel_id, populate_existing=True) if room is not None else None
        _, reviewed = _verify_review(request, (reservation, room, hotel, payments), user_id, claims, now)
        _check_unsettled_charges(adjustments)
        _check_overlap(db, reservation_id, user_id, request)
        validate_change_quote_acceptance(request, reviewed, fresh, reservation_id=reservation_id,
                                        user_id=user_id, quote_owner_user_id=int(claims.sub), now=now)
        receipt = _persist_change(db, request, reservation, room, hotel, payments[0], claims, fresh, user_id)
        db.commit()
        return receipt
    except IntegrityError as exc:
        db.rollback()
        if not _change_uniqueness_conflict(exc):
            raise HTTPException(status_code=500, detail="Failed to change reservation") from exc
        # A uniqueness race is a retry ONLY if a matching immutable receipt is
        # now committed. Foreign-key/adjustment/unrelated uniqueness errors never
        # enter this path. Rollback establishes a fresh read snapshot.
        try:
            _require_active_user(db, user_id)
            receipt = reservation_change_idempotency.get_committed_change_receipt(
                db, request, reservation_id=reservation_id, user_id=user_id, now=now,
            )
            if receipt is None:
                raise HTTPException(status_code=409, detail="Change quote conflicts with a committed reservation revision")
            return receipt
        except HTTPException:
            raise
        except Exception as recovery_error:
            raise HTTPException(status_code=500, detail="Failed to verify committed reservation change") from recovery_error
        finally:
            db.rollback()
    except ValidationError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail="Invalid reservation change confirmation") from exc
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail="Failed to change reservation") from exc
