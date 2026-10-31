"""Dormant contracts only: synthetic data, no application, database or provider.

The frontend compatibility check evaluates its existing pure validators in a
Node VM, without importing its API/auth modules or issuing an HTTP request.
"""

import importlib
import importlib.abc
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
from datetime import date, datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest
from pydantic import ValidationError


BACKEND = Path(__file__).resolve().parents[1]
FRONTEND = BACKEND.parent / "frontend" / "likehome"
SCHEMA_MODULES = (
    "app.schemas.reservation_change_schema",
    "app.schemas.reservation_change_adjustment_schema",
    "app.schemas.reservation_change_payment_schema",
)
FORBIDDEN_IMPORTS = (
    "app.config", "app.main", "app.models", "app.repositories", "app.routers",
    "app.services", "sqlalchemy", "pymysql", "sqlite3", "requests", "httpx",
)
DATE_IN, DATE_OUT = "2026-10-05", "2026-10-07"
STAMP = "2026-09-29T12:00:00.123456Z"
# Deliberately not a JWT, bearer token or usable provider identifier.
OPAQUE_ID = "  synthetic opaque review\t"


class NoInfrastructure(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if any(fullname == name or fullname.startswith(name + ".") for name in FORBIDDEN_IMPORTS):
            raise AssertionError("Pure contracts must not import application infrastructure")
        return None


def no_network(*args, **kwargs):
    raise AssertionError("Pure contracts must not access the network")


@pytest.fixture(autouse=True)
def isolated_contract_boundary(monkeypatch):
    guard = NoInfrastructure()
    monkeypatch.setattr(sys, "meta_path", [guard, *sys.meta_path])
    monkeypatch.setattr(socket, "create_connection", no_network)
    monkeypatch.setattr(socket.socket, "connect", no_network)
    monkeypatch.setattr(socket.socket, "connect_ex", no_network)
    monkeypatch.setattr(socket, "getaddrinfo", no_network)


@pytest.fixture
def contracts(isolated_contract_boundary):
    modules = [importlib.import_module(name) for name in SCHEMA_MODULES]
    return SimpleNamespace(**{
        name: getattr(module, name)
        for module in modules for name in vars(module)
        if name.startswith(("ReservationChange", "Adjustment", "ReservationFinancial"))
    })


def review(**changes):
    return {"check_in_date": DATE_IN, "check_out_date": DATE_OUT,
            "q": "Synthetic destination", "adults": 2, "children": 1, **changes}


def confirmation(**changes):
    return {"check_in_date": DATE_IN, "check_out_date": DATE_OUT,
            "quote_id": OPAQUE_ID, "accept_quote": True,
            "price_per_night": 100, "accepted_payment_amount": 226.8, **changes}


def detail(**changes):
    return {"adjustment_id": 11, "change_id": 51, "reservation_id": 41,
            "currency": "USD", "entry_role": "price_change", "reconciles_adjustment_id": None,
            "kind": "charge", "amount": 40, "status": "paid", "settled_at": STAMP, **changes}


def financial_summary():
    return {
        "reservation_id": 41, "reservation_revision": 7, "reservation_status": "confirmed",
        "currency": "USD", "latest_change_id": 51, "current_reservation_total": 250,
        "current_booking_obligation": 270,
        "original_booking_payment": {"payment_id": 61, "reservation_id": 41,
                                     "amount": 200, "payment_type": "booking", "payment_status": "paid"},
        "paid_additional_charges": 40, "pending_additional_charges": 10,
        "failed_additional_charges": 5, "recorded_internal_credits": 10,
        "outstanding_additional_amount": 15,
        "adjustments": [detail(), detail(adjustment_id=12, kind="credit", amount=10,
                                         status="recorded", settled_at=None),
                        detail(adjustment_id=13, amount=10, status="pending", settled_at=None),
                        detail(adjustment_id=14, amount=5, status="failed", settled_at=None),
                        detail(adjustment_id=15, amount=2, status="voided", settled_at=None)],
        "voided_additional_charges": 2, "cancellation_reconciliations": [],
        "reconciliation_credits": 0, "reconciliation_debits": 0, "cancellation_payment": None,
        "outstanding_cancellation_amount": 0, "outstanding_booking_amount": 0,
    }


def cancelled_summary():
    result = financial_summary()
    result.update(reservation_status="cancelled", pending_additional_charges=0,
                  failed_additional_charges=0, outstanding_additional_amount=0,
                  voided_additional_charges=17, reconciliation_credits=40, reconciliation_debits=10,
                  outstanding_cancellation_amount=50)
    result["original_booking_payment"]["payment_status"] = "refunded"
    for entry in result["adjustments"]:
        if entry["status"] in ("pending", "failed"):
            entry["status"] = "voided"
    result["cancellation_payment"] = {"payment_id": 62, "reservation_id": 41, "amount": 50,
                                      "payment_type": "cancellation", "payment_status": "pending"}
    result["cancellation_reconciliations"] = [
        detail(adjustment_id=16, entry_role="cancellation_reconciliation", reconciles_adjustment_id=11,
               kind="credit", amount=40, status="recorded", settled_at=None),
        detail(adjustment_id=17, entry_role="cancellation_reconciliation", reconciles_adjustment_id=12,
               kind="charge", amount=10, status="recorded", settled_at=None),
    ]
    return result


def quote_response(**changes):
    return {"reservation_id": 41, "quote_id": OPAQUE_ID, "expires_at": "2026-09-29T12:10:00Z",
            "quote": {"property_token": "synthetic-property", "hotel_name": "Synthetic hotel",
                      "check_in_date": DATE_IN, "check_out_date": DATE_OUT, "adults": 2, "children": 1,
                      "currency": "USD", "number_of_nights": 2, "availability": "available",
                      "rate_rule": "lowest_eligible_provider_base_total", "source": "Synthetic provider",
                      "guest_capacity": 3, "current_price_per_night": 100, "provider_base_total": 200,
                      "provider_total_with_taxes_fees": None, "likehome_reservation_total": 210,
                      "likehome_payment_amount": 226.8, "price_changed": None}, **changes}


def receipt(**changes):
    return {"change_id": 51, "reservation_id": 41, "revision": 7, "room_type_id": 31,
            "check_in_date": DATE_IN, "check_out_date": DATE_OUT, "reservation_total": "210.00",
            "payment_obligation": "226.80", "previous_payment_obligation": "200.00",
            "payment_difference": "26.80", "booking_payment_id": 61, "booking_payment_status": "paid",
            "adjustment": {"adjustment_id": 11, "kind": "charge", "amount": "26.80", "status": "pending"},
            **changes}


def settlement(**changes):
    return {"accepted_amount": 40, "reservation_revision": 7, "accept_payment": True, **changes}


def record(**changes):
    return {"change_id": 51, "kind": "charge", "amount": Decimal("40.00"), "status": "pending", **changes}


def test_fresh_imports_and_parsing_cannot_load_infrastructure():
    script = '''
import importlib, importlib.abc, json, socket, sys
sys.path.insert(0, sys.argv[1])
blocked = tuple(json.loads(sys.argv[2]))
class Guard(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if any(fullname == p or fullname.startswith(p + '.') for p in blocked):
            raise AssertionError('Infrastructure import during pure schema parsing')
sys.meta_path.insert(0, Guard())
def deny(*args, **kwargs):
    raise AssertionError('Network operation during pure schema parsing')
socket.create_connection = socket.getaddrinfo = deny
socket.socket.connect = socket.socket.connect_ex = deny
for name in json.loads(sys.argv[3]):
    module = importlib.import_module(name)
    for value in vars(module).values():
        if isinstance(value, type) and value.__module__ == name and hasattr(value, 'model_json_schema'):
            value.model_json_schema()
from app.schemas.reservation_change_schema import ReservationChangeReceiptRequest
ReservationChangeReceiptRequest.model_validate_json(sys.argv[4]).model_dump_json()
assert not any(n == p or n.startswith(p + '.') for n in sys.modules for p in blocked)
print('guarded imports, JSON schemas and historical parsing passed')
'''
    result = subprocess.run(
        [sys.executable, "-I", "-B", "-c", script, str(BACKEND), json.dumps(FORBIDDEN_IMPORTS),
         json.dumps(SCHEMA_MODULES), json.dumps(confirmation(check_in_date="2020-01-01", check_out_date="2020-01-03"))],
        capture_output=True, text=True, timeout=20, check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "guarded imports, JSON schemas and historical parsing passed"


@pytest.mark.parametrize("field", ["check_in_date", "check_out_date"])
@pytest.mark.parametrize("value", ["2026-02-30", "2026-1-05", "20261005", "2026-10-05T00:00:00Z",
                                  " 2026-10-05", "2026-10-05\n", 1791158400, True, None,
                                  datetime(2026, 10, 5, tzinfo=timezone.utc)])
def test_date_only_inputs_reject_coercion(contracts, field, value):
    for cls in [contracts.ReservationChangeReviewRequest, contracts.ReservationChangeConfirmRequest,
                contracts.ReservationChangeReceiptRequest]:
        body = review() if cls is contracts.ReservationChangeReviewRequest else confirmation()
        with pytest.raises(ValidationError):
            cls.model_validate({**body, field: value})


@pytest.mark.parametrize("body", [confirmation(check_out_date=DATE_IN),
                                  confirmation(check_out_date="2026-10-04")])
def test_stay_order_is_required_even_for_historical_receipts(contracts, body):
    for cls in [contracts.ReservationChangeConfirmRequest, contracts.ReservationChangeReceiptRequest]:
        with pytest.raises(ValidationError):
            cls.model_validate(body)


def test_new_changes_use_existing_today_or_later_calendar(contracts):
    body = confirmation(check_in_date="2026-09-28", check_out_date="2026-09-30")
    with pytest.raises(ValidationError):
        contracts.ReservationChangeConfirmRequest.model_validate(body)
    with pytest.raises(ValidationError):
        contracts.ReservationChangeReviewRequest.model_validate(review(**{k: body[k] for k in ["check_in_date", "check_out_date"]}))
    today = contracts.ReservationChangeConfirmRequest.model_validate(
        confirmation(check_in_date="2026-09-29", check_out_date="2026-09-30"))
    assert today.check_in_date == date(2026, 9, 29)


def test_historical_retry_schema_is_not_authorization_for_a_new_change(contracts):
    historical = confirmation(check_in_date="2020-02-28", check_out_date="2020-02-29")
    parsed = contracts.ReservationChangeReceiptRequest.model_validate_json(json.dumps(historical))
    assert json.loads(parsed.model_dump_json()) == historical
    with pytest.raises(ValidationError):
        contracts.ReservationChangeConfirmRequest.model_validate(parsed.model_dump())
    saved = contracts.ReservationChangeReceiptResponse.model_validate(
        receipt(check_in_date="2020-02-28", check_out_date="2020-02-29"))
    assert json.loads(saved.model_dump_json())["check_out_date"] == "2020-02-29"


@pytest.mark.parametrize("field", ["q", "adults", "children", "check_in_date", "check_out_date"])
def test_quote_review_requires_explicit_context(contracts, field):
    body = review()
    del body[field]
    with pytest.raises(ValidationError):
        contracts.ReservationChangeReviewRequest.model_validate(body)


@pytest.mark.parametrize("changes", [
    {"q": " \t"}, {"q": "a" * 256}, {"q": True}, {"adults": True}, {"adults": "2"},
    {"adults": 2.0}, {"adults": 0}, {"adults": 21}, {"children": False}, {"children": "0"},
    {"children": -1}, {"children": 21}, {"currency": "EUR"}, {"gl": "ca"}, {"hl": "fr"},
    {"property_token": "untrusted"}, {"user_id": 7}, {"price_per_night": 1},
])
def test_quote_review_rejects_unsupported_or_client_selected_identity(contracts, changes):
    with pytest.raises(ValidationError):
        contracts.ReservationChangeReviewRequest.model_validate(review(**changes))


def test_review_serialization_matches_supported_locale(contracts):
    value = contracts.ReservationChangeReviewRequest.model_validate(review(q=" Synthetic destination "))
    assert json.loads(value.model_dump_json()) == {**review(), "currency": "USD", "gl": "us", "hl": "en"}


@pytest.mark.parametrize("field", list(confirmation()))
def test_confirmation_has_exactly_six_required_fields(contracts, field):
    body = confirmation()
    del body[field]
    with pytest.raises(ValidationError):
        contracts.ReservationChangeReceiptRequest.model_validate(body)


@pytest.mark.parametrize("extra", ["user_id", "reservation_id", "currency", "q", "idempotency_key"])
def test_confirmation_rejects_extra_fields(contracts, extra):
    with pytest.raises(ValidationError):
        contracts.ReservationChangeReceiptRequest.model_validate({**confirmation(), extra: "extra"})


@pytest.mark.parametrize("value", [False, 0, 1, "true", "false", None])
def test_confirmation_requires_literal_acceptance(contracts, value):
    with pytest.raises(ValidationError):
        contracts.ReservationChangeReceiptRequest.model_validate(confirmation(accept_quote=value))


@pytest.mark.parametrize("value", ["", " \t\n", "a" * 16385, None, True, 1, b"opaque"])
def test_invalid_quote_identifiers(contracts, value):
    with pytest.raises(ValidationError):
        contracts.ReservationChangeReceiptRequest.model_validate(confirmation(quote_id=value))
    with pytest.raises(ValidationError):
        contracts.ReservationChangeQuoteResponse.model_validate(quote_response(quote_id=value))


@pytest.mark.parametrize("value", [OPAQUE_ID, "opaque", "a" * 16384, "é-opaque\n"])
def test_opaque_identifiers_survive_parsing_and_serialization_unchanged(contracts, value):
    for cls in [contracts.ReservationChangeConfirmRequest, contracts.ReservationChangeReceiptRequest]:
        parsed = cls.model_validate_json(json.dumps(confirmation(quote_id=value)))
        assert parsed.quote_id == value
        assert json.loads(parsed.model_dump_json())["quote_id"] == value
    quoted = contracts.ReservationChangeQuoteResponse.model_validate(quote_response(quote_id=value))
    assert json.loads(quoted.model_dump_json())["quote_id"] == value


@pytest.mark.parametrize("field", ["price_per_night", "accepted_payment_amount"])
@pytest.mark.parametrize("value", [True, False, "100", b"100", None, 0, -1, 100000000,
                                  float("nan"), float("inf"), float("-inf"), Decimal("NaN")])
def test_confirmation_prices_are_positive_finite_numbers(contracts, field, value):
    with pytest.raises(ValidationError):
        contracts.ReservationChangeReceiptRequest.model_validate(confirmation(**{field: value}))


@pytest.mark.parametrize("value", [100, 100.0, Decimal("100.00"), 100 + 1e-12, 99999999.99])
def test_accepted_numbers_are_not_rounded_in_contracts(contracts, value):
    result = contracts.ReservationChangeReceiptRequest.model_validate(confirmation(price_per_night=value))
    assert result.price_per_night == float(value)
    assert json.loads(result.model_dump_json())["price_per_night"] == float(value)


@pytest.mark.parametrize("value", [0, 4294967295])
def test_summary_and_settlement_revision_bounds_are_inclusive(contracts, value):
    assert contracts.AdjustmentSettlementRequest.model_validate(settlement(reservation_revision=value)).reservation_revision == value
    assert contracts.ReservationFinancialSummary.model_validate({**financial_summary(), "reservation_revision": value}).reservation_revision == value


@pytest.mark.parametrize("value", [True, False, "7", 7.0, -1, 4294967296, None])
def test_revision_is_a_strict_unsigned_integer(contracts, value):
    with pytest.raises(ValidationError):
        contracts.AdjustmentSettlementRequest.model_validate(settlement(reservation_revision=value))
    with pytest.raises(ValidationError):
        contracts.ReservationFinancialSummary.model_validate({**financial_summary(), "reservation_revision": value})
    with pytest.raises(ValidationError):
        contracts.ReservationChangeReceiptResponse.model_validate(receipt(revision=value))


@pytest.mark.parametrize("changes", [{"accepted_amount": True}, {"accepted_amount": "40"},
                                   {"accepted_amount": None}, {"accepted_amount": 0},
                                   {"accepted_amount": -1}, {"accepted_amount": 100000000},
                                   {"accepted_amount": float("nan")}, {"accepted_amount": float("inf")},
                                   {"accept_payment": False}, {"accept_payment": 1}, {"accept_payment": "true"},
                                   {"external_payment_id": "not-allowed"}])
def test_settlement_input_fails_closed(contracts, changes):
    with pytest.raises(ValidationError):
        contracts.AdjustmentSettlementRequest.model_validate(settlement(**changes))


@pytest.mark.parametrize("field", list(settlement()))
def test_settlement_fields_are_required(contracts, field):
    body = settlement()
    del body[field]
    with pytest.raises(ValidationError):
        contracts.AdjustmentSettlementRequest.model_validate(body)


@pytest.mark.parametrize("value", [40, 40.0, Decimal("40.00"), 40 + 1e-12, 0.010000000000001])
def test_settlement_retains_precision_and_serializes_a_json_number(contracts, value):
    parsed = contracts.AdjustmentSettlementRequest.model_validate(settlement(accepted_amount=value))
    expected = value if isinstance(value, Decimal) else Decimal(str(value))
    assert parsed.accepted_amount == expected
    body = json.loads(parsed.model_dump_json())
    assert type(body["accepted_amount"]) in (int, float)
    assert body["accepted_amount"] == float(value)
    assert contracts.AdjustmentSettlementRequest.model_validate_json(parsed.model_dump_json()).accepted_amount == expected


@pytest.mark.parametrize("value", ["40", True, 0, -1, Decimal("0.001"), Decimal("100000000"), Decimal("NaN"), Decimal("Infinity")])
def test_ledger_record_requires_exact_positive_database_cents(contracts, value):
    with pytest.raises(ValidationError):
        contracts.ReservationChangeAdjustmentRecord.model_validate(record(amount=value))


@pytest.mark.parametrize("changes", [{"kind": "credit", "status": "paid"}, {"status": "recorded"},
                                   {"reconciles_adjustment_id": 11},
                                   {"entry_role": "cancellation_reconciliation", "status": "recorded"},
                                   {"entry_role": "cancellation_reconciliation", "reconciles_adjustment_id": 11},
                                   {"change_id": True}, {"change_id": 0}])
def test_ledger_category_and_parent_requirements(contracts, changes):
    with pytest.raises(ValidationError):
        contracts.ReservationChangeAdjustmentRecord.model_validate(record(**changes))


def test_internal_credits_and_reconciliations_are_records_not_refunds(contracts):
    credit = contracts.ReservationChangeAdjustmentRecord.model_validate(record(kind="credit", status="recorded"))
    reversal = contracts.ReservationChangeAdjustmentRecord.model_validate(record(
        entry_role="cancellation_reconciliation", reconciles_adjustment_id=11, status="recorded"))
    assert credit.amount == reversal.amount == Decimal("40.00")
    assert json.loads(credit.model_dump_json())["amount"] == "40.00"
    assert "payment_id" not in credit.model_dump() and "reward_points" not in reversal.model_dump()


@pytest.mark.parametrize("field", ["reservation_total", "payment_obligation", "previous_payment_obligation", "payment_difference"])
@pytest.mark.parametrize("value", [1, Decimal("1.00"), "1", "1.0", "1.000", "1e2", "+1.00", " 1.00", "1.00\n", "١.٠٠", "NaN", "Infinity"])
def test_receipt_money_is_an_exact_ascii_cent_string(contracts, field, value):
    with pytest.raises(ValidationError):
        contracts.ReservationChangeReceiptResponse.model_validate(receipt(**{field: value}))


@pytest.mark.parametrize("changes", [{"revision": 0}, {"change_id": True}, {"room_type_id": "31"},
                                   {"booking_payment_id": 0}, {"reservation_id": 9007199254740992},
                                   {"booking_payment_status": "refunded"}, {"external_refund": True},
                                   {"check_out_date": DATE_IN}])
def test_receipt_identity_lifecycle_and_shape(contracts, changes):
    with pytest.raises(ValidationError):
        contracts.ReservationChangeReceiptResponse.model_validate(receipt(**changes))


@pytest.mark.parametrize("adjustment", [{"adjustment_id": 11, "kind": "charge", "amount": "1.00", "status": "recorded"},
                                      {"adjustment_id": 11, "kind": "credit", "amount": "1.00", "status": "pending"},
                                      {"adjustment_id": 11, "kind": "charge", "amount": 1, "status": "pending"},
                                      {"adjustment_id": 11, "kind": "charge", "amount": "1.00", "status": "paid"}])
def test_receipt_adjustment_is_the_historical_confirmation_state(contracts, adjustment):
    with pytest.raises(ValidationError):
        contracts.ReservationChangeReceiptResponse.model_validate(receipt(adjustment=adjustment))


def test_receipt_keeps_negative_difference_and_explicit_null_adjustment(contracts):
    parsed = contracts.ReservationChangeReceiptResponse.model_validate(receipt(
        payment_difference="-10.00", adjustment={"adjustment_id": 12, "kind": "credit", "amount": "10.00", "status": "recorded"}))
    assert json.loads(parsed.model_dump_json())["payment_difference"] == "-10.00"
    assert json.loads(contracts.ReservationChangeReceiptResponse.model_validate(receipt(adjustment=None)).model_dump_json())["adjustment"] is None
    missing = receipt()
    del missing["adjustment"]
    with pytest.raises(ValidationError):
        contracts.ReservationChangeReceiptResponse.model_validate(missing)


@pytest.mark.parametrize("value", [None, "2026-09-29T12:00:00", "2026-02-30T12:00:00Z", datetime(2026, 9, 29, 12)])
def test_quote_and_paid_settlement_require_aware_timestamps(contracts, value):
    with pytest.raises(ValidationError):
        contracts.ReservationChangeQuoteResponse.model_validate(quote_response(expires_at=value))
    with pytest.raises(ValidationError):
        contracts.AdjustmentSettlementResponse.model_validate(detail(settled_at=value))


@pytest.mark.parametrize("value", [STAMP, "2026-09-29T05:00:00-07:00", datetime(2026, 9, 29, 12, tzinfo=timezone.utc)])
def test_aware_timestamps_serialize_with_offsets(contracts, value):
    parsed = contracts.AdjustmentSettlementResponse.model_validate(detail(settled_at=value))
    stamp = json.loads(parsed.model_dump_json())["settled_at"]
    assert datetime.fromisoformat(stamp).utcoffset() is not None


@pytest.mark.parametrize("field,value", [("provider_base_total", float("nan")), ("likehome_payment_amount", float("inf")),
                                        ("current_price_per_night", 0), ("provider_total_with_taxes_fees", -1),
                                        ("currency", "EUR"), ("guest_capacity", 2), ("number_of_nights", 3),
                                        ("source", " "), ("property_token", ""), ("price_changed", "not-bool")])
def test_nested_quote_fields_are_compatible(contracts, field, value):
    body = quote_response()
    body["quote"][field] = value
    with pytest.raises(ValidationError):
        contracts.ReservationChangeQuoteResponse.model_validate(body)


@pytest.mark.parametrize("changes", [{"status": "pending", "settled_at": STAMP}, {"status": "paid", "settled_at": None},
                                   {"kind": "credit", "status": "paid"}, {"status": "recorded"},
                                   {"amount": True}, {"amount": "40"}, {"amount": float("nan")},
                                   {"adjustment_id": True}, {"change_id": "51"}, {"reservation_id": 0},
                                   {"reconciles_adjustment_id": 12}, {"currency": "EUR"},
                                   {"entry_role": "cancellation_reconciliation", "reconciles_adjustment_id": 11,
                                    "status": "recorded", "settled_at": None}])
def test_adjustment_detail_lifecycle_and_identity(contracts, changes):
    with pytest.raises(ValidationError):
        contracts.AdjustmentDetailResponse.model_validate(detail(**changes))


@pytest.mark.parametrize("changes", [{"status": "failed"}, {"kind": "credit"},
                                   {"entry_role": "cancellation_reconciliation"}, {"settled_at": None}])
def test_settlement_response_describes_only_a_paid_primary_charge(contracts, changes):
    with pytest.raises(ValidationError):
        contracts.AdjustmentSettlementResponse.model_validate(detail(**changes))


@pytest.mark.parametrize("field", ["current_reservation_total", "current_booking_obligation", "paid_additional_charges",
                                  "pending_additional_charges", "failed_additional_charges", "recorded_internal_credits",
                                  "outstanding_additional_amount", "voided_additional_charges", "reconciliation_credits",
                                  "reconciliation_debits", "outstanding_cancellation_amount", "outstanding_booking_amount"])
@pytest.mark.parametrize("value", [True, "1", -1, float("nan"), float("inf"), None])
def test_summary_money_remains_finite_numeric_not_string_or_null(contracts, field, value):
    with pytest.raises(ValidationError):
        contracts.ReservationFinancialSummary.model_validate({**financial_summary(), field: value})


@pytest.mark.parametrize("case", ["wrong-payment-owner", "wrong-payment-kind", "nonfinite-payment", "coercible-payment",
                                 "wrong-adjustment-owner", "wrong-bucket", "duplicate-id", "missing-change",
                                 "cancellation-on-active", "missing-cancellation", "same-payment-id",
                                 "missing-parent", "wrong-parent-amount", "wrong-parent-kind", "duplicate-reconciliation"])
def test_summary_references_match_frontend_validation(contracts, case):
    body = cancelled_summary() if case in {"missing-cancellation", "same-payment-id", "missing-parent",
                                          "wrong-parent-amount", "wrong-parent-kind", "duplicate-reconciliation"} else financial_summary()
    if case == "wrong-payment-owner": body["original_booking_payment"]["reservation_id"] = 42
    elif case == "wrong-payment-kind": body["original_booking_payment"]["payment_type"] = "cancellation"
    elif case == "nonfinite-payment": body["original_booking_payment"]["amount"] = float("inf")
    elif case == "coercible-payment": body["original_booking_payment"]["payment_id"] = True
    elif case == "wrong-adjustment-owner": body["adjustments"][0]["reservation_id"] = 42
    elif case == "wrong-bucket": body["adjustments"][0].update(entry_role="cancellation_reconciliation", reconciles_adjustment_id=12, status="recorded", settled_at=None)
    elif case == "duplicate-id": body["adjustments"][1]["adjustment_id"] = 11
    elif case == "missing-change": body["latest_change_id"] = None
    elif case == "cancellation-on-active": body["cancellation_payment"] = cancelled_summary()["cancellation_payment"]
    elif case == "missing-cancellation": body["cancellation_payment"] = None
    elif case == "same-payment-id": body["cancellation_payment"]["payment_id"] = 61
    elif case == "missing-parent": body["cancellation_reconciliations"][0]["reconciles_adjustment_id"] = 999
    elif case == "wrong-parent-amount": body["cancellation_reconciliations"][0]["amount"] = 41
    elif case == "wrong-parent-kind": body["cancellation_reconciliations"][0]["kind"] = "charge"
    elif case == "duplicate-reconciliation": body["cancellation_reconciliations"].append({**body["cancellation_reconciliations"][0], "adjustment_id": 18})
    with pytest.raises(ValidationError):
        contracts.ReservationFinancialSummary.model_validate(body)


def test_nullable_financial_fields_and_recovered_defaults_are_explicit_in_json(contracts):
    body = financial_summary()
    body.update(latest_change_id=None, adjustments=[])
    for key in ["voided_additional_charges", "cancellation_reconciliations", "reconciliation_credits",
                "reconciliation_debits", "cancellation_payment", "outstanding_cancellation_amount", "outstanding_booking_amount"]:
        del body[key]
    wire = json.loads(contracts.ReservationFinancialSummary.model_validate(body).model_dump_json())
    assert wire["latest_change_id"] is None and wire["cancellation_payment"] is None
    assert wire["cancellation_reconciliations"] == []
    assert wire["reconciliation_credits"] == wire["outstanding_cancellation_amount"] == 0
    assert "settled_at" in detail(settled_at=None)


FRONTEND_VALIDATORS = r'''
const fs = require('node:fs'), vm = require('node:vm');
const root = process.argv[1];
const ts = require(root + '/node_modules/typescript/lib/typescript.js');
const source = fs.readFileSync(root + '/lib/bookings.ts', 'utf8');
const tree = ts.createSourceFile('bookings.ts', source, ts.ScriptTarget.Latest, true);
// Evaluate only pure declarations. No API, token storage, fetch or router imports.
const functions = tree.statements.filter(node => ts.isFunctionDeclaration(node) &&
  !node.modifiers?.some(modifier => modifier.kind === ts.SyntaxKind.AsyncKeyword));
const validators = functions.map(node => node.getText(tree)).join('\n');
const search = fs.readFileSync(root + '/lib/search-validation.mjs', 'utf8');
const now = Date.parse('2026-09-29T12:00:00Z');
class FixedDate extends Date {
  constructor(...args) { super(...(args.length ? args : [now])); }
  static now() { return now; }
}
const context = vm.createContext({ exports: {}, Date: FixedDate });
vm.runInContext(ts.transpileModule(search + '\n' + validators, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 }
}).outputText, context, {timeout: 1000});
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
let accepted;
if (input.kind === 'summary') accepted = context.isReservationFinancialSummary(input.response, 41);
if (input.kind === 'quote') accepted = context.isReservationChangeQuote(input.response, 41,
  context.normalizeReservationChangeReview(input.request));
if (input.kind === 'confirmation') {
  const parsed = context.reservationChangeConfirmation(input.request);
  accepted = JSON.stringify(parsed) === JSON.stringify(input.request) &&
    context.isReservationChangeReceipt(input.response, 41, parsed);
}
if (input.kind === 'settlement') {
  const parsed = context.adjustmentSettlementRequest(input.request);
  accepted = JSON.stringify(parsed) === JSON.stringify(input.request) &&
    context.isAdjustmentSettlement(input.response, 41, 11, parsed.accepted_amount);
}
if (accepted !== true) throw new Error('Serialized contract rejected by existing frontend validator');
process.stdout.write('compatible');
'''


@pytest.mark.parametrize("kind", ["summary", "cancelled-summary", "quote", "confirmation", "historical-confirmation", "settlement"])
def test_serialized_json_passes_unchanged_frontend_validators(contracts, kind):
    if kind in {"summary", "cancelled-summary"}:
        value = financial_summary() if kind == "summary" else cancelled_summary()
        response = contracts.ReservationFinancialSummary.model_validate(value)
        body = {"kind": "summary"}
    elif kind == "quote":
        response = contracts.ReservationChangeQuoteResponse.model_validate(quote_response())
        body = {"kind": kind, "request": json.loads(contracts.ReservationChangeReviewRequest.model_validate(review()).model_dump_json())}
    elif kind in {"confirmation", "historical-confirmation"}:
        changes = {"check_in_date": "2020-01-01", "check_out_date": "2020-01-03"} if kind.startswith("historical") else {}
        response = contracts.ReservationChangeReceiptResponse.model_validate(receipt(**changes))
        body = {"kind": "confirmation", "request": json.loads(contracts.ReservationChangeReceiptRequest.model_validate(confirmation(**changes)).model_dump_json())}
    else:
        response = contracts.AdjustmentSettlementResponse.model_validate(detail())
        body = {"kind": kind, "request": json.loads(contracts.AdjustmentSettlementRequest.model_validate(settlement(accepted_amount=40 + 1e-12)).model_dump_json())}
    body["response"] = json.loads(response.model_dump_json())
    assert body["response"] == response.model_dump(mode="json")
    node = shutil.which("node")
    assert node is not None, "Existing frontend Node environment is required for compatibility verification"
    result = subprocess.run([node, "-e", FRONTEND_VALIDATORS, str(FRONTEND)], input=json.dumps(body),
                            capture_output=True, text=True, timeout=20, check=False,
                            env=os.environ.copy())
    assert result.returncode == 0, result.stderr
    assert result.stdout == "compatible"
