"""
Tests for app.services.hotel_service — task 3.1.5.

These mock app.services.hotel_service.serpapi_client.search_google_hotels
directly, so they don't depend on the HTTP layer at all (that's covered
separately in test_serpapi_client.py).
"""

import pytest
from fastapi import HTTPException

from app.schemas.hotel_schema import HotelSearchRequest
from app.services import hotel_service
from app.utilities.serpapi_client import (
    SerpApiConfigError,
    SerpApiTimeoutError,
    SerpApiRequestError,
    SerpApiResponseError,
)


@pytest.fixture(autouse=True)
def disable_cache_for_mapping_tests(monkeypatch):
    monkeypatch.setattr(hotel_service, "_cache_hotels", lambda **_: None)


def make_request(**overrides):
    defaults = dict(
        q="San Jose hotels",
        check_in_date="2026-10-05",
        check_out_date="2026-10-08",
        adults=2,
        children=0,
        currency="USD",
        gl="us",
        hl="en",
    )
    defaults.update(overrides)
    return HotelSearchRequest(**defaults)


FULL_PROPERTY = {
    "name": "Hotel Testa",
    "property_token": "abc123",
    "hotel_class": "4-star hotel",
    "overall_rating": 4.4,
    "reviews": 812,
    "rate_per_night": {"lowest": "$150", "extracted_lowest": 150},
    "total_rate": {"lowest": "$450", "extracted_lowest": 450},
    "amenities": ["Free Wi-Fi", "Pool"],
    "images": [{"thumbnail": "http://example.com/thumb.jpg"}],
    "link": "http://example.com/hotel",
    "gps_coordinates": {"latitude": 37.33, "longitude": -121.88},
}


# ---------------------------------------------------------------------------
# Success / mapping
# ---------------------------------------------------------------------------


def test_full_property_maps_all_fields(monkeypatch):
    monkeypatch.setattr(
        hotel_service.serpapi_client,
        "search_google_hotels",
        lambda params: {"properties": [FULL_PROPERTY]},
    )

    result = hotel_service.search_hotels(make_request(), db=object())

    assert result.result_count == 1
    hotel = result.properties[0]
    assert hotel.name == "Hotel Testa"
    assert hotel.property_token == "abc123"
    assert hotel.price_per_night == 150
    assert hotel.rating == 4.4
    assert hotel.overall_rating == 4.4
    assert hotel.reviews == 812
    assert hotel.rate_per_night.extracted_lowest == 150
    assert hotel.amenities == ["Free Wi-Fi", "Pool"]
    assert hotel.thumbnail == "http://example.com/thumb.jpg"
    assert hotel.link == "http://example.com/hotel"


def test_property_missing_optional_fields_does_not_crash(monkeypatch):
    sparse_property = {"name": "Bare Bones Inn"}
    monkeypatch.setattr(
        hotel_service.serpapi_client,
        "search_google_hotels",
        lambda params: {"properties": [sparse_property]},
    )

    result = hotel_service.search_hotels(make_request(), db=object())

    hotel = result.properties[0]
    assert hotel.name == "Bare Bones Inn"
    assert hotel.price_per_night is None
    assert hotel.rating is None
    assert hotel.property_token is None
    assert hotel.reviews is None
    assert hotel.amenities is None
    assert hotel.thumbnail is None


def test_property_with_no_images_has_none_thumbnail(monkeypatch):
    property_without_images = {**FULL_PROPERTY, "images": []}
    monkeypatch.setattr(
        hotel_service.serpapi_client,
        "search_google_hotels",
        lambda params: {"properties": [property_without_images]},
    )

    result = hotel_service.search_hotels(make_request(), db=object())

    assert result.properties[0].thumbnail is None


def test_multiple_properties_preserve_count_and_order(monkeypatch):
    properties = [{"name": "Hotel A"}, {"name": "Hotel B"}, {"name": "Hotel C"}]
    monkeypatch.setattr(
        hotel_service.serpapi_client,
        "search_google_hotels",
        lambda params: {"properties": properties},
    )

    result = hotel_service.search_hotels(make_request(), db=object())

    assert result.result_count == 3
    assert [p.name for p in result.properties] == ["Hotel A", "Hotel B", "Hotel C"]


def test_malformed_property_fields_do_not_break_search(monkeypatch):
    malformed_property = {
        "name": "  Hotel Testa  ",
        "property_token": "  abc123  ",
        "overall_rating": "unavailable",
        "rate_per_night": {"extracted_lowest": "unavailable"},
        "amenities": [" Free Wi-Fi ", None, 12, ""],
        "images": [None, {"thumbnail": "  http://example.com/thumb.jpg  "}],
    }
    monkeypatch.setattr(
        hotel_service.serpapi_client,
        "search_google_hotels",
        lambda params: {"properties": [malformed_property]},
    )

    result = hotel_service.search_hotels(make_request(), db=object())

    hotel = result.properties[0]
    assert hotel.name == "Hotel Testa"
    assert hotel.property_token == "abc123"
    assert hotel.price_per_night is None
    assert hotel.rating is None
    assert hotel.amenities == ["Free Wi-Fi"]
    assert hotel.thumbnail == "http://example.com/thumb.jpg"


def test_non_property_items_are_skipped(monkeypatch):
    monkeypatch.setattr(
        hotel_service.serpapi_client,
        "search_google_hotels",
        lambda params: {"properties": [None, "bad item", {"name": "Hotel A"}]},
    )

    result = hotel_service.search_hotels(make_request(), db=object())

    assert result.result_count == 1
    assert result.properties[0].name == "Hotel A"


# ---------------------------------------------------------------------------
# No-results cases
# ---------------------------------------------------------------------------


def test_empty_properties_list_is_not_an_error(monkeypatch):
    monkeypatch.setattr(
        hotel_service.serpapi_client,
        "search_google_hotels",
        lambda params: {"properties": []},
    )

    result = hotel_service.search_hotels(make_request(), db=object())

    assert result.result_count == 0
    assert result.properties == []


def test_missing_properties_key_is_treated_as_no_results(monkeypatch):
    monkeypatch.setattr(
        hotel_service.serpapi_client,
        "search_google_hotels",
        lambda params: {"search_metadata": {"status": "Success"}},
    )

    result = hotel_service.search_hotels(make_request(), db=object())

    assert result.result_count == 0
    assert result.properties == []


# ---------------------------------------------------------------------------
# Error translation
# ---------------------------------------------------------------------------


def test_config_error_becomes_http_500(monkeypatch):
    def raise_config_error(params):
        raise SerpApiConfigError("API_KEY is not set")

    monkeypatch.setattr(hotel_service.serpapi_client, "search_google_hotels", raise_config_error)

    with pytest.raises(HTTPException) as exc_info:
        hotel_service.search_hotels(make_request(), db=object())

    assert exc_info.value.status_code == 500
    assert exc_info.value.detail == "Hotel search service is not configured"


def test_timeout_error_becomes_http_504(monkeypatch):
    def raise_timeout(params):
        raise SerpApiTimeoutError("timed out")

    monkeypatch.setattr(hotel_service.serpapi_client, "search_google_hotels", raise_timeout)

    with pytest.raises(HTTPException) as exc_info:
        hotel_service.search_hotels(make_request(), db=object())

    assert exc_info.value.status_code == 504
    assert exc_info.value.detail == "Hotel search service timed out"


@pytest.mark.parametrize("error_cls", [SerpApiRequestError, SerpApiResponseError])
def test_request_and_response_errors_become_http_502(monkeypatch, error_cls):
    def raise_error(params):
        raise error_cls("upstream problem")

    monkeypatch.setattr(hotel_service.serpapi_client, "search_google_hotels", raise_error)

    with pytest.raises(HTTPException) as exc_info:
        hotel_service.search_hotels(make_request(), db=object())

    assert exc_info.value.status_code == 502


def test_serpapi_error_detail_is_not_exposed(monkeypatch):
    def raise_error(params):
        raise SerpApiResponseError("SerpApi error: Invalid API key.")

    monkeypatch.setattr(
        hotel_service.serpapi_client,
        "search_google_hotels",
        raise_error,
    )

    with pytest.raises(HTTPException) as exc_info:
        hotel_service.search_hotels(make_request(), db=object())

    assert exc_info.value.status_code == 502
    assert exc_info.value.detail == "Hotel search service returned an error"
    assert "Invalid API key" not in exc_info.value.detail

# ---------------------------------------------------------------------------
# Request params sent to the client
# ---------------------------------------------------------------------------


def test_service_forwards_all_search_fields_to_client(monkeypatch):
    captured = {}

    def fake_search(params):
        captured.update(params)
        return {"properties": []}

    monkeypatch.setattr(hotel_service.serpapi_client, "search_google_hotels", fake_search)

    hotel_service.search_hotels(
        make_request(q="Bali resorts", adults=4, children=2, currency="EUR", gl="fr", hl="fr"),
        db=object(),
    )

    assert captured["q"] == "Bali resorts"
    assert captured["adults"] == 4
    assert captured["children"] == 2
    assert captured["currency"] == "EUR"
    assert captured["gl"] == "fr"
    assert captured["hl"] == "fr"


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------


def test_next_page_token_is_returned(monkeypatch):
    monkeypatch.setattr(
        hotel_service.serpapi_client,
        "search_google_hotels",
        lambda params: {
            "properties": [{"name": "Hotel A"}],
            "next_page_token": "next-page-123",
        },
    )

    result = hotel_service.search_hotels(make_request(), db=object())

    assert result.next_page_token == "next-page-123"


def test_next_page_token_is_forwarded_to_serpapi(monkeypatch):
    captured = {}

    def fake_search(params):
        captured.update(params)
        return {"properties": []}

    monkeypatch.setattr(
        hotel_service.serpapi_client,
        "search_google_hotels",
        fake_search,
    )

    hotel_service.search_hotels(
        make_request(next_page_token="next-page-123"), db=object()
    )

    assert captured["next_page_token"] == "next-page-123"


def test_missing_next_page_token_returns_none(monkeypatch):
    monkeypatch.setattr(
        hotel_service.serpapi_client,
        "search_google_hotels",
        lambda params: {"properties": []},
    )

    result = hotel_service.search_hotels(make_request(), db=object())

    assert result.next_page_token is None
