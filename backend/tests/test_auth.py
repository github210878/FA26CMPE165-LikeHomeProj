"""Tests for JWT creation and Bearer-token validation."""

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from app.utilities import auth


@pytest.fixture(autouse=True)
def jwt_config(monkeypatch):
    monkeypatch.setattr(auth, "JWT_SECRET_KEY", "test-secret")
    monkeypatch.setattr(auth, "JWT_ALGORITHM", "HS256")


def test_create_and_verify_access_token_round_trip():
    token = auth.create_access_token(42)

    assert auth.verify_access_token(
        HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
    ) == 42


def test_invalid_token_is_rejected():
    with pytest.raises(HTTPException) as exc_info:
        auth.verify_access_token(
            HTTPAuthorizationCredentials(scheme="Bearer", credentials="not-a-token")
        )

    assert exc_info.value.status_code == 401


def test_missing_jwt_secret_is_configuration_error(monkeypatch):
    monkeypatch.setattr(auth, "JWT_SECRET_KEY", None)

    with pytest.raises(RuntimeError, match="JWT_SECRET_KEY"):
        auth.create_access_token(42)
