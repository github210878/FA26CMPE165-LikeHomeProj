
from unittest.mock import MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config.database import get_db
from app.routers.shortlist_router import router
from app.services import shortlist_service
from app.utilities.auth import get_current_user_id


def make_client(user_id=1):
    """Build an isolated app without changing main.py."""
    app = FastAPI()
    app.include_router(router)

    db = MagicMock()

    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user_id] = lambda: user_id

    return TestClient(app)


def test_add_shortlist_hotel(monkeypatch):
    monkeypatch.setattr(
        shortlist_service,
        "add_hotel",
        lambda db, user_id, token: {"property_token": token},
    )

    client = make_client()

    response = client.post(
        "/shortlist",
        json={"property_token": "hotel-123"},
    )

    assert response.status_code == 201
    assert response.json()["property_token"] == "hotel-123"


def test_get_shortlist(monkeypatch):
    monkeypatch.setattr(
        shortlist_service,
        "get_hotels",
        lambda db, user_id: {
            "properties": [{"property_token": "hotel-123"}]
        },
    )

    client = make_client()
    response = client.get("/shortlist")

    assert response.status_code == 200
    assert response.json()["properties"][0]["property_token"] == "hotel-123"


def test_remove_shortlist_hotel(monkeypatch):
    monkeypatch.setattr(
        shortlist_service,
        "remove_hotel",
        lambda db, user_id, token: None,
    )

    client = make_client()
    response = client.delete("/shortlist/hotel-123")

    assert response.status_code == 204


def test_invalid_shortlist_token():
    client = make_client()

    response = client.post(
        "/shortlist",
        json={"property_token": "   "},
    )

    assert response.status_code == 422


def test_shortlist_routes_require_authentication():
    """Check real authentication without overriding it."""
    app = FastAPI()
    app.include_router(router)

    app.dependency_overrides[get_db] = lambda: MagicMock()

    client = TestClient(app)

    assert client.get("/shortlist").status_code == 401
    assert client.post(
        "/shortlist",
        json={"property_token": "hotel-123"},
    ).status_code == 401
    assert client.delete("/shortlist/hotel-123").status_code == 401
