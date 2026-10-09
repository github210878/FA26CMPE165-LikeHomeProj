"""Increment 1 contracts/guards: transient models, no database or provider calls."""

from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.models.hotel import Hotel
from app.models.payment import Payment
from app.models.reservation import Reservation
from app.models.room_type import RoomType
from app.routers.booking_router import router
from app.schemas.hotel_schema import HotelRevalidationResponse
from app.schemas.reservation_change_schema import (
    ReservationChangeConfirmRequest,
    ReservationChangeQuoteRequest,
    ReservationChangeQuoteResponse,
    ReservationChangeRevalidationContext,
)
from app.services.reservation_change_validation import (
    build_change_revalidation_request,
    validate_change_quote_acceptance,
    validate_changed_dates,
    validate_reservation_change_eligibility,
)

TODAY = date(2026, 9, 29)
NOW = datetime(2026, 9, 29, 12, tzinfo=timezone.utc)


@pytest.fixture
def records():
    reservation = Reservation(
        reservation_id=1, user_id=7, room_type_id=2,
        check_in_date=date(2026, 11, 1), check_out_date=date(2026, 11, 3),
        status="confirmed", total_price=210,
    )
    payment = Payment(
        payment_id=3, reservation_id=1, payment_type="booking",
        payment_status="pending", amount=226.80,
    )
    room = RoomType(room_type_id=2, hotel_id=4, type_name="Lowest available rate", price_per_night=100)
    hotel = Hotel(hotel_id=4, hotel_token="property-A", name="Hotel A")
    return reservation, payment, room, hotel


def change_request(**overrides):
    return ReservationChangeQuoteRequest(**{
        "check_in_date": "2026-11-04", "check_out_date": "2026-11-06", **overrides,
    })


def confirm_request(**overrides):
    return ReservationChangeConfirmRequest(**{
        **change_request().model_dump(), "quote_id": "review-1", "accept_quote": True,
        "price_per_night": 100, "accepted_payment_amount": 226.80, **overrides,
    })


def context(**overrides):
    return ReservationChangeRevalidationContext(**{
        "q": " San Jose hotels ", "adults": 3, "children": 1, **overrides,
    })


def provider_quote(**overrides):
    return HotelRevalidationResponse(**{
        "property_token": "property-A", "hotel_name": "Hotel A",
        **change_request().model_dump(), "adults": 3, "children": 1, "currency": "USD",
        "number_of_nights": 2, "availability": "available",
        "rate_rule": "lowest_eligible_provider_base_total", "source": "Provider A",
        "guest_capacity": 4, "current_price_per_night": 100, "provider_base_total": 200,
        "provider_total_with_taxes_fees": 240, "likehome_reservation_total": 210,
        "likehome_payment_amount": 226.80, "price_changed": None, **overrides,
    })


def review(**overrides):
    return ReservationChangeQuoteResponse(**{
        "reservation_id": 1, "quote_id": "review-1",
        "expires_at": NOW + timedelta(hours=1), "quote": provider_quote(), **overrides,
    })


def check_acceptance(request=None, reviewed_quote=None, fresh_quote=None, **overrides):
    validate_change_quote_acceptance(
        request or confirm_request(), reviewed_quote or review(), fresh_quote or provider_quote(),
        **{"reservation_id": 1, "user_id": 7, "quote_owner_user_id": 7, "now": NOW, **overrides},
    )


@pytest.mark.parametrize("payment_status", ["pending", "paid"])
def test_upcoming_owned_paid_and_unpaid_reservations_are_eligible(records, payment_status):
    reservation, payment, _, _ = records
    payment.payment_status = payment_status
    assert validate_reservation_change_eligibility(reservation, [payment], 7) is payment
    assert payment.payment_status == payment_status
    assert reservation.status == "confirmed"


@pytest.mark.parametrize("status", ["cancelled", "completed", "unknown", None])
def test_unsupported_reservation_states_are_rejected(records, status):
    reservation, payment, _, _ = records
    reservation.status = status
    with pytest.raises(HTTPException) as error:
        validate_reservation_change_eligibility(reservation, [payment], 7)
    assert error.value.status_code == 409


@pytest.mark.parametrize("check_in", [TODAY - timedelta(days=1), TODAY])
def test_past_and_current_reservations_are_not_upcoming(records, check_in):
    reservation, payment, _, _ = records
    reservation.check_in_date = check_in
    with pytest.raises(HTTPException, match="Only upcoming") as error:
        validate_reservation_change_eligibility(reservation, [payment], 7, today=TODAY)
    assert error.value.status_code == 409


def test_eligibility_clock_can_be_injected(records):
    reservation, payment, _, _ = records
    assert validate_reservation_change_eligibility(
        reservation, [payment], 7, today=reservation.check_in_date - timedelta(days=1),
    ) is payment
    with pytest.raises(HTTPException):
        validate_reservation_change_eligibility(reservation, [payment], 7, today=reservation.check_in_date)


@pytest.mark.parametrize("missing", [False, True])
def test_missing_and_nonowned_reservations_share_not_found_error(records, missing):
    reservation, payment, _, _ = records
    # This is a local ownership guard; owner-scoped lookup/HTTP integration is Increment 2.
    with pytest.raises(HTTPException) as error:
        validate_reservation_change_eligibility(None if missing else reservation, [payment], 8)
    assert error.value.status_code == 404
    assert error.value.detail == "Reservation not found"


@pytest.mark.parametrize("status", ["failed", "refunded", "unknown", None])
def test_unsupported_payment_states_are_rejected(records, status):
    reservation, payment, _, _ = records
    payment.payment_status = status
    with pytest.raises(HTTPException) as error:
        validate_reservation_change_eligibility(reservation, [payment], 7)
    assert error.value.status_code == 409


@pytest.mark.parametrize("case", ["missing", "duplicate", "cancellation", "other-reservation"])
def test_missing_ambiguous_or_unrelated_payment_records_are_rejected(records, case):
    reservation, payment, _, _ = records
    payments = [payment]
    if case == "missing":
        payments = []
    elif case == "duplicate":
        payments.append(Payment(reservation_id=1, payment_type="booking", payment_status="paid"))
    elif case == "cancellation":
        payment.payment_type = "cancellation"
    else:
        payment.reservation_id = 999
    with pytest.raises(HTTPException) as error:
        validate_reservation_change_eligibility(reservation, payments, 7)
    assert error.value.status_code == 409


def test_corrupt_existing_date_range_is_rejected(records):
    reservation, payment, _, _ = records
    reservation.check_out_date = reservation.check_in_date
    with pytest.raises(HTTPException, match="Reservation dates are invalid"):
        validate_reservation_change_eligibility(reservation, [payment], 7)


@pytest.mark.parametrize("field", ["check_in_date", "check_out_date"])
@pytest.mark.parametrize("value", ["2026-02-30", "not-a-date", "20261104", None, 1793750400, True])
def test_invalid_calendar_dates_are_rejected(field, value):
    with pytest.raises(ValidationError) as error:
        change_request(**{field: value})
    assert (field,) in [item["loc"] for item in error.value.errors()]


@pytest.mark.parametrize("checkout", ["2026-11-04", "2026-11-03"])
def test_checkout_must_follow_checkin(checkout):
    with pytest.raises(ValidationError, match="check_out_date must be after"):
        change_request(check_out_date=checkout)


def test_requested_checkin_must_not_be_past_but_today_is_allowed():
    with pytest.raises(ValidationError, match="cannot be in the past"):
        change_request(check_in_date="2026-09-28")
    assert change_request(check_in_date=TODAY).check_in_date == TODAY


def test_valid_leap_day_uses_calendar_validation():
    assert change_request(check_in_date="2028-02-29", check_out_date="2028-03-01").check_in_date == date(2028, 2, 29)


def test_unchanged_stay_is_rejected(records):
    reservation, _, _, _ = records
    request = change_request(check_in_date=reservation.check_in_date, check_out_date=reservation.check_out_date)
    with pytest.raises(HTTPException, match="must differ") as error:
        validate_changed_dates(reservation, request)
    assert error.value.status_code == 422


@pytest.mark.parametrize("field,new_date", [("check_in_date", "2026-11-02"), ("check_out_date", "2026-11-04")])
def test_changing_either_date_is_sufficient(records, field, new_date):
    reservation, _, _, _ = records
    request = change_request(**{
        "check_in_date": reservation.check_in_date, "check_out_date": reservation.check_out_date, field: new_date,
    })
    validate_changed_dates(reservation, request)


def test_change_requests_require_both_dates_and_reject_client_authority_fields():
    for schema, fields in (
        (ReservationChangeQuoteRequest, change_request().model_dump()),
        (ReservationChangeConfirmRequest, confirm_request().model_dump()),
    ):
        for field in ("check_in_date", "check_out_date"):
            with pytest.raises(ValidationError):
                schema(**{key: value for key, value in fields.items() if key != field})
        for field in ("user_id", "hotel_id", "property_token", "q", "adults", "children",
                      "reward_points", "service_fee", "tax", "total_price", "payment_amount"):
            with pytest.raises(ValidationError) as error:
                schema(**fields, **{field: 1})
            assert error.value.errors()[0]["type"] == "extra_forbidden"


@pytest.mark.parametrize("field", ["quote_id", "accept_quote", "price_per_night", "accepted_payment_amount"])
def test_confirmation_requires_a_review_and_explicit_price_acknowledgements(field):
    fields = confirm_request().model_dump()
    fields.pop(field)
    with pytest.raises(ValidationError):
        ReservationChangeConfirmRequest(**fields)


@pytest.mark.parametrize("changes", [
    {"quote_id": " "}, {"accept_quote": False}, {"accept_quote": 1}, {"accept_quote": "true"},
    {"price_per_night": 0}, {"price_per_night": float("inf")},
    {"accepted_payment_amount": -1}, {"accepted_payment_amount": float("nan")},
])
def test_malformed_confirmations_are_rejected(changes):
    with pytest.raises(ValidationError):
        confirm_request(**changes)


@pytest.mark.parametrize("field", ["q", "adults", "children"])
def test_revalidation_context_is_required_without_occupancy_defaults(field):
    fields = context().model_dump()
    fields.pop(field)
    with pytest.raises(ValidationError):
        ReservationChangeRevalidationContext(**fields)


@pytest.mark.parametrize("changes", [
    {"q": " "}, {"adults": 0}, {"adults": True}, {"children": -1}, {"children": "0"},
    {"currency": "EUR"}, {"gl": "gb"}, {"hl": "fr"}, {"property_token": "property-B"},
])
def test_invalid_or_client_selected_property_context_is_rejected(changes):
    with pytest.raises(ValidationError):
        context(**changes)


def test_revalidation_request_uses_linked_property_new_dates_and_explicit_occupancy(records):
    reservation, _, room, hotel = records
    result = build_change_revalidation_request(reservation, room, hotel, change_request(), context())
    assert result.model_dump() == {
        "property_token": "property-A", "q": "San Jose hotels",
        **change_request().model_dump(), "adults": 3, "children": 1,
        "currency": "USD", "gl": "us", "hl": "en", "displayed_price_per_night": None,
    }


def test_missing_historical_context_fails_closed(records):
    reservation, _, room, hotel = records
    with pytest.raises(HTTPException, match="must be established") as error:
        build_change_revalidation_request(reservation, room, hotel, change_request(), None)
    assert error.value.status_code == 409


@pytest.mark.parametrize("case", ["missing-room", "missing-hotel", "wrong-room", "wrong-hotel"])
def test_property_associations_must_match_the_reservation(records, case):
    reservation, _, room, hotel = records
    if case == "missing-room":
        room = None
    elif case == "missing-hotel":
        hotel = None
    elif case == "wrong-room":
        room.room_type_id = 999
    else:
        hotel.hotel_id = 999
    with pytest.raises(HTTPException) as error:
        build_change_revalidation_request(reservation, room, hotel, change_request(), context())
    assert error.value.status_code == 409


@pytest.mark.parametrize("token", ["legacy:4", "partner:4", "", None])
def test_unusable_historical_property_tokens_are_rejected(records, token):
    reservation, _, room, hotel = records
    hotel.hotel_token = token
    with pytest.raises(HTTPException, match="context is invalid") as error:
        build_change_revalidation_request(reservation, room, hotel, change_request(), context())
    assert error.value.status_code == 409


def test_review_reuses_existing_quote_contract_and_requires_aware_expiry():
    response = review()
    assert isinstance(response.quote, HotelRevalidationResponse)
    assert response.model_dump(mode="json")["quote"]["likehome_payment_amount"] == 226.80
    with pytest.raises(ValidationError):
        review(expires_at=NOW.replace(tzinfo=None))


def test_review_requires_identity_expiry_and_authoritative_quote():
    fields = review().model_dump()
    for field in ("reservation_id", "quote_id", "expires_at", "quote"):
        with pytest.raises(ValidationError):
            ReservationChangeQuoteResponse(**{key: value for key, value in fields.items() if key != field})


def test_accepted_server_review_and_matching_fresh_quote_are_valid():
    check_acceptance()


@pytest.mark.parametrize("changes", [
    {"reservation_id": 999}, {"quote_owner_user_id": 8},
    {"now": NOW + timedelta(hours=1)}, {"now": NOW + timedelta(hours=2)},
])
def test_other_reservation_owner_or_expired_review_is_rejected(changes):
    with pytest.raises(HTTPException) as error:
        check_acceptance(**changes)
    assert error.value.status_code == 409


def test_unissued_review_is_rejected():
    with pytest.raises(HTTPException) as error:
        validate_change_quote_acceptance(
            confirm_request(), None, provider_quote(),
            reservation_id=1, user_id=7, quote_owner_user_id=7, now=NOW,
        )
    assert error.value.status_code == 409


@pytest.mark.parametrize("changes", [
    {"quote_id": "other-review"}, {"check_in_date": "2026-11-05"},
    {"price_per_night": 1}, {"accepted_payment_amount": 1},
])
def test_client_acceptance_cannot_change_review_identity_dates_or_price(changes):
    with pytest.raises(HTTPException) as error:
        check_acceptance(request=confirm_request(**changes))
    assert error.value.status_code == 409


@pytest.mark.parametrize("changes", [
    {"property_token": "property-B"}, {"adults": 2}, {"children": 0},
    {"check_out_date": date(2026, 11, 7)}, {"current_price_per_night": 101},
    {"provider_base_total": 201}, {"likehome_reservation_total": 211}, {"likehome_payment_amount": 227.88},
])
def test_fresh_quote_changes_require_new_review(changes):
    with pytest.raises(HTTPException) as error:
        check_acceptance(fresh_quote=provider_quote(**changes))
    assert error.value.status_code == 409


def test_quote_clock_must_be_timezone_aware():
    with pytest.raises(ValueError, match="timezone-aware"):
        check_acceptance(now=NOW.replace(tzinfo=None))


def test_validation_does_not_mutate_reservation_payment_room_or_hotel(records):
    reservation, payment, room, hotel = records
    before = [
        {column.name: getattr(record, column.name) for column in record.__table__.columns}
        for record in records
    ]
    validate_reservation_change_eligibility(reservation, [payment], 7)
    build_change_revalidation_request(reservation, room, hotel, change_request(), context())
    check_acceptance()
    after = [
        {column.name: getattr(record, column.name) for column in record.__table__.columns}
        for record in records
    ]
    assert after == before


def test_existing_booking_routes_are_unchanged_and_only_change_review_is_registered():
    assert {(route.path, frozenset(route.methods)) for route in router.routes} == {
        ("/bookings/create", frozenset({"POST"})),
        ("/bookings/get-all-bookings", frozenset({"GET"})),
        ("/bookings/get-all-payments", frozenset({"GET"})),
        ("/bookings/get-booking-details/{reservation_id}", frozenset({"GET"})),
        ("/bookings/get-payment-details/{payment_id}", frozenset({"GET"})),
        ("/bookings/pay/{payment_id}", frozenset({"POST"})),
        ("/bookings/cancel-booking/{reservation_id}", frozenset({"POST"})),
        ("/bookings/{reservation_id}/change-quote", frozenset({"POST"})),
    }
