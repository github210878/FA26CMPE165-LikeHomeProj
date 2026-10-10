"""Public change contracts using real services/auth, SQLite and a mock provider.

No application server, development database, external API or payment processor
is used. The existing MySQL checkpoint covers the unchanged locking strategy.
"""

from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import event
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.models import Payment, Reservation, ReservationChangeAdjustment, User
from app.repositories import booking_dao
from app.schemas import booking_schema
from app.schemas.reservation_change_schema import ReservationChangeReceiptResponse
from app.schemas.reservation_change_payment_schema import (
    AdjustmentSettlementResponse, ReservationFinancialSummary,
)
from app.services import hotel_service, reservation_change_validation
from app.utilities import reservation_change_quote as signing, serpapi_client

from test_reservation_change_confirmation import snapshot
from test_reservation_change_quotes import NOW, REQUEST, headers, quote_app

CONFIRM = "/bookings/1/change-confirm"
PAY = "/bookings/1/adjustments/1/pay"
SUMMARY = "/bookings/1/financial-summary"
ACK = {"accepted_amount": 81.44, "reservation_revision": 1, "accept_payment": True}


@pytest.fixture
def api(quote_app, monkeypatch):
    clock = {"now": NOW}

    class QuoteClock(datetime):
        @classmethod
        def now(cls, tz=None):
            value = clock["now"]
            return value.astimezone(tz) if tz is not None else value.replace(tzinfo=None)

    # Use the real request dependencies/services; only their clock is fixed.
    monkeypatch.setattr(signing, "datetime", QuoteClock)
    monkeypatch.setattr(reservation_change_validation, "datetime", QuoteClock)
    yield (*quote_app, clock)


def reviewed_body(api, **changes):
    client = api[0]
    response = client.post("/bookings/1/change-quote", headers=headers(), json={**REQUEST, **changes})
    assert response.status_code == 200, response.json()
    review = response.json()
    return {
        "check_in_date": review["quote"]["check_in_date"],
        "check_out_date": review["quote"]["check_out_date"],
        "quote_id": review["quote_id"], "accept_quote": True,
        "price_per_night": review["quote"]["current_price_per_night"],
        "accepted_payment_amount": review["quote"]["likehome_payment_amount"],
    }


def confirm(api, body=None, **review_changes):
    response = api[0].post(CONFIRM, headers=headers(), json=body or reviewed_body(api, **review_changes))
    assert response.status_code == 200, response.json()
    ReservationChangeReceiptResponse.model_validate(response.json())
    return response.json()


def paid_baseline(api, amount=100):
    with Session(api[1]) as db:
        payment = db.get(Payment, 1)
        payment.payment_status = "paid"
        payment.amount = amount
        db.commit()


@pytest.fixture
def charge_api(api):
    paid_baseline(api)
    receipt = confirm(api)
    assert receipt["adjustment"] == {
        "adjustment_id": 1, "kind": "charge", "amount": "81.44", "status": "pending",
    }
    return api


def financial_summary(api):
    response = api[0].get(SUMMARY, headers=headers())
    assert response.status_code == 200, response.json()
    ReservationFinancialSummary.model_validate(response.json())
    return response.json()


@pytest.mark.parametrize("status,amount,kind,difference", [
    ("pending", 226.8, None, "-45.36"),
    ("paid", 100, "charge", "81.44"),
    ("paid", 226.8, "credit", "-45.36"),
])
def test_confirmation_returns_exact_receipt_with_expected_financial_effects(api, status, amount, kind, difference):
    client, engine, calls, _, _ = api
    if status == "paid":
        paid_baseline(api, amount)
    body = reviewed_body(api)
    before = snapshot(engine)
    commits = []
    listener = lambda db: commits.append(True)
    event.listen(Session, "after_commit", listener)
    try:
        receipt = confirm(api, body)
    finally:
        event.remove(Session, "after_commit", listener)
    after = snapshot(engine)
    assert commits == [True] and len(calls) == 2
    assert receipt["revision"] == 1 and receipt["payment_difference"] == difference
    assert receipt["reservation_total"] == "168.00" and receipt["payment_obligation"] == "181.44"
    assert receipt["booking_payment_status"] == status
    assert receipt == after["reservation_change_events"][0]["response_json"]
    assert "quote_id" not in receipt and body["quote_id"] not in str(receipt)
    assert len(after["payments"]) == 1
    if kind is None:
        assert receipt["adjustment"] is None and after["reservation_change_adjustments"] == []
        assert after["payments"][0]["amount"] == 181.44
        payment = client.post("/bookings/pay/1", headers=headers())
        assert payment.status_code == 200 and payment.json()["amount"] == 181.44
    else:
        assert receipt["adjustment"]["kind"] == kind
        assert after["payments"] == before["payments"]


@pytest.mark.parametrize("route,method", [(CONFIRM, "post"), (PAY, "post"), (SUMMARY, "get")])
@pytest.mark.parametrize("credentials", ["missing", "invalid", "partner", "inactive", "revoked"])
def test_authentication_is_required_and_customer_boundary_is_enforced(api, route, method, credentials):
    client, engine, calls, _, _ = api
    request_headers = headers(subject_type="partner") if credentials == "partner" else headers()
    if credentials == "missing":
        request_headers = {}
    elif credentials == "invalid":
        request_headers = {"Authorization": "Bearer invalid"}
    elif credentials in ("inactive", "revoked"):
        with Session(engine) as db:
            user = db.get(User, 7)
            if credentials == "inactive":
                user.status = "deleted"
            else:
                user.session_version += 1
            db.commit()
    before = snapshot(engine)
    kwargs = {"headers": request_headers}
    if method == "post":
        kwargs["json"] = ACK if route == PAY else {}
    response = getattr(client, method)(route, **kwargs)
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert snapshot(engine) == before and calls == []


@pytest.mark.parametrize("path,user_id", [(CONFIRM, 8), ("/bookings/999/change-confirm", 7)])
def test_confirmation_owner_and_missing_reservation_return_same_safe_404(api, path, user_id):
    body = reviewed_body(api)
    before = snapshot(api[1])
    response = api[0].post(path, headers=headers(user_id), json=body)
    assert response.status_code == 404 and response.json() == {"detail": "Reservation not found"}
    assert snapshot(api[1]) == before and len(api[2]) == 1


@pytest.mark.parametrize("case", ["expired", "tampered", "stale-revision", "overlap"])
def test_invalid_or_conflicting_quotes_do_not_write_or_revalidate_provider(api, case):
    client, engine, calls, _, clock = api
    body = reviewed_body(api)
    if case == "expired":
        clock["now"] += timedelta(minutes=10)
    elif case == "tampered":
        head, payload, signature = body["quote_id"].split(".")
        signature = ("A" if signature[0] != "A" else "B") + signature[1:]
        body["quote_id"] = f"{head}.{payload}.{signature}"
    else:
        with Session(engine) as db:
            if case == "stale-revision":
                db.get(Reservation, 1).revision += 1
            else:
                db.add(Reservation(user_id=7, room_type_id=2, total_price=100, status="confirmed",
                                   check_in_date=date(2026, 11, 5), check_out_date=date(2026, 11, 7)))
            db.commit()
    before = snapshot(engine)
    response = client.post(CONFIRM, headers=headers(), json=body)
    assert response.status_code == 409
    assert body["quote_id"] not in response.text
    assert snapshot(engine) == before and len(calls) == 1


@pytest.mark.parametrize("case,expected", [
    ("changed-price", 409), ("unavailable", 409), ("wrong_property", 409),
    ("network", 502), ("timeout", 504),
])
def test_fresh_provider_failures_keep_safe_statuses_and_rollback(api, monkeypatch, case, expected):
    client, engine, calls, state, _ = api
    body = reviewed_body(api)
    if case == "changed-price":
        original = hotel_service.revalidate_hotel
        monkeypatch.setattr(hotel_service, "revalidate_hotel", lambda request:
                            original(request).model_copy(update={"likehome_payment_amount": 181.45}))
    elif case in ("network", "timeout"):
        error = serpapi_client.SerpApiRequestError if case == "network" else serpapi_client.SerpApiTimeoutError
        state["error"] = error("private-provider-detail")
    else:
        state[case] = True
    before = snapshot(engine)
    response = client.post(CONFIRM, headers=headers(), json=body)
    assert response.status_code == expected
    assert "private-provider-detail" not in response.text and body["quote_id"] not in response.text
    assert snapshot(engine) == before and len(calls) == 2


def test_confirmation_retries_preserve_receipt_after_expiry_past_dates_and_cancellation(api, monkeypatch):
    body = reviewed_body(api)
    receipt = confirm(api, body)
    committed = snapshot(api[1])
    assert confirm(api, body) == receipt and snapshot(api[1]) == committed
    assert api[0].post("/bookings/cancel-booking/1", headers=headers()).status_code == 200
    cancelled = snapshot(api[1])
    api[4]["now"] += timedelta(days=100)

    class LaterDate(date):
        @classmethod
        def today(cls):
            return cls(2027, 1, 7)

    monkeypatch.setattr(booking_schema, "date", LaterDate)
    assert confirm(api, body) == receipt
    assert snapshot(api[1]) == cancelled and len(api[2]) == 2


def test_expired_unconsumed_quote_with_historical_dates_cannot_authorize_mutation(api, monkeypatch):
    body = reviewed_body(api)
    api[4]["now"] += timedelta(days=100)

    class LaterDate(date):
        @classmethod
        def today(cls):
            return cls(2027, 1, 7)

    monkeypatch.setattr(booking_schema, "date", LaterDate)
    before = snapshot(api[1])
    response = api[0].post(CONFIRM, headers=headers(), json=body)
    assert response.status_code == 422
    assert snapshot(api[1]) == before and len(api[2]) == 1


@pytest.mark.parametrize("changes", [{"accepted_payment_amount": 181.45}, {"price_per_night": 81},
                                        {"check_out_date": "2026-11-07"}])
def test_conflicting_reuse_of_committed_quote_is_rejected(api, changes):
    body = reviewed_body(api)
    confirm(api, body)
    before = snapshot(api[1])
    response = api[0].post(CONFIRM, headers=headers(), json={**body, **changes})
    assert response.status_code == 409
    assert snapshot(api[1]) == before and len(api[2]) == 2


@pytest.mark.parametrize("changes", [
    {"accept_quote": False}, {"accept_quote": "true"}, {"user_id": 8},
    {"hotel_id": 2}, {"property_token": "property-B"}, {"price_per_night": 0},
    {"quote_id": "x" * 16385}, {"check_out_date": "2026-11-04"},
])
def test_confirmation_validation_is_strict_and_never_echoes_signed_quote(api, changes):
    body = {**reviewed_body(api), **changes}
    before = snapshot(api[1])
    response = api[0].post(CONFIRM, headers=headers(), json=body)
    assert response.status_code == 422
    assert body["quote_id"] not in response.text
    assert all(set(error) == {"loc", "msg", "type"} for error in response.json()["detail"])
    assert snapshot(api[1]) == before and len(api[2]) == 1


@pytest.mark.parametrize("failure", ["after-flush", "commit"])
def test_confirmation_failure_rolls_back_flushed_records_without_detail_leak(api, monkeypatch, failure):
    paid_baseline(api)
    body = reviewed_body(api)
    before = snapshot(api[1])
    if failure == "after-flush":
        original = booking_dao.stage_booking_record

        def fail_after_flush(db, record):
            result = original(db, record)
            if isinstance(record, ReservationChangeAdjustment):
                raise SQLAlchemyError("private-sql-detail")
            return result

        monkeypatch.setattr(booking_dao, "stage_booking_record", fail_after_flush)
    else:
        def fail_commit(db):
            raise SQLAlchemyError("private-sql-detail")
        monkeypatch.setattr(Session, "commit", fail_commit)
    response = api[0].post(CONFIRM, headers=headers(), json=body)
    assert response.status_code == 500 and response.json() == {"detail": "Failed to change reservation"}
    assert snapshot(api[1]) == before and len(api[2]) == 2


@pytest.mark.parametrize("status", ["pending", "failed"])
def test_settlement_and_paid_retry_preserve_original_payment_and_history(charge_api, status):
    client, engine, calls, _, _ = charge_api
    with Session(engine) as db:
        db.get(ReservationChangeAdjustment, 1).status = status
        db.commit()
    before = snapshot(engine)
    count = len(calls)
    response = client.post(PAY, headers=headers(), json=ACK)
    assert response.status_code == 200
    paid = response.json()
    AdjustmentSettlementResponse.model_validate(paid)
    assert paid["amount"] == 81.44 and paid["status"] == "paid"
    assert paid["settled_at"] == NOW.isoformat().replace("+00:00", "Z")
    after = snapshot(engine)
    assert after["payments"] == before["payments"]
    assert after["reservation_change_events"] == before["reservation_change_events"]
    assert after["reservations"][0]["revision"] == 2
    assert client.post(PAY, headers=headers(), json=ACK).json() == paid
    assert snapshot(engine) == after and len(calls) == count


@pytest.mark.parametrize("path,user_id", [
    (PAY, 8), ("/bookings/1/adjustments/999/pay", 7),
    ("/bookings/2/adjustments/1/pay", 7), ("/bookings/999/adjustments/1/pay", 7),
])
def test_settlement_missing_nonowned_and_mismatched_path_are_indistinguishable(charge_api, path, user_id):
    # Reservation 2 also belongs to this owner: ownership alone cannot validate the URL.
    with Session(charge_api[1]) as db:
        db.add(Reservation(reservation_id=2, user_id=7, room_type_id=2, total_price=100,
                           status="confirmed", check_in_date=date(2026, 11, 9), check_out_date=date(2026, 11, 10)))
        db.commit()
    before = snapshot(charge_api[1])
    count = len(charge_api[2])
    response = charge_api[0].post(path, headers=headers(user_id), json=ACK)
    assert response.status_code == 404 and response.json() == {"detail": "Adjustment not found"}
    assert snapshot(charge_api[1]) == before and len(charge_api[2]) == count


@pytest.mark.parametrize("changes", [{"accepted_amount": 81.45}, {"reservation_revision": 0},
                                        {"reservation_revision": 2}])
def test_settlement_stale_review_rejects_without_writes(charge_api, changes):
    before = snapshot(charge_api[1])
    count = len(charge_api[2])
    response = charge_api[0].post(PAY, headers=headers(), json={**ACK, **changes})
    assert response.status_code == 409
    assert snapshot(charge_api[1]) == before and len(charge_api[2]) == count


@pytest.mark.parametrize("changes", [{"accept_payment": False}, {"accept_payment": "true"},
                                        {"accepted_amount": True}, {"accepted_amount": "NaN"},
                                        {"reservation_revision": "1"}, {"user_id": 8}, {"amount": 1}])
def test_settlement_validation_rejects_client_authority_fields(charge_api, changes):
    before = snapshot(charge_api[1])
    response = charge_api[0].post(PAY, headers=headers(), json={**ACK, **changes})
    assert response.status_code == 422
    assert snapshot(charge_api[1]) == before


def test_recorded_credit_cannot_be_paid(api):
    paid_baseline(api, 226.8)
    receipt = confirm(api)
    assert receipt["adjustment"]["kind"] == "credit"
    before = snapshot(api[1])
    response = api[0].post(PAY, headers=headers(), json={**ACK, "accepted_amount": 45.36})
    assert response.status_code == 409 and snapshot(api[1]) == before


@pytest.mark.parametrize("case", ["voided", "cancelled"])
def test_voided_charge_and_cancelled_reservation_cannot_be_paid(charge_api, case):
    client, engine, _, _, _ = charge_api
    if case == "cancelled":
        assert client.post("/bookings/cancel-booking/1", headers=headers()).status_code == 200
    else:
        with Session(engine) as db:
            db.get(ReservationChangeAdjustment, 1).status = "voided"
            db.commit()
    before = snapshot(engine)
    response = client.post(PAY, headers=headers(), json=ACK)
    assert response.status_code == 409 and snapshot(engine) == before


def test_settlement_commit_failure_returns_safe_error_and_rolls_back(charge_api, monkeypatch):
    before = snapshot(charge_api[1])

    def fail_commit(db):
        raise SQLAlchemyError("private-sql-detail")

    monkeypatch.setattr(Session, "commit", fail_commit)
    response = charge_api[0].post(PAY, headers=headers(), json=ACK)
    assert response.status_code == 500
    assert response.json() == {"detail": "Failed to record internal adjustment payment"}
    assert snapshot(charge_api[1]) == before


@pytest.mark.parametrize("case", ["unmodified", "modified-unpaid", "pending", "failed", "settled", "credit"])
def test_summary_returns_numeric_original_payment_and_separate_ledger_buckets(api, case):
    if case in ("pending", "failed", "settled", "credit"):
        paid_baseline(api, 226.8 if case == "credit" else 100)
    if case != "unmodified":
        confirm(api)
    if case == "settled":
        assert api[0].post(PAY, headers=headers(), json=ACK).status_code == 200
    elif case == "failed":
        with Session(api[1]) as db:
            db.get(ReservationChangeAdjustment, 1).status = "failed"
            db.commit()
    before = snapshot(api[1])
    provider_count = len(api[2])
    statements = []

    def record(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement.lstrip().split()[0].upper())

    event.listen(api[1], "before_cursor_execute", record)
    try:
        value = financial_summary(api)
    finally:
        event.remove(api[1], "before_cursor_execute", record)
    assert snapshot(api[1]) == before and len(api[2]) == provider_count
    assert not {"INSERT", "UPDATE", "DELETE", "REPLACE"}.intersection(statements)
    assert value["current_reservation_total"] == (210 if case == "unmodified" else 168)
    assert value["current_booking_obligation"] == (226.8 if case == "unmodified" else 181.44)
    assert value["original_booking_payment"]["amount"] == (
        100 if case in ("pending", "failed", "settled") else 181.44 if case == "modified-unpaid" else 226.8
    )
    assert value["latest_change_id"] == (None if case == "unmodified" else 1)
    for bucket, expected in {
        "pending_additional_charges": 81.44 if case == "pending" else 0,
        "failed_additional_charges": 81.44 if case == "failed" else 0,
        "paid_additional_charges": 81.44 if case == "settled" else 0,
        "recorded_internal_credits": 45.36 if case == "credit" else 0,
        "outstanding_additional_amount": 81.44 if case in ("pending", "failed") else 0,
        "outstanding_booking_amount": 226.8 if case == "unmodified" else 181.44 if case == "modified-unpaid" else 0,
    }.items():
        assert value[bucket] == expected and isinstance(value[bucket], (int, float))


def test_multiple_changes_and_cancellation_summary_do_not_double_count_or_rewrite_receipts(api):
    paid_baseline(api, 226.8)
    first_body = reviewed_body(api)
    first = confirm(api, first_body)
    second = confirm(api, check_in_date="2026-11-08", check_out_date="2026-11-11")
    assert second["previous_payment_obligation"] == "181.44"
    value = financial_summary(api)
    assert value["latest_change_id"] == 2 and value["current_booking_obligation"] == 272.16
    assert value["recorded_internal_credits"] == 45.36
    assert value["pending_additional_charges"] == value["outstanding_additional_amount"] == 90.72
    second_path = "/bookings/1/adjustments/2/pay"
    paid = api[0].post(second_path, headers=headers(), json={**ACK, "accepted_amount": 90.72, "reservation_revision": 2})
    assert paid.status_code == 200
    assert financial_summary(api)["paid_additional_charges"] == 90.72
    events_before_cancel = snapshot(api[1])["reservation_change_events"]
    cancellation = api[0].post("/bookings/cancel-booking/1", headers=headers())
    assert cancellation.status_code == 200
    before = snapshot(api[1])
    count = len(api[2])
    value = financial_summary(api)
    assert value["reservation_status"] == "cancelled"
    assert value["original_booking_payment"]["amount"] == 226.8
    assert value["original_booking_payment"]["payment_status"] == "refunded"
    assert value["paid_additional_charges"] == value["reconciliation_credits"] == 90.72
    assert value["recorded_internal_credits"] == value["reconciliation_debits"] == 45.36
    assert value["outstanding_additional_amount"] == value["outstanding_booking_amount"] == 0
    assert value["cancellation_payment"]["amount"] == value["outstanding_cancellation_amount"] == 50.4
    assert len(value["adjustments"]) == len(value["cancellation_reconciliations"]) == 2
    assert all(row["status"] == "recorded" for row in value["cancellation_reconciliations"])
    assert before["reservation_change_events"] == events_before_cancel
    assert confirm(api, first_body) == first
    assert snapshot(api[1]) == before and len(api[2]) == count


def test_cancelled_pending_charge_is_voided_in_summary(charge_api):
    assert charge_api[0].post("/bookings/cancel-booking/1", headers=headers()).status_code == 200
    value = financial_summary(charge_api)
    assert value["voided_additional_charges"] == 81.44
    assert value["outstanding_additional_amount"] == value["pending_additional_charges"] == 0
    assert value["adjustments"][0]["status"] == "voided"
    assert value["cancellation_reconciliations"] == []


@pytest.mark.parametrize("path,user_id", [(SUMMARY, 8), ("/bookings/999/financial-summary", 7)])
def test_summary_nonowner_and_missing_reservation_return_same_404(api, path, user_id):
    before = snapshot(api[1])
    response = api[0].get(path, headers=headers(user_id))
    assert response.status_code == 404 and response.json() == {"detail": "Reservation not found"}
    assert snapshot(api[1]) == before and api[2] == []


def test_summary_and_settlement_never_call_provider(charge_api, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Unexpected provider request")

    monkeypatch.setattr(serpapi_client, "search_google_hotels", forbidden)
    financial_summary(charge_api)
    assert charge_api[0].post(PAY, headers=headers(), json=ACK).status_code == 200
    financial_summary(charge_api)


@pytest.mark.parametrize("method,path", [
    ("post", "/bookings/0/change-confirm"), ("post", "/bookings/-1/change-confirm"),
    ("post", "/bookings/0/adjustments/1/pay"), ("post", "/bookings/1/adjustments/0/pay"),
    ("get", "/bookings/0/financial-summary"), ("get", "/bookings/abc/financial-summary"),
])
def test_new_route_identifiers_must_be_positive_integers(api, method, path):
    body = reviewed_body(api) if "change-confirm" in path else ACK
    before = snapshot(api[1])
    kwargs = {"headers": headers()}
    if method == "post":
        kwargs["json"] = body
    response = getattr(api[0], method)(path, **kwargs)
    assert response.status_code == 422 and snapshot(api[1]) == before


def test_openapi_registers_typed_authenticated_routes_once_and_preserves_existing_paths():
    from app.main import app

    expected = {
        "/bookings/{reservation_id}/change-confirm": ("post", "ReservationChangeReceiptRequest", "ReservationChangeReceiptResponse"),
        "/bookings/{reservation_id}/adjustments/{adjustment_id}/pay": ("post", "AdjustmentSettlementRequest", "AdjustmentSettlementResponse"),
        "/bookings/{reservation_id}/financial-summary": ("get", None, "ReservationFinancialSummary"),
    }
    def effective_routes(router):
        # Current FastAPI retains included routers lazily instead of flattening.
        for route in router.routes:
            included = getattr(route, "original_router", None)
            if included is not None:
                yield from effective_routes(included)
            else:
                yield route

    routes = [(route.path, method) for route in effective_routes(app)
              for method in getattr(route, "methods", ())]
    assert len(routes) == len(set(routes))
    schema = app.openapi()
    operation_ids = []
    for path, (method, request_model, response_model) in expected.items():
        assert routes.count((path, method.upper())) == 1
        operation = schema["paths"][path][method]
        operation_ids.append(operation["operationId"])
        assert operation["security"] == [{"HTTPBearer": []}]
        assert operation["responses"]["200"]["content"]["application/json"]["schema"]["$ref"].endswith("/" + response_model)
        if request_model:
            body = operation["requestBody"]
            assert body["required"] is True
            assert body["content"]["application/json"]["schema"]["$ref"].endswith("/" + request_model)
            assert schema["components"]["schemas"][request_model]["additionalProperties"] is False
        for parameter in operation["parameters"]:
            assert parameter["in"] == "path" and parameter["schema"]["exclusiveMinimum"] == 0
    assert len(operation_ids) == len(set(operation_ids))
    for path in ("/hotels/search", "/bookings/create", "/bookings/pay/{payment_id}",
                 "/bookings/cancel-booking/{reservation_id}", "/bookings/{reservation_id}/change-quote"):
        assert path in schema["paths"]
