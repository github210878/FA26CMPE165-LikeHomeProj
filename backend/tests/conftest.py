"""
Ensures backend/ (which contains the app/ package) is on sys.path when
pytest is invoked with a working directory of tests/ itself — this happens
with some test runners (e.g. PyCharm's), which don't always honor the
`pythonpath` setting in pytest.ini the way plain `pytest` does.
"""

import os
import sys
from datetime import date

import pytest

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)


@pytest.fixture(autouse=True)
def fixed_stay_calendar(monkeypatch):
    """Keep search and booking fixtures valid regardless of the real date."""
    from app.schemas import booking_schema, hotel_schema

    class StayDate(date):
        @classmethod
        def today(cls):
            return cls(2026, 9, 29)

    monkeypatch.setattr(hotel_schema, "date", StayDate)
    monkeypatch.setattr(booking_schema, "date", StayDate)
