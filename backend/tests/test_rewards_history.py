
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI, HTTPException, status
from fastapi.testclient import TestClient

from app.config.database import get_db
from app.routers.rewards_router import router
from app.services import rewards_service
from app.utilities.auth import get_current_user_id


def make_client(authenticated=True):
    app = FastAPI()
    app.include_router(router)

    app.dependency_overrides[get_db] = lambda: MagicMock()

    if authenticated:
        app.dependency_overrides[get_current_user_id] = lambda: 1

    return TestClient(app)


def test_history_service_not_implemented():
    db = MagicMock()

    with pytest.raises(HTTPException) as exc:
        rewards_service.get_rewards_history(db, 1)

    assert exc.value.status_code == 501


def test_history_endpoint_not_implemented():
    client = make_client()

    response = client.get("/users/rewards/history")

    assert response.status_code == 501
    assert response.json()["detail"] == "Rewards history is not yet available"


def test_history_requires_authentication():
    client = make_client(authenticated=False)

    response = client.get("/users/rewards/history")

    assert response.status_code == 401


def test_history_endpoint_uses_authenticated_user(monkeypatch):
    received = {}

    def fake_history(db, user_id):
        received["user_id"] = user_id
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="Rewards history is not yet available",
        )

    monkeypatch.setattr(
        rewards_service,
        "get_rewards_history",
        fake_history,
    )

    client = make_client()
    response = client.get("/users/rewards/history")

    assert response.status_code == 501
    assert received["user_id"] == 1
