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
        "amenities": ["Free Wi-Fi", "Pool"],
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
        "cancellation_policies": None,
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


def test_details_maps_documented_original_images_with_thumbnail_and_legacy_fallbacks(client, monkeypatch):
    raw = property_data() | {
        "images": [
            {"original_image": " https://example.test/full.jpg ", "thumbnail": "https://example.test/small.jpg"},
            {"original_image": "https://example.test/full.jpg"},
            {"original": "https://example.test/legacy.jpg"},
            {"original_image": "javascript:alert(1)", "thumbnail": "https://example.test/fallback.jpg"},
            {"original_image": "https://[broken", "thumbnail": "file:///private.jpg"},
            {"thumbnail": "not a URL"},
            "https://example.test/unstructured.jpg",
            None,
        ],
    }
    monkeypatch.setattr(hotel_service.serpapi_client, "search_google_hotels", lambda _: raw)

    response = client.get("/hotels/details", params=VALID_PARAMS)

    assert response.status_code == 200
    assert response.json()["images"] == [
        "https://example.test/full.jpg",
        "https://example.test/legacy.jpg",
        "https://example.test/fallback.jpg",
    ]
    assert response.json()["thumbnail"] == "https://example.test/small.jpg"


@pytest.mark.parametrize("images, thumbnail", [
    ([{"original_image": "https://example.test/full.jpg"}], "https://example.test/full.jpg"),
    (None, "https://example.test/top-level.jpg"),
])
def test_details_thumbnail_survives_missing_image_thumbnail(client, monkeypatch, images, thumbnail):
    raw = property_data() | {"images": images}
    if images is None:
        raw["thumbnail"] = thumbnail
    monkeypatch.setattr(hotel_service.serpapi_client, "search_google_hotels", lambda _: raw)

    response = client.get("/hotels/details", params=VALID_PARAMS)

    assert response.status_code == 200
    assert response.json()["thumbnail"] == thumbnail


def test_details_keeps_cancellation_terms_with_each_provider_offer(client, monkeypatch):
    raw = property_data() | {"prices": [
        {
            "source": " Provider A ", "free_cancellation": True,
            "free_cancellation_until_date": " Nov 10 ",
            "free_cancellation_until_time": " 6:00 PM ",
            "rate_per_night": {"lowest": "$120", "extracted_lowest": 120, "private": "secret"},
            "total_rate": {"extracted_lowest": 240}, "private": "secret",
        },
        {
            "source": "Provider B", "free_cancellation": False,
            "free_cancellation_until_date": "must not imply free cancellation",
            "free_cancellation_until_time": "6:00 PM",
            "rate_per_night": {"extracted_lowest": 100},
        },
        {"source": "Provider C", "free_cancellation": True},
        {"source": "Unknown terms", "rate_per_night": {"extracted_lowest": 90}},
        {"source": "Malformed flag", "free_cancellation": "false"},
        {"source": "Numeric flag", "free_cancellation": 1},
        {"source": " ", "free_cancellation": True},
        None,
    ]}
    monkeypatch.setattr(hotel_service.serpapi_client, "search_google_hotels", lambda _: raw)

    response = client.get("/hotels/details", params=VALID_PARAMS)

    assert response.status_code == 200
    policies = response.json()["cancellation_policies"]
    assert [policy["source"] for policy in policies] == ["Provider A", "Provider B", "Provider C"]
    assert policies[0] == {
        "source": "Provider A", "free_cancellation": True,
        "free_cancellation_until_date": "Nov 10", "free_cancellation_until_time": "6:00 PM",
        "rate_per_night": {"lowest": "$120", "extracted_lowest": 120, "before_taxes_fees": None, "extracted_before_taxes_fees": None},
        "total_rate": {"lowest": None, "extracted_lowest": 240, "before_taxes_fees": None, "extracted_before_taxes_fees": None},
    }
    assert policies[1]["free_cancellation"] is False
    assert policies[1]["free_cancellation_until_date"] is None
    assert policies[1]["free_cancellation_until_time"] is None
    assert policies[2]["free_cancellation_until_date"] is None
    assert policies[2]["free_cancellation_until_time"] is None
    assert "private" not in response.text
    assert "prices" not in response.json()


@pytest.mark.parametrize("prices", [None, [], {}, [{"source": "Unknown terms"}], [{"source": "Bad", "free_cancellation": "true"}]])
def test_details_does_not_invent_cancellation_terms(client, monkeypatch, prices):
    monkeypatch.setattr(hotel_service.serpapi_client, "search_google_hotels", lambda _: property_data() | {"prices": prices})

    response = client.get("/hotels/details", params=VALID_PARAMS)

    assert response.status_code == 200
    assert response.json()["cancellation_policies"] is None


def test_details_with_only_required_fields_returns_unknown_optional_information(client, monkeypatch):
    monkeypatch.setattr(hotel_service.serpapi_client, "search_google_hotels", lambda _: {"property_token": "property-A", "name": "Hotel A"})

    response = client.get("/hotels/details", params=VALID_PARAMS)

    assert response.status_code == 200
    data = response.json()
    assert data.pop("property_token") == "property-A"
    assert data.pop("name") == "Hotel A"
    assert all(value is None for value in data.values())


def test_details_malformed_optional_fields_do_not_break_valid_property(client, monkeypatch):
    raw = property_data() | {
        "overall_rating": float("nan"), "reviews": True, "hotel_class": True,
        "amenities": [None, 123, " Wi-Fi ", "Wi-Fi", {"private": "secret"}, ""],
        "images": [None, {}, {"thumbnail": "data:image/png;base64,bad"}],
        "description": {}, "address": [], "phone": 123,
        "check_in_time": False, "check_out_time": " ",
        "rate_per_night": {"extracted_lowest": float("inf"), "extracted_before_taxes_fees": -1},
        "total_rate": {"lowest": "$200", "extracted_lowest": True},
        "prices": [{"source": "Provider A", "free_cancellation": True,
                    "free_cancellation_until_date": 123, "free_cancellation_until_time": {},
                    "rate_per_night": {"extracted_lowest": "120"}}],
    }
    monkeypatch.setattr(hotel_service.serpapi_client, "search_google_hotels", lambda _: raw)

    response = client.get("/hotels/details", params=VALID_PARAMS)

    assert response.status_code == 200
    data = response.json()
    assert data["amenities"] == ["Wi-Fi"]
    for field in ("overall_rating", "reviews", "hotel_class", "images", "thumbnail", "description", "address", "phone", "check_in_time", "check_out_time", "rate_per_night"):
        assert data[field] is None
    assert data["total_rate"]["lowest"] == "$200"
    assert data["total_rate"]["extracted_lowest"] is None
    assert data["cancellation_policies"][0]["free_cancellation_until_date"] is None
    assert data["cancellation_policies"][0]["free_cancellation_until_time"] is None
    assert data["cancellation_policies"][0]["rate_per_night"] is None


@pytest.mark.parametrize("hotel_class, extracted, expected", [
    (" 4-star hotel ", 5, "4-star hotel"),
    (4, None, "4-star hotel"),
    (None, 5, "5-star hotel"),
    (True, None, None),
    (0, 6, None),
])
def test_details_normalizes_text_and_numeric_hotel_class(client, monkeypatch, hotel_class, extracted, expected):
    raw = property_data() | {"hotel_class": hotel_class, "extracted_hotel_class": extracted}
    monkeypatch.setattr(hotel_service.serpapi_client, "search_google_hotels", lambda _: raw)

    response = client.get("/hotels/details", params=VALID_PARAMS)

    assert response.status_code == 200
    assert response.json()["hotel_class"] == expected


@pytest.mark.parametrize("rating, expected", [(0, 0), (5, 5), (5.1, None), (-1, None), (True, None), ("4.6", None)])
def test_details_preserves_valid_rating_boundaries_and_rejects_invalid_values(client, monkeypatch, rating, expected):
    monkeypatch.setattr(hotel_service.serpapi_client, "search_google_hotels", lambda _: property_data() | {"overall_rating": rating})

    response = client.get("/hotels/details", params=VALID_PARAMS)

    assert response.status_code == 200
    assert response.json()["overall_rating"] == expected
