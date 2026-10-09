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

    assert captured == {
        "q": "Bali resorts",
        "check_in_date": "2026-10-05",
        "check_out_date": "2026-10-08",
        "adults": 4,
        "children": 2,
        "currency": "EUR",
        "gl": "fr",
        "hl": "fr",
    }


def test_optional_search_controls_are_forwarded_without_leaking_ui_sorting(monkeypatch):
    captured = {}

    def fake_search(params):
        captured.update(params)
        return {"properties": []}

    monkeypatch.setattr(hotel_service.serpapi_client, "search_google_hotels", fake_search)

    hotel_service.search_hotels(
        make_request(
            next_page_token="next-page-token",
            no_cache=True,
            sort_by="price_low_to_high",
        ),
        db=object(),
    )

    assert captured["next_page_token"] == "next-page-token"
    assert captured["no_cache"] == "true"
    assert "sort_by" not in captured


def test_empty_optional_search_controls_are_not_forwarded(monkeypatch):
    captured = {}

    def fake_search(params):
        captured.update(params)
        return {"properties": []}

    monkeypatch.setattr(hotel_service.serpapi_client, "search_google_hotels", fake_search)

    hotel_service.search_hotels(
        make_request(next_page_token="", no_cache=False),
        db=object(),
    )

    assert "next_page_token" not in captured
    assert "no_cache" not in captured


def test_default_children_value_is_present_in_the_provider_payload(monkeypatch):
    captured = {}

    def fake_search(params):
        captured.update(params)
        return {"properties": []}

    monkeypatch.setattr(hotel_service.serpapi_client, "search_google_hotels", fake_search)

    hotel_service.search_hotels(make_request(children=0), db=object())

    assert captured["children"] == 0


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


def test_nested_serpapi_next_page_token_is_returned(monkeypatch):
    monkeypatch.setattr(
        hotel_service.serpapi_client,
        "search_google_hotels",
        lambda params: {
            "properties": [{"name": "Hotel A"}],
            "serpapi_pagination": {"next_page_token": "nested-next-page-123"},
        },
    )

    result = hotel_service.search_hotels(make_request(), db=object())

    assert result.next_page_token == "nested-next-page-123"


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


# ---------------------------------------------------------------------------
# Sprint 3 - Hotel sorting
# ---------------------------------------------------------------------------

def test_recommended_preserves_original_order():
    hotels = [
        hotel_service.HotelSearchResult(name="Hotel C", price_per_night=300),
        hotel_service.HotelSearchResult(name="Hotel A", price_per_night=100),
        hotel_service.HotelSearchResult(name="Hotel B", price_per_night=200),
    ]

    result = hotel_service._sort_hotels(hotels, "recommended")

    assert [h.name for h in result] == ["Hotel C", "Hotel A", "Hotel B"]


def test_price_low_to_high():
    hotels = [
        hotel_service.HotelSearchResult(name="Expensive", price_per_night=300),
        hotel_service.HotelSearchResult(name="Cheap", price_per_night=100),
        hotel_service.HotelSearchResult(name="Medium", price_per_night=200),
    ]

    result = hotel_service._sort_hotels(hotels, "price_low_to_high")

    assert [h.name for h in result] == ["Cheap", "Medium", "Expensive"]


def test_price_high_to_low():
    hotels = [
        hotel_service.HotelSearchResult(name="Cheap", price_per_night=100),
        hotel_service.HotelSearchResult(name="Expensive", price_per_night=300),
        hotel_service.HotelSearchResult(name="Medium", price_per_night=200),
    ]

    result = hotel_service._sort_hotels(hotels, "price_high_to_low")

    assert [h.name for h in result] == ["Expensive", "Medium", "Cheap"]


def test_rating_high_to_low():
    hotels = [
        hotel_service.HotelSearchResult(name="Hotel A", rating=3.5),
        hotel_service.HotelSearchResult(name="Hotel B", rating=4.9),
        hotel_service.HotelSearchResult(name="Hotel C", rating=4.2),
    ]

    result = hotel_service._sort_hotels(hotels, "rating_high_to_low")

    assert [h.name for h in result] == ["Hotel B", "Hotel C", "Hotel A"]


def test_missing_prices_are_last():
    hotels = [
        hotel_service.HotelSearchResult(name="No Price"),
        hotel_service.HotelSearchResult(name="Hotel A", price_per_night=150),
        hotel_service.HotelSearchResult(name="Hotel B", price_per_night=100),
    ]

    result = hotel_service._sort_hotels(hotels, "price_low_to_high")

    assert [h.name for h in result] == ["Hotel B", "Hotel A", "No Price"]


def test_equal_prices_preserve_original_order():
    hotels = [
        hotel_service.HotelSearchResult(name="Hotel A", price_per_night=150),
        hotel_service.HotelSearchResult(name="Hotel B", price_per_night=150),
        hotel_service.HotelSearchResult(name="Hotel C", price_per_night=100),
    ]

    result = hotel_service._sort_hotels(hotels, "price_low_to_high")

    assert [h.name for h in result] == ["Hotel C", "Hotel A", "Hotel B"]



def test_search_request_accepts_supported_sort_options():
    for option in (
        "recommended",
        "price_low_to_high",
        "price_high_to_low",
        "rating_high_to_low",
    ):
        request = make_request(sort_by=option)
        assert request.sort_by == option


def test_search_request_rejects_invalid_sort_option():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        make_request(sort_by="random")


def test_search_applies_sort_to_mapped_results(monkeypatch):
    properties = [
        {"name": "Expensive", "rate_per_night": {"extracted_lowest": 300}},
        {"name": "Cheap", "rate_per_night": {"extracted_lowest": 100}},
        {"name": "Medium", "rate_per_night": {"extracted_lowest": 200}},
    ]

    monkeypatch.setattr(
        hotel_service.serpapi_client,
        "search_google_hotels",
        lambda params: {"properties": properties},
    )

    result = hotel_service.search_hotels(
        make_request(sort_by="price_low_to_high"),
        db=object(),
    )

    assert [hotel.name for hotel in result.properties] == [
        "Cheap",
        "Medium",
        "Expensive",
    ]