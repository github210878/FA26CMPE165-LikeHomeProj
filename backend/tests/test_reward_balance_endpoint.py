
"""Tests for the authenticated reward balance endpoint."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.config.database import Base, get_db
from app.models.user import User
from app.routers.user_router import router
from app.utilities.auth import get_current_user_id


@pytest.fixture
def reward_client():
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
                email="first@example.test",
                password_hash="test-hash",
                reward_points=250,
            ),
            User(
                user_id=2,
                email="second@example.test",
                password_hash="test-hash",
                reward_points=900,
            ),
        ])
        db.commit()

    app = FastAPI()
    app.include_router(router)

    def get_test_db():
        with Session(engine) as db:
            yield db

    app.dependency_overrides[get_db] = get_test_db
    app.dependency_overrides[get_current_user_id] = lambda: 1

    with TestClient(app) as client:
        yield client, app

    engine.dispose()


def test_reward_balance_returns_authenticated_users_points(reward_client):
    client, _ = reward_client

    response = client.get("/users/get-reward-points")

    assert response.status_code == 200
    assert response.json()["reward_points"] == 250


def test_reward_balance_does_not_return_other_users_points(reward_client):
    client, _ = reward_client

    response = client.get("/users/get-reward-points")

    assert response.status_code == 200
    assert response.json()["reward_points"] != 900


def test_reward_balance_missing_user_returns_404(reward_client):
    client, app = reward_client
    app.dependency_overrides[get_current_user_id] = lambda: 999

    response = client.get("/users/get-reward-points")

    assert response.status_code == 404
