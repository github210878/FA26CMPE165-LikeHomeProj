"""HTTP contract tests spanning frontend payloads, FastAPI, SerpApi, and SQL writes."""

import json
from copy import deepcopy
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.config.database import Base, get_db
from app.models.payment import Payment
from app.models.reservation import Reservation
from app.models.user import User
from app.routers.booking_router import router as booking_router
from app.routers.hotel_router import router as hotel_router
from app.services import hotel_service
from app.utilities.auth import get_current_user_id


FIXTURE = json.loads(
    (Path(__file__).parents[2] / "contract-fixtures" / "search-to-booking.json")
    .read_text()
)


def provider_property():
    return {
        "name": "Hotel A",
        "property_token": "property-123",
        "rate_per_night": {"extracted_lowest": 150},
        "overall_rating": 4.5,
    }


def provider_details(nightly=165, property_token="property-123"):
    return {
        "name": "Hotel A",
        "property_token": property_token,
        "prices": [
            {
                "source": "Provider A",
                "num_guests": 3,
                "rate_per_night": {"extracted_before_taxes_fees": nightly},
                "total_rate": {
                    "extracted_before_taxes_fees": nightly * 2,
                    "extracted_lowest": nightly * 2 + 20,
                },
            }
        ],
    }


@pytest.fixture
def contract_app(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(User(user_id=7, email="test7@example.com", password_hash="test"))
        db.commit()

    test_app = FastAPI()
    test_app.include_router(hotel_router)
    test_app.include_router(booking_router)

    def override_db():
        with Session(engine) as db:
            yield db

    test_app.dependency_overrides[get_db] = override_db
    test_app.dependency_overrides[get_current_user_id] = lambda: 7
    monkeypatch.setattr(hotel_service, "_cache_hotels", lambda **_: None)

    with TestClient(test_app) as client:
        yield client, engine
    engine.dispose()


def test_frontend_contract_reaches_fastapi_and_commits_one_booking(
    contract_app, monkeypatch
):
    client, engine = contract_app
    calls = []

    def fake_provider(params):
        calls.append(params)
        return {"properties": [provider_property()]} if "property_token" not in params else provider_details()

    monkeypatch.setattr(hotel_service.serpapi_client, "search_google_hotels", fake_provider)

    search_response = client.get("/hotels/search", params=FIXTURE["selection"])
    assert search_response.status_code == 200
    assert search_response.json()["properties"][0]["property_token"] == FIXTURE["selection"]["property_token"]

    quote_response = client.post("/hotels/revalidate", json=FIXTURE["selection"])
    assert quote_response.status_code == 200
    assert quote_response.json() == FIXTURE["quote"]

    booking_response = client.post(
        "/bookings/create",
        json=FIXTURE["booking_request"],
        headers={"Authorization": "Bearer test-user-token"},
    )
    assert booking_response.status_code == 200
    assert booking_response.json() == FIXTURE["booking_response"]

    assert calls == [
        {
            "q": "San Jose hotels",
            "check_in_date": "2026-11-01",
            "check_out_date": "2026-11-03",
            "adults": 3,
            "children": 0,
            "currency": "USD",
            "gl": "us",
            "hl": "en",
        },
        {
            "q": "San Jose hotels",
            "property_token": "property-123",
            "check_in_date": "2026-11-01",
            "check_out_date": "2026-11-03",
            "adults": 3,
            "children": 0,
            "currency": "USD",
            "gl": "us",
            "hl": "en",
        },
        {
            "q": "San Jose hotels",
            "property_token": "property-123",
            "check_in_date": "2026-11-01",
            "check_out_date": "2026-11-03",
            "adults": 3,
            "children": 0,
            "currency": "USD",
            "gl": "us",
            "hl": "en",
        },
    ]

    with Session(engine) as db:
        reservations = db.scalars(select(Reservation)).all()
        payments = db.scalars(select(Payment)).all()
        assert len(reservations) == 1
        assert len(payments) == 1
        assert reservations[0].user_id == 7
        assert reservations[0].guest_email == "person@example.com"
        assert payments[0].amount == pytest.approx(374.22)
        assert payments[0].payment_status == "pending"


@pytest.mark.parametrize(
    "change",
    [
        lambda body: body.pop("property_token"),
        lambda body: body.update(property_token="legacy:1"),
        lambda body: body.update(currency="EUR"),
        lambda body: body.update(check_out_date="2026-11-01"),
        lambda body: body.update(adults=True),
        lambda body: body.update(displayed_price_per_night="NaN"),
        lambda body: body.update(unexpected="field"),
    ],
)
def test_invalid_frontend_contract_is_rejected_before_provider_call(
    contract_app, monkeypatch, change
):
    client, _ = contract_app
    calls = []
    monkeypatch.setattr(
        hotel_service.serpapi_client,
        "search_google_hotels",
        lambda params: calls.append(params),
    )
    body = deepcopy(FIXTURE["selection"])
    change(body)

    response = client.post("/hotels/revalidate", json=body)

    assert response.status_code == 422
    assert calls == []


@pytest.mark.parametrize(
    "failure, expected_status",
    [("mismatch", 409), ("empty", 409), ("timeout", 504), ("provider", 502)],
)
def test_provider_failures_are_safe_at_http_boundary(
    contract_app, monkeypatch, failure, expected_status
):
    client, _ = contract_app

    def fake_provider(_):
        if failure == "mismatch":
            return provider_details(property_token="other-property")
        if failure == "empty":
            return {"property_token": "property-123", "name": "Hotel A", "prices": []}
        if failure == "timeout":
            from app.utilities.serpapi_client import SerpApiTimeoutError
            raise SerpApiTimeoutError("private timeout")
        from app.utilities.serpapi_client import SerpApiResponseError
        raise SerpApiResponseError("private provider failure")

    monkeypatch.setattr(hotel_service.serpapi_client, "search_google_hotels", fake_provider)
    response = client.post("/hotels/revalidate", json=FIXTURE["selection"])

    assert response.status_code == expected_status
    assert "private" not in response.text


def test_stale_frontend_quote_returns_conflict_without_database_writes(
    contract_app, monkeypatch
):
    client, engine = contract_app
    monkeypatch.setattr(
        hotel_service.serpapi_client,
        "search_google_hotels",
        lambda _: provider_details(nightly=170),
    )

    response = client.post(
        "/bookings/create",
        json=FIXTURE["booking_request"],
        headers={"Authorization": "Bearer test-user-token"},
    )

    assert response.status_code == 409
    with Session(engine) as db:
        assert db.scalars(select(Reservation)).all() == []
        assert db.scalars(select(Payment)).all() == []


def test_booking_route_requires_authentication_without_bypassing_contract_validation():
    test_app = FastAPI()
    test_app.include_router(booking_router)
    client = TestClient(test_app)

    response = client.post("/bookings/create", json=FIXTURE["booking_request"])

    assert response.status_code == 401
