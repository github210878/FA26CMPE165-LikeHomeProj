"""
Tests for app.utilities.serpapi_client — task 3.1.5.

Every test here mocks requests.get, so no real network call is made and no
real SerpApi key is required to run this file.
"""

import pytest
import requests

from app.utilities import serpapi_client
from app.utilities.serpapi_client import (
    SerpApiConfigError,
    SerpApiTimeoutError,
    SerpApiRequestError,
    SerpApiResponseError,
)

SEARCH_PARAMS = {
    "q": "San Jose hotels",
    "check_in_date": "2026-10-05",
    "check_out_date": "2026-10-08",
    "adults": 2,
}


class FakeResponse:
    """Minimal stand-in for requests.Response."""

    def __init__(self, status_code=200, json_data=None, text="", raise_json_error=False):
        self.status_code = status_code
        self._json_data = json_data
        self.text = text
        self._raise_json_error = raise_json_error

    def json(self):
        if self._raise_json_error:
            raise ValueError("No JSON object could be decoded")
        return self._json_data


@pytest.fixture(autouse=True)
def configured_api_key(monkeypatch):
    """Give every test in this file a valid API key + base URL by default."""
    monkeypatch.setattr(serpapi_client.Config, "API_KEY", "test-api-key")
    monkeypatch.setattr(
        serpapi_client.Config, "EXTERNAL_API_URL", "https://serpapi.com/search"
    )


# ---------------------------------------------------------------------------
# Config errors
# ---------------------------------------------------------------------------


def test_missing_api_key_raises_config_error_without_calling_requests(monkeypatch):
    monkeypatch.setattr(serpapi_client.Config, "API_KEY", None)
    called = {"count": 0}

    def fail_if_called(*args, **kwargs):
        called["count"] += 1
        raise AssertionError("requests.get should not be called without an API key")

    monkeypatch.setattr(serpapi_client.requests, "get", fail_if_called)

    with pytest.raises(SerpApiConfigError):
        serpapi_client.search_google_hotels(SEARCH_PARAMS)

    assert called["count"] == 0


def test_missing_external_api_url_falls_back_to_default(monkeypatch):
    monkeypatch.setattr(serpapi_client.Config, "EXTERNAL_API_URL", None)
    captured = {}

    def fake_get(url, params=None, timeout=None):
        captured["url"] = url
        return FakeResponse(status_code=200, json_data={"properties": []})

    monkeypatch.setattr(serpapi_client.requests, "get", fake_get)

    serpapi_client.search_google_hotels(SEARCH_PARAMS)

    assert captured["url"] == "https://serpapi.com/search"


# ---------------------------------------------------------------------------
# Success
# ---------------------------------------------------------------------------


def test_success_returns_parsed_json(monkeypatch):
    payload = {
        "search_metadata": {"status": "Success"},
        "properties": [{"name": "Hotel Testa", "property_token": "abc123"}],
    }

    monkeypatch.setattr(
        serpapi_client.requests,
        "get",
        lambda url, params=None, timeout=None: FakeResponse(200, json_data=payload),
    )

    result = serpapi_client.search_google_hotels(SEARCH_PARAMS)

    assert result == payload


def test_request_params_include_engine_and_api_key_and_preserve_caller_params(monkeypatch):
    captured = {}

    def fake_get(url, params=None, timeout=None):
        captured["params"] = params
        captured["timeout"] = timeout
        return FakeResponse(status_code=200, json_data={"properties": []})

    monkeypatch.setattr(serpapi_client.requests, "get", fake_get)

    serpapi_client.search_google_hotels(SEARCH_PARAMS, timeout=7)

    assert captured["params"]["engine"] == "google_hotels"
    assert captured["params"]["api_key"] == "test-api-key"
    for key, value in SEARCH_PARAMS.items():
        assert captured["params"][key] == value
    assert captured["timeout"] == 7


def test_no_results_returns_empty_properties_list(monkeypatch):
    payload = {"search_metadata": {"status": "Success"}, "properties": []}

    monkeypatch.setattr(
        serpapi_client.requests,
        "get",
        lambda url, params=None, timeout=None: FakeResponse(200, json_data=payload),
    )

    result = serpapi_client.search_google_hotels(SEARCH_PARAMS)

    assert result["properties"] == []


# ---------------------------------------------------------------------------
# Network-level failures
# ---------------------------------------------------------------------------


def test_timeout_raises_serpapi_timeout_error(monkeypatch):
    def fake_get(url, params=None, timeout=None):
        raise requests.exceptions.Timeout("timed out")

    monkeypatch.setattr(serpapi_client.requests, "get", fake_get)

    with pytest.raises(SerpApiTimeoutError):
        serpapi_client.search_google_hotels(SEARCH_PARAMS)


def test_connection_error_raises_serpapi_request_error(monkeypatch):
    def fake_get(url, params=None, timeout=None):
        raise requests.exceptions.ConnectionError("connection refused")

    monkeypatch.setattr(serpapi_client.requests, "get", fake_get)

    with pytest.raises(SerpApiRequestError):
        serpapi_client.search_google_hotels(SEARCH_PARAMS)


# ---------------------------------------------------------------------------
# Response-level failures
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("status_code", [400, 401, 403, 429, 500, 503])
def test_non_200_status_raises_serpapi_response_error(monkeypatch, status_code):
    monkeypatch.setattr(
        serpapi_client.requests,
        "get",
        lambda url, params=None, timeout=None: FakeResponse(
            status_code=status_code, text="upstream error"
        ),
    )

    with pytest.raises(SerpApiResponseError):
        serpapi_client.search_google_hotels(SEARCH_PARAMS)


def test_non_json_body_raises_serpapi_response_error(monkeypatch):
    monkeypatch.setattr(
        serpapi_client.requests,
        "get",
        lambda url, params=None, timeout=None: FakeResponse(
            status_code=200, raise_json_error=True, text="<html>not json</html>"
        ),
    )

    with pytest.raises(SerpApiResponseError):
        serpapi_client.search_google_hotels(SEARCH_PARAMS)


def test_json_body_not_a_dict_raises_serpapi_response_error(monkeypatch):
    monkeypatch.setattr(
        serpapi_client.requests,
        "get",
        lambda url, params=None, timeout=None: FakeResponse(
            status_code=200, json_data=["unexpected", "list"]
        ),
    )

    with pytest.raises(SerpApiResponseError):
        serpapi_client.search_google_hotels(SEARCH_PARAMS)


def test_serpapi_error_field_raises_serpapi_response_error(monkeypatch):
    monkeypatch.setattr(
        serpapi_client.requests,
        "get",
        lambda url, params=None, timeout=None: FakeResponse(
            status_code=200, json_data={"error": "Invalid API key."}
        ),
    )

    with pytest.raises(SerpApiResponseError, match="Invalid API key"):
        serpapi_client.search_google_hotels(SEARCH_PARAMS)
