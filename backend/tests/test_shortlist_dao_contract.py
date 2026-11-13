
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.config.database import Base, get_db
from app.models.user import User
from app.models.shortlist import Shortlist
from app.routers.shortlist_router import router
from app.utilities.auth import get_current_user_id


@pytest.fixture
def shortlist_client():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    Base.metadata.create_all(engine)

    with Session(engine) as db:
        db.add_all([
            User(
                user_id=1,
                email="user1@example.test",
                password_hash="test",
            ),
            User(
                user_id=2,
                email="user2@example.test",
                password_hash="test",
            ),
        ])
        db.commit()

    app = FastAPI()
    app.include_router(router)

    def test_db():
        with Session(engine) as db:
            yield db

    app.dependency_overrides[get_db] = test_db
    app.dependency_overrides[get_current_user_id] = lambda: 1

    with TestClient(app) as client:
        yield client, app

    engine.dispose()


def test_add_and_retrieve_saved_hotel(shortlist_client):
    client, _ = shortlist_client

    response = client.post(
        "/shortlist",
        json={"property_token": "hotel-123"},
    )

    assert response.status_code == 201
    assert response.json()["property_token"] == "hotel-123"

    response = client.get("/shortlist")

    assert response.status_code == 200
    assert response.json()["properties"] == [
        {"property_token": "hotel-123"}
    ]


def test_duplicate_saved_hotel_returns_409(shortlist_client):
    client, _ = shortlist_client

    payload = {"property_token": "hotel-123"}

    assert client.post(
        "/shortlist", json=payload
    ).status_code == 201

    response = client.post("/shortlist", json=payload)

    assert response.status_code == 409

    assert len(
        client.get("/shortlist").json()["properties"]
    ) == 1


def test_delete_saved_hotel(shortlist_client):
    client, _ = shortlist_client

    client.post(
        "/shortlist",
        json={"property_token": "hotel-123"},
    )

    response = client.delete("/shortlist/hotel-123")

    assert response.status_code == 204
    assert client.get("/shortlist").json()["properties"] == []

    response = client.delete("/shortlist/hotel-123")
    assert response.status_code == 404


def test_shortlist_is_isolated_by_user(shortlist_client):
    client, app = shortlist_client

    client.post(
        "/shortlist",
        json={"property_token": "user1-hotel"},
    )

    # Authenticate as user 2.
    app.dependency_overrides[get_current_user_id] = lambda: 2

    response = client.get("/shortlist")
    assert response.status_code == 200
    assert response.json()["properties"] == []

    # User 2 cannot delete user 1's hotel.
    response = client.delete("/shortlist/user1-hotel")
    assert response.status_code == 404

    client.post(
        "/shortlist",
        json={"property_token": "user2-hotel"},
    )

    # Authenticate as user 1 again.
    app.dependency_overrides[get_current_user_id] = lambda: 1

    response = client.get("/shortlist")

    assert response.json()["properties"] == [
        {"property_token": "user1-hotel"}
    ]

    # User 1 cannot delete user 2's hotel.
    response = client.delete("/shortlist/user2-hotel")
    assert response.status_code == 404
