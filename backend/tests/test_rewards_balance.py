
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.config.database import get_db
from app.routers.rewards_router import router
from app.services import rewards_service
from app.utilities.auth import get_current_user_id


def test_get_rewards_balance_success(monkeypatch):
    """Service returns the user's reward points."""
    db = MagicMock()

    monkeypatch.setattr(
        rewards_service.user_dao,
        "get_user_by_id",
        lambda db, user_id: SimpleNamespace(reward_points=250),
    )

    result = rewards_service.get_rewards_balance(db, 1)

    assert result.reward_points == 250


def test_get_rewards_balance_zero(monkeypatch):
    """A user can have zero reward points."""
    db = MagicMock()

    monkeypatch.setattr(
        rewards_service.user_dao,
        "get_user_by_id",
        lambda db, user_id: SimpleNamespace(reward_points=0),
    )

    result = rewards_service.get_rewards_balance(db, 1)

    assert result.reward_points == 0


def test_get_rewards_balance_missing_user(monkeypatch):
    """Missing users receive a 404 error."""
    db = MagicMock()

    monkeypatch.setattr(
        rewards_service.user_dao,
        "get_user_by_id",
        lambda db, user_id: None,
    )

    with pytest.raises(HTTPException) as exc:
        rewards_service.get_rewards_balance(db, 999)

    assert exc.value.status_code == 404


def test_rewards_balance_endpoint(monkeypatch):
    """Authenticated endpoint returns the balance."""
    app = FastAPI()
    app.include_router(router)

    app.dependency_overrides[get_db] = lambda: MagicMock()
    app.dependency_overrides[get_current_user_id] = lambda: 1

    monkeypatch.setattr(
        rewards_service,
        "get_rewards_balance",
        lambda db, user_id: {"reward_points": 250},
    )

    client = TestClient(app)
    response = client.get("/users/rewards/balance")

    assert response.status_code == 200
    assert response.json() == {"reward_points": 250}


def test_rewards_balance_requires_authentication():
    """Unauthenticated requests must be rejected."""
    app = FastAPI()
    app.include_router(router)

    app.dependency_overrides[get_db] = lambda: MagicMock()

    client = TestClient(app)
    response = client.get("/users/rewards/balance")

    assert response.status_code == 401
