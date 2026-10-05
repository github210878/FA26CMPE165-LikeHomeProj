"""HTTP-level tests for protected user routes."""

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config.database import get_db
from app.routers.user_router import router as user_router
from app.utilities import auth


@pytest.fixture
def client(monkeypatch):
    test_app = FastAPI()
    test_app.include_router(user_router)
    test_app.dependency_overrides[get_db] = lambda: object()

    monkeypatch.setattr(
        auth,
        "JWT_SECRET_KEY",
        "test-secret-for-http-tests-32chars",
    )
    monkeypatch.setattr(auth, "JWT_ALGORITHM", "HS256")

    yield TestClient(test_app)


def make_user(status="active", session_version=0):
    return SimpleNamespace(status=status, session_version=session_version)


def test_users_me_requires_a_bearer_token(client):
    response = client.get("/users/me")

    assert response.status_code == 401


def test_users_me_accepts_a_valid_active_user_token(client, monkeypatch):
    monkeypatch.setattr(
        auth.user_dao,
        "get_user_by_id",
        lambda **_: make_user(),
    )
    token = auth.create_access_token(7, subject_type="user")

    response = client.get(
        "/users/me",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    assert response.json()["user_id"] == 7


def test_users_me_rejects_deleted_user_without_reactivating_it(client, monkeypatch):
    deleted_user = make_user(status="deleted")
    monkeypatch.setattr(
        auth.user_dao,
        "get_user_by_id",
        lambda **_: deleted_user,
    )
    token = auth.create_access_token(7, subject_type="user")

    response = client.get(
        "/users/me",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 401
    assert deleted_user.status == "deleted"
