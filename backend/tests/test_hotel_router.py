"""
Tests for GET /hotels/search — task 3.1.5.

These exercise FastAPI's request validation (422s) and confirm the endpoint
returns the shape defined by HotelSearchResponse. The service call itself is
mocked so no real SerpApi call is made and no DB connection is required.
"""

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.main import app
from app.schemas.hotel_schema import HotelSearchResponse, HotelSearchResult
from app.services import hotel_service

client = TestClient(app)

VALID_PARAMS = {
    "q": "San Jose hotels",
    "check_in_date": "2026-10-05",
    "check_out_date": "2026-10-08",
}


@pytest.fixture(autouse=True)
def mock_search(monkeypatch):
    """By default, short-circuit the SerpApi call with a canned empty response."""

    def fake_search_hotels(search_info):
        return HotelSearchResponse(
            search_query=search_info.q,
            check_in_date=search_info.check_in_date,
            check_out_date=search_info.check_out_date,
            result_count=0,
            properties=[],
        )

    monkeypatch.setattr(hotel_service, "search_hotels", fake_search_hotels)


@pytest.mark.parametrize("missing_field", ["q", "check_in_date", "check_out_date"])
def test_missing_required_param_returns_422(missing_field):
    params = {k: v for k, v in VALID_PARAMS.items() if k != missing_field}

    response = client.get("/hotels/search", params=params)

    assert response.status_code == 422
    error_fields = [err["loc"][-1] for err in response.json()["detail"]]
    assert missing_field in error_fields


def test_invalid_adults_type_returns_422():
    response = client.get("/hotels/search", params={**VALID_PARAMS, "adults": "not-a-number"})
    assert response.status_code == 422


@pytest.mark.parametrize("adults", [0, 21])
def test_adults_out_of_bounds_returns_422(adults):
    response = client.get("/hotels/search", params={**VALID_PARAMS, "adults": adults})
    assert response.status_code == 422


@pytest.mark.parametrize("adults", [1, 20])
def test_adults_at_bounds_is_accepted(adults):
    response = client.get("/hotels/search", params={**VALID_PARAMS, "adults": adults})
    assert response.status_code == 200


def test_defaults_are_applied_when_optional_params_omitted(monkeypatch):
    captured = {}

    def fake_search_hotels(search_info):
        captured["search_info"] = search_info
        return HotelSearchResponse(
            search_query=search_info.q,
            check_in_date=search_info.check_in_date,
            check_out_date=search_info.check_out_date,
            result_count=0,
            properties=[],
        )

    monkeypatch.setattr(hotel_service, "search_hotels", fake_search_hotels)

    response = client.get("/hotels/search", params=VALID_PARAMS)

    assert response.status_code == 200
    info = captured["search_info"]
    assert info.adults == 2
    assert info.children == 0
    assert info.currency == "USD"
    assert info.gl == "us"
    assert info.hl == "en"


def test_successful_response_matches_schema_shape():
    response = client.get("/hotels/search", params=VALID_PARAMS)

    assert response.status_code == 200
    body = response.json()
    assert set(body.keys()) == {
        "search_query",
        "check_in_date",
        "check_out_date",
        "result_count",
        "properties",
    }


def test_search_forwards_browser_query_and_returns_normalized_property(monkeypatch):
    captured = {}

    def fake_search(search_info):
        captured["request"] = search_info
        return HotelSearchResponse(
            search_query=search_info.q,
            check_in_date=search_info.check_in_date,
            check_out_date=search_info.check_out_date,
            result_count=1,
            properties=[HotelSearchResult(
                name="Test Hotel",
                property_token="property-123",
                price_per_night=125.0,
                rating=4.5,
                amenities=["Pool"],
            )],
        )

    monkeypatch.setattr(hotel_service, "search_hotels", fake_search)
    response = client.get(
        "/hotels/search",
        params={**VALID_PARAMS, "adults": 3},
        headers={"Origin": "http://localhost:3000"},
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"
    assert captured["request"].q == VALID_PARAMS["q"]
    assert captured["request"].check_in_date == VALID_PARAMS["check_in_date"]
    assert captured["request"].check_out_date == VALID_PARAMS["check_out_date"]
    assert captured["request"].adults == 3
    body = response.json()
    assert body["result_count"] == 1
    assert body["properties"][0]["name"] == "Test Hotel"
    assert body["properties"][0]["price_per_night"] == 125.0
    assert body["properties"][0]["rating"] == 4.5
    assert body["properties"][0]["amenities"] == ["Pool"]


def test_provider_error_reaches_browser_as_502(monkeypatch):
    def fake_search(_search_info):
        raise HTTPException(status_code=502, detail="Upstream unavailable")

    monkeypatch.setattr(hotel_service, "search_hotels", fake_search)
    response = client.get("/hotels/search", params=VALID_PARAMS)

    assert response.status_code == 502
