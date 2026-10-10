"""UTC-naive values for SQL DATETIME/TIMESTAMP writes through UTC sessions."""

from datetime import datetime, timezone


def utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)
