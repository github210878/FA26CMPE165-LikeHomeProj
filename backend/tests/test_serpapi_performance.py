"""Repeatable local baseline for the SerpApi adapter.

These tests intentionally mock the network. They measure the adapter's parsing
and validation overhead, which is the part LikeHome controls; provider latency
is covered by the timeout/error tests and should be measured separately when a
real API key is available.
"""

from time import perf_counter

import pytest

from app.utilities import serpapi_client


SEARCH_PARAMS = {
    "q": "San Jose hotels",
    "check_in_date": "2026-10-05",
    "check_out_date": "2026-10-08",
    "adults": 2,
}


class FakeResponse:
    status_code = 200
    text = ""

    def __init__(self, payload):
        self.payload = payload

    def json(self):
        return self.payload


@pytest.mark.parametrize("property_count", [0, 10, 50])
def test_serpapi_adapter_p95_stays_within_local_baseline(monkeypatch, property_count):
    """The mocked adapter should remain below the 250 ms p95 local baseline."""
    monkeypatch.setattr(serpapi_client.Config, "API_KEY", "test-api-key")
    monkeypatch.setattr(serpapi_client.Config, "EXTERNAL_API_URL", "https://serpapi.com/search")
    payload = {"properties": [{"name": f"Hotel {i}"} for i in range(property_count)]}
    monkeypatch.setattr(
        serpapi_client.requests,
        "get",
        lambda url, params=None, timeout=None: FakeResponse(payload),
    )

    durations = []
    for _ in range(50):
        started = perf_counter()
        result = serpapi_client.search_google_hotels(SEARCH_PARAMS)
        durations.append(perf_counter() - started)

    assert len(result["properties"]) == property_count
    p95 = sorted(durations)[int(len(durations) * 0.95) - 1]
    assert p95 < 0.250
