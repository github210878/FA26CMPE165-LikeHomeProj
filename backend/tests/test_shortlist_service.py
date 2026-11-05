
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from app.services import shortlist_service


def test_add_hotel_success(monkeypatch):
    db = MagicMock()

    monkeypatch.setattr(
        shortlist_service.shortlist_dao,
        "get_saved_hotel",
        lambda db, user_id, token: None,
    )

    monkeypatch.setattr(
        shortlist_service.shortlist_dao,
        "add_saved_hotel",
        lambda db, user_id, token: SimpleNamespace(
            property_token=token
        ),
    )

    result = shortlist_service.add_hotel(db, 1, "hotel-123")

    assert result.property_token == "hotel-123"


def test_add_duplicate_hotel(monkeypatch):
    db = MagicMock()

    monkeypatch.setattr(
        shortlist_service.shortlist_dao,
        "get_saved_hotel",
        lambda db, user_id, token: SimpleNamespace(
            property_token=token
        ),
    )

    with pytest.raises(HTTPException) as exc:
        shortlist_service.add_hotel(db, 1, "hotel-123")

    assert exc.value.status_code == 409


def test_get_saved_hotels(monkeypatch):
    db = MagicMock()

    monkeypatch.setattr(
        shortlist_service.shortlist_dao,
        "get_saved_hotels",
        lambda db, user_id: [
            SimpleNamespace(property_token="hotel-123"),
            SimpleNamespace(property_token="hotel-456"),
        ],
    )

    result = shortlist_service.get_hotels(db, 1)

    assert len(result.properties) == 2
    assert result.properties[0].property_token == "hotel-123"
    assert result.properties[1].property_token == "hotel-456"


def test_remove_hotel_success(monkeypatch):
    db = MagicMock()

    monkeypatch.setattr(
        shortlist_service.shortlist_dao,
        "delete_saved_hotel",
        lambda db, user_id, token: True,
    )

    assert shortlist_service.remove_hotel(db, 1, "hotel-123") is None


def test_remove_missing_hotel(monkeypatch):
    db = MagicMock()

    monkeypatch.setattr(
        shortlist_service.shortlist_dao,
        "delete_saved_hotel",
        lambda db, user_id, token: False,
    )

    with pytest.raises(HTTPException) as exc:
        shortlist_service.remove_hotel(db, 1, "missing-hotel")

    assert exc.value.status_code == 404
