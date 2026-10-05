"""Property-only rate quotes; provider responses are always mocked."""

from datetime import date
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.routers.hotel_router import router
from app.schemas.hotel_schema import HotelRevalidationRequest
from app.services import hotel_service
from app.utilities import serpapi_client
from app.utilities.serpapi_client import SerpApiTimeoutError, SerpApiResponseError


def stay(**overrides):
    values = dict(
        property_token="property-A", q="San Jose hotels",
        check_in_date=date(2026, 11, 1), check_out_date=date(2026, 11, 3),
        adults=2, children=0, currency="USD", gl="us", hl="en",
    )
    values.update(overrides)
    return HotelRevalidationRequest(**values)


def offer(*, source="Provider A", capacity=2, nightly=100, total=200, all_in=230):
    return {
        "source": source, "num_guests": capacity,
        "rate_per_night": {"extracted_before_taxes_fees": nightly},
        "total_rate": {
            "extracted_before_taxes_fees": total,
            "extracted_lowest": all_in,
        },
    }


def details(*offers):
    return {"property_token": "property-A", "name": "Hotel A", "prices": list(offers)}


def test_exact_stay_is_sent_and_lowest_eligible_offer_is_normalized(monkeypatch):
    captured = {}
    def fake_provider(params):
        captured.update(params)
        return details(
            offer(source="Too small", capacity=1, nightly=50, total=100, all_in=120),
            offer(source="Higher", nightly=110, total=220, all_in=250),
            offer(),
        )
    monkeypatch.setattr(serpapi_client, "search_google_hotels", fake_provider)
    result = hotel_service.revalidate_hotel(stay(displayed_price_per_night=115))
    assert captured == {
        "q": "San Jose hotels", "property_token": "property-A",
        "check_in_date": "2026-11-01", "check_out_date": "2026-11-03",
        "adults": 2, "children": 0, "currency": "USD", "gl": "us", "hl": "en",
    }
    assert "api_key" not in captured
    assert result.source == "Provider A"
    assert result.number_of_nights == 2
    assert result.current_price_per_night == 100
    assert result.provider_base_total == 200
    assert result.provider_total_with_taxes_fees == 230
    assert result.likehome_reservation_total == 210
    assert result.likehome_payment_amount == 226.80
    assert result.price_changed is False
    assert "prices" not in result.model_dump()


def test_search_display_price_change_is_flagged_but_does_not_set_quote(monkeypatch):
    monkeypatch.setattr(serpapi_client, "search_google_hotels", lambda _: details(offer(nightly=165, total=330, all_in=350)))
    result = hotel_service.revalidate_hotel(stay(displayed_price_per_night=150))
    assert result.price_changed is True
    assert result.current_price_per_night == 165
    assert result.provider_base_total == 330


def test_provider_stay_total_is_not_multiplied_by_nights(monkeypatch):
    monkeypatch.setattr(serpapi_client, "search_google_hotels", lambda _: details(offer(nightly=100, total=201, all_in=231)))
    result = hotel_service.revalidate_hotel(stay())
    assert result.current_price_per_night == 100.50
    assert result.provider_base_total == 201
    assert result.likehome_reservation_total == 211.05
    assert result.likehome_payment_amount == 227.93


@pytest.mark.parametrize("payload", [
    {},
    {"property_token": "different", "name": "Other", "prices": [offer()]},
    {"property_token": "property-A", "name": "Hotel A", "prices": []},
    details({"source": "Missing rate", "num_guests": 2}),
    details(offer(capacity=1)),
    details(offer(nightly="bad")),
    details(offer(nightly=None)),
    details(offer(total=900)),
])
def test_unverifiable_or_unavailable_property_fails_closed(monkeypatch, payload):
    monkeypatch.setattr(serpapi_client, "search_google_hotels", lambda _: payload)
    with pytest.raises(HTTPException) as error:
        hotel_service.revalidate_hotel(stay())
    assert error.value.status_code == 409


@pytest.mark.parametrize("failure,code", [
    (SerpApiTimeoutError("private timeout detail"), 504),
    (SerpApiResponseError("private provider detail"), 502),
])
def test_provider_failure_is_safe(monkeypatch, failure, code):
    def fail(_):
        raise failure
    monkeypatch.setattr(serpapi_client, "search_google_hotels", fail)
    with pytest.raises(HTTPException) as error:
        hotel_service.revalidate_hotel(stay())
    assert error.value.status_code == code
    assert "private" not in error.value.detail


def test_http_contract_rejects_non_usd_and_extra_price_fields(monkeypatch):
    monkeypatch.setattr(serpapi_client, "search_google_hotels", lambda _: details(offer()))
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    body = stay().model_dump(mode="json")
    response = client.post("/hotels/revalidate", json=body)
    assert response.status_code == 200
    assert response.json()["availability"] == "available"
    assert client.post("/hotels/revalidate", json={**body, "currency": "EUR"}).status_code == 422
    assert client.post("/hotels/revalidate", json={**body, "price_per_night": 1}).status_code == 422


def test_serpapi_client_keeps_api_key_server_side(monkeypatch):
    observed = {}
    monkeypatch.setattr(serpapi_client.Config, "API_KEY", "test-server-key")
    monkeypatch.setattr(serpapi_client.Config, "EXTERNAL_API_URL", None)
    def fake_get(url, params, timeout):
        observed.update(url=url, params=params, timeout=timeout)
        return SimpleNamespace(status_code=200, json=lambda: details(offer()))
    monkeypatch.setattr(serpapi_client.requests, "get", fake_get)
    serpapi_client.search_google_hotels({"property_token": "property-A"})
    assert observed["params"]["api_key"] == "test-server-key"
    assert observed["params"]["property_token"] == "property-A"
    assert observed["params"]["engine"] == "google_hotels"
