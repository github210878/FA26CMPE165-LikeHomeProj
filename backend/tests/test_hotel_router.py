"""
Tests for GET /hotels/search — task 3.1.5.

These exercise FastAPI's request validation (422s) and confirm the endpoint
returns the shape defined by HotelSearchResponse. The service call itself is
mocked so no real SerpApi call is made and no DB connection is required.
"""

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.schemas.hotel_schema import HotelSearchResponse
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
