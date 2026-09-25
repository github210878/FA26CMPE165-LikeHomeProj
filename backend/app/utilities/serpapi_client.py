"""
Thin client around SerpApi's Google Hotels engine.

Responsibility: talk to SerpApi and hand back the raw parsed JSON. It does
NOT know about LikeHome's data models (that mapping is task 3.1.3) and does
NOT cache anything (that's task 3.1.4). Keeping it dumb like this makes it
easy to unit test (task 3.1.5: success, no-results, timeout, malformed).
"""

import requests

from app.config.config import Config

SERPAPI_ENGINE = "google_hotels"
DEFAULT_TIMEOUT_SECONDS = 10


class SerpApiError(Exception):
    """Base class for all errors raised by the SerpApi client."""


class SerpApiConfigError(SerpApiError):
    """Raised when the client is missing required configuration (e.g. API key)."""


class SerpApiTimeoutError(SerpApiError):
    """Raised when the request to SerpApi times out."""


class SerpApiRequestError(SerpApiError):
    """Raised for network-level failures (DNS, connection refused, etc.)."""


class SerpApiResponseError(SerpApiError):
    """Raised when SerpApi returns a non-2xx status or a malformed/error payload."""


def search_google_hotels(params: dict, timeout: int = DEFAULT_TIMEOUT_SECONDS) -> dict:
    """
    Call SerpApi's google_hotels engine and return the parsed JSON response.

    :param params: query params understood by SerpApi's google_hotels engine,
        e.g. {"q": "Bali Resorts", "check_in_date": "2026-10-05",
        "check_out_date": "2026-10-08", "adults": 2}
    :param timeout: request timeout in seconds.
    :raises SerpApiConfigError: if API_KEY is not configured.
    :raises SerpApiTimeoutError: if the request times out.
    :raises SerpApiRequestError: on network-level failure.
    :raises SerpApiResponseError: on a non-2xx response or a malformed/error payload.
    """
    if not Config.API_KEY:
        raise SerpApiConfigError(
            "API_KEY is not set. Add your SerpApi key to backend/.env"
        )

    base_url = Config.EXTERNAL_API_URL or "https://serpapi.com/search"

    request_params = {
        **params,
        "engine": SERPAPI_ENGINE,
        "api_key": Config.API_KEY,
    }

    try:
        response = requests.get(base_url, params=request_params, timeout=timeout)
    except requests.exceptions.Timeout as exc:
        raise SerpApiTimeoutError("Request to SerpApi timed out") from exc
    except requests.exceptions.RequestException as exc:
        raise SerpApiRequestError(f"Failed to reach SerpApi: {exc}") from exc

    if response.status_code != 200:
        raise SerpApiResponseError(
            f"SerpApi returned status {response.status_code}: {response.text[:300]}"
        )

    try:
        data = response.json()
    except ValueError as exc:
        raise SerpApiResponseError("SerpApi returned a non-JSON response") from exc

    if not isinstance(data, dict):
        raise SerpApiResponseError("SerpApi returned an unexpected response shape")

    error_message = data.get("error")
    if error_message:
        raise SerpApiResponseError(f"SerpApi error: {error_message}")

    return data
