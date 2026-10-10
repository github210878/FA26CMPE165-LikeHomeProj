"""HTTP contract tests for property details fetched by SerpApi token."""

from datetime import date

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers.hotel_router import router
from app.services import hotel_service
from app.utilities.serpapi_client import (
    SerpApiConfigError,
    SerpApiResponseError,
    SerpApiTimeoutError,
)


VALID_PARAMS = {
    "property_token": "property-A",
    "q": "San Jose hotels",
    "check_in_date": "2026-11-01",
    "check_out_date": "2026-11-03",
    "adults": 2,
    "children": 1,
    "currency": "USD",
    "gl": "us",
    "hl": "en",
}


def property_data():
    return {
        "name": "Hotel A",
        "property_token": "property-A",
        "hotel_class": "4-star hotel",
        "overall_rating": 4.6,
        "reviews": 1250,
        "amenities": ["Free Wi-Fi", "Pool", "Free Wi-Fi", ""],
        "images": [
            {"original": "https://example.test/hotel.jpg"},
            {"thumbnail": "https://example.test/thumb.jpg"},
        ],
        "link": "https://example.test/hotel",
        "gps_coordinates": {"latitude": 37.3, "longitude": -121.9},
        "description": "A verified hotel.",
        "address": "1 Main Street",
        "phone": "+1 555 0100",
        "check_in_time": "3:00 PM",
        "check_out_time": "11:00 AM",
        "rate_per_night": {"lowest": "$100", "extracted_lowest": 100},
        "total_rate": {"lowest": "$200", "extracted_lowest": 200},
    }


@pytest.fixture
def client():
    test_app = FastAPI()
    test_app.include_router(router)
    return TestClient(test_app)


def test_details_forwards_exact_stay_and_normalizes_top_level_property(client, monkeypatch):
    captured = {}

    def fake_provider(params):
        captured.update(params)
        return property_data()

    monkeypatch.setattr(hotel_service.serpapi_client, "search_google_hotels", fake_provider)

    response = client.get("/hotels/details", params=VALID_PARAMS)

    assert response.status_code == 200
    assert captured == VALID_PARAMS
    assert response.json() == {
        "property_token": "property-A",
        "name": "Hotel A",
        "hotel_class": "4-star hotel",
        "overall_rating": 4.6,
        "reviews": 1250,
        "amenities": ["Free Wi-Fi", "Pool", "Free Wi-Fi"],
        "images": ["https://example.test/hotel.jpg", "https://example.test/thumb.jpg"],
        "thumbnail": "https://example.test/thumb.jpg",
        "link": "https://example.test/hotel",
        "gps_coordinates": {"latitude": 37.3, "longitude": -121.9},
        "description": "A verified hotel.",
        "address": "1 Main Street",
        "phone": "+1 555 0100",
        "check_in_time": "3:00 PM",
        "check_out_time": "11:00 AM",
        "rate_per_night": {"lowest": "$100", "extracted_lowest": 100, "before_taxes_fees": None, "extracted_before_taxes_fees": None},
        "total_rate": {"lowest": "$200", "extracted_lowest": 200, "before_taxes_fees": None, "extracted_before_taxes_fees": None},
    }


def test_details_accepts_matching_property_inside_properties_envelope(client, monkeypatch):
    monkeypatch.setattr(
        hotel_service.serpapi_client,
        "search_google_hotels",
        lambda _: {"properties": [{"property_token": "other"}, property_data()]},
    )

    response = client.get("/hotels/details", params=VALID_PARAMS)

    assert response.status_code == 200
    assert response.json()["property_token"] == "property-A"
    assert response.json()["name"] == "Hotel A"


@pytest.mark.parametrize(
    "change",
    [
        lambda params: params.pop("property_token"),
        lambda params: params.update(property_token="legacy:1"),
        lambda params: params.update(property_token="partner:1"),
        lambda params: params.update(check_out_date="2026-11-01"),
        lambda params: params.update(adults=True),
        lambda params: params.update(currency="EUR"),
        lambda params: params.update(unexpected="value"),
    ],
)
def test_invalid_details_contract_is_rejected_without_provider_call(client, monkeypatch, change):
    calls = []
    monkeypatch.setattr(
        hotel_service.serpapi_client,
        "search_google_hotels",
        lambda params: calls.append(params),
    )
    params = dict(VALID_PARAMS)
    change(params)

    response = client.get("/hotels/details", params=params)

    assert response.status_code == 422
    assert calls == []


@pytest.mark.parametrize(
    "provider_response, expected_status",
    [
        ({"property_token": "other", "name": "Other"}, 404),
        ({"properties": []}, 404),
        ({"property_token": "property-A"}, 502),
        (None, 404),
    ],
)
def test_unverifiable_provider_property_fails_safely(
    client, monkeypatch, provider_response, expected_status
):
    monkeypatch.setattr(
        hotel_service.serpapi_client,
        "search_google_hotels",
        lambda _: provider_response,
    )

    response = client.get("/hotels/details", params=VALID_PARAMS)

    assert response.status_code == expected_status
    assert "api_key" not in response.text


@pytest.mark.parametrize(
    "error, expected_status",
    [
        (SerpApiConfigError("private config"), 500),
        (SerpApiTimeoutError("private timeout"), 504),
        (SerpApiResponseError("private provider"), 502),
    ],
)
def test_provider_errors_are_translated_without_private_details(
    client, monkeypatch, error, expected_status
):
    def fail(_):
        raise error

    monkeypatch.setattr(hotel_service.serpapi_client, "search_google_hotels", fail)

    response = client.get("/hotels/details", params=VALID_PARAMS)

    assert response.status_code == expected_status
    assert "private" not in response.text


def test_details_never_returns_provider_only_fields(client, monkeypatch):
    raw = property_data() | {
        "api_key": "secret",
        "prices": [{"source": "Provider A", "private": "secret"}],
    }
    monkeypatch.setattr(hotel_service.serpapi_client, "search_google_hotels", lambda _: raw)

    response = client.get("/hotels/details", params=VALID_PARAMS)

    assert response.status_code == 200
    assert "api_key" not in response.json()
    assert "prices" not in response.json()
