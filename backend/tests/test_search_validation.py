from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.main import app
from app.schemas.hotel_schema import HotelSearchRequest
from app.utilities import serpapi_client

client = TestClient(app)
VALID_PARAMS = {
    "q": "San Jose hotels",
    "check_in_date": "2026-10-02",
    "check_out_date": "2026-10-05",
}


@pytest.fixture
def upstream_search(monkeypatch):
    search = Mock(return_value={"properties": []})
    monkeypatch.setattr(serpapi_client, "search_google_hotels", search)
    return search


@pytest.mark.parametrize("field", ["check_in_date", "check_out_date"])
@pytest.mark.parametrize(
    "value", ["", "2026-2-01", "2026-13-01", "2026-04-31", "2027-02-29", "2026-10-02T12:00:00"]
)
def test_invalid_calendar_dates_are_rejected_before_serpapi(field, value, upstream_search):
    response = client.get("/hotels/search", params={**VALID_PARAMS, field: value})

    assert response.status_code == 422
    assert ["query", field] in [error["loc"] for error in response.json()["detail"]]
    upstream_search.assert_not_called()


@pytest.mark.parametrize("query", ["", " ", "\t\n"])
def test_blank_destination_is_rejected_before_serpapi(query, upstream_search):
    response = client.get("/hotels/search", params={**VALID_PARAMS, "q": query})

    assert response.status_code == 422
    assert ["query", "q"] in [error["loc"] for error in response.json()["detail"]]
    upstream_search.assert_not_called()


def test_destination_is_trimmed_before_serpapi(upstream_search):
    response = client.get(
        "/hotels/search",
        params={**VALID_PARAMS, "q": "  San Jose hotels  "},
    )

    assert response.status_code == 200
    assert upstream_search.call_args.args[0]["q"] == "San Jose hotels"


def test_destination_over_maximum_length_is_rejected_before_serpapi(upstream_search):
    response = client.get(
        "/hotels/search",
        params={**VALID_PARAMS, "q": "a" * 256},
    )

    assert response.status_code == 422
    assert ["query", "q"] in [error["loc"] for error in response.json()["detail"]]
    upstream_search.assert_not_called()


@pytest.mark.parametrize(
    ("overrides", "field", "message"),
    [
        ({"check_in_date": "2026-09-28"}, "check_in_date", "cannot be in the past"),
        ({"check_out_date": "2026-10-02"}, "check_out_date", "must be after check-in"),
        ({"check_out_date": "2026-10-01"}, "check_out_date", "must be after check-in"),
    ],
)
def test_invalid_date_ranges_return_clear_errors(overrides, field, message, upstream_search):
    response = client.get("/hotels/search", params={**VALID_PARAMS, **overrides})

    assert response.status_code == 422
    assert any(
        error["loc"] == ["query", field] and message in error["msg"]
        for error in response.json()["detail"]
    )
    upstream_search.assert_not_called()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("adults", ""), ("adults", "0"), ("adults", "-1"), ("adults", "21"),
        ("adults", "1.5"), ("adults", "1e1"), ("adults", "abc"),
        ("children", ""), ("children", "-1"), ("children", "21"),
        ("children", "1.5"), ("children", "abc"),
    ],
)
def test_invalid_guest_counts_do_not_reach_serpapi(field, value, upstream_search):
    response = client.get("/hotels/search", params={**VALID_PARAMS, field: value})

    assert response.status_code == 422
    assert ["query", field] in [error["loc"] for error in response.json()["detail"]]
    upstream_search.assert_not_called()


@pytest.mark.parametrize(
    "overrides",
    [
        {"check_in_date": "2026-09-29", "check_out_date": "2026-09-30"},
        {"check_in_date": "2028-02-29", "check_out_date": "2028-03-01"},
        {"adults": 1, "children": 0},
        {"adults": 20, "children": 20},
    ],
)
def test_valid_boundary_inputs_keep_existing_request_and_response(overrides, upstream_search):
    params = {**VALID_PARAMS, **overrides}
    response = client.get("/hotels/search", params=params)

    assert response.status_code == 200
    upstream_search.assert_called_once()
    sent = upstream_search.call_args.args[0]
    assert sent["check_in_date"] == params["check_in_date"]
    assert sent["check_out_date"] == params["check_out_date"]
    assert sent["adults"] == params.get("adults", 2)
    assert sent["children"] == params.get("children", 0)
    assert response.json()["result_count"] == 0


@pytest.mark.parametrize("field", ["adults", "children"])
def test_direct_model_rejects_boolean_guest_counts(field):
    with pytest.raises(ValidationError):
        HotelSearchRequest(**VALID_PARAMS, **{field: True})
