"""Tests for JWT creation and Bearer-token validation."""

from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from app.utilities import auth


@pytest.fixture(autouse=True)
def jwt_config(monkeypatch):
    monkeypatch.setattr(auth, "JWT_SECRET_KEY", "test-secret-for-jwt-unit-tests-32")
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


def test_active_user_with_matching_session_version_is_authorized(monkeypatch):
    token = auth.create_access_token(42, session_version=3)
    monkeypatch.setattr(
        auth.user_dao,
        "get_user_by_id",
        lambda **_: SimpleNamespace(status="active", session_version=3),
    )

    user_id = auth.get_current_user_id(
        db=object(),
        credentials=HTTPAuthorizationCredentials(
            scheme="Bearer",
            credentials=token,
        ),
    )

    assert user_id == 42


def test_deleted_user_is_rejected_without_being_reactivated(monkeypatch):
    deleted_user = SimpleNamespace(status="deleted", session_version=0)
    monkeypatch.setattr(
        auth.user_dao,
        "get_user_by_id",
        lambda **_: deleted_user,
    )
    token = auth.create_access_token(42, session_version=0)

    with pytest.raises(HTTPException) as exc_info:
        auth.get_current_user_id(
            db=object(),
            credentials=HTTPAuthorizationCredentials(
                scheme="Bearer",
                credentials=token,
            ),
        )

    assert exc_info.value.status_code == 401
    assert deleted_user.status == "deleted"


def test_old_session_version_is_rejected(monkeypatch):
    token = auth.create_access_token(42, session_version=1)
    monkeypatch.setattr(
        auth.user_dao,
        "get_user_by_id",
        lambda **_: SimpleNamespace(status="active", session_version=2),
    )

    with pytest.raises(HTTPException) as exc_info:
        auth.get_current_user_id(
            db=object(),
            credentials=HTTPAuthorizationCredentials(
                scheme="Bearer",
                credentials=token,
            ),
        )

    assert exc_info.value.status_code == 401


def test_missing_bearer_credentials_are_rejected():
    with pytest.raises(HTTPException) as exc_info:
        auth.get_current_user_id(db=object(), credentials=None)

    assert exc_info.value.status_code == 401


def test_expired_token_is_rejected(monkeypatch):
    monkeypatch.setattr(auth, "JWT_EXPIRE_MINUTES", -1)
    token = auth.create_access_token(42)

    with pytest.raises(HTTPException) as exc_info:
        auth.verify_access_token(
            HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
        )

    assert exc_info.value.status_code == 401