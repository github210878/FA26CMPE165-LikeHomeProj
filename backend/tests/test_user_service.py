"""Unit tests for user registration and account-management business logic.

These tests stub the DAO, so they do not need MySQL and never write real user
data.  They cover the service decisions that are not exercised by the hotel
tests.
"""

from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.schemas.user_schema import (
    ChangePasswordRequest,
    DeleteUserRequest,
    LoginUserRequest,
    RegisterUserRequest,
)
from app.services import user_service


def make_user(**overrides):
    values = {
        "user_id": 7,
        "email": "person@example.com",
        "password_hash": "stored-hash",
        "full_name": "Person Example",
        "phone": "555-0100",
        "status": "active",
        "session_version": 0,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_register_normalizes_email_hashes_password_and_returns_public_fields(monkeypatch):
    captured = {}

    monkeypatch.setattr(user_service.user_dao, "get_user_by_email", lambda **_: None)

    class FakeHasher:
        def hash(self, password):
            captured["password"] = password
            return "new-hash"

    def create_user(**kwargs):
        captured.update(kwargs)
        return make_user(email=kwargs["email"], password_hash=kwargs["password_hash"])

    monkeypatch.setattr(user_service, "PASSWORD_HASHER", FakeHasher())
    monkeypatch.setattr(user_service.user_dao, "create_user", create_user)

    result = user_service.register_user(
        RegisterUserRequest(
            email="PERSON@Example.COM",
            password="password123",
            full_name="Person Example",
            phone="555-0100",
        ),
        db=object(),
    )

    assert captured["email"] == "person@example.com"
    assert captured["password"] == "password123"
    assert captured["password_hash"] == "new-hash"
    assert result.email == "person@example.com"
    assert result.user_id == 7


def test_register_rejects_duplicate_email(monkeypatch):
    monkeypatch.setattr(
        user_service.user_dao,
        "get_user_by_email",
        lambda **_: make_user(),
    )

    with pytest.raises(HTTPException) as exc_info:
        user_service.register_user(
            RegisterUserRequest(email="person@example.com", password="password123"),
            db=object(),
        )

    assert exc_info.value.status_code == 409


def test_login_returns_access_token_for_active_user(monkeypatch):
    user = make_user()
    monkeypatch.setattr(user_service.user_dao, "get_user_by_email", lambda **_: user)

    class FakeHasher:
        def verify(self, password, password_hash):
            return password == "password123" and password_hash == "stored-hash"

    monkeypatch.setattr(user_service, "PASSWORD_HASHER", FakeHasher())
    monkeypatch.setattr(
        user_service,
        "create_access_token",
        lambda user_id, session_version=0: "token-123",
    )

    result = user_service.login_user(
        LoginUserRequest(email="PERSON@EXAMPLE.COM", password="password123"),
        db=object(),
    )

    assert result.user_id == 7
    assert result.access_token == "token-123"
    assert result.token_type == "bearer"


@pytest.mark.parametrize("status", ["deleted"])
def test_login_rejects_deleted_user(monkeypatch, status):
    monkeypatch.setattr(
        user_service.user_dao,
        "get_user_by_email",
        lambda **_: make_user(status=status),
    )
    monkeypatch.setattr(user_service.PASSWORD_HASHER, "verify", lambda *_: True)

    with pytest.raises(HTTPException) as exc_info:
        user_service.login_user(
            LoginUserRequest(email="person@example.com", password="password123"),
            db=object(),
        )

    assert exc_info.value.status_code == 401


def test_change_password_requires_old_password_and_updates_hash(monkeypatch):
    user = make_user()
    captured = {}
    monkeypatch.setattr(user_service.user_dao, "get_user_by_id", lambda **_: user)

    class FakeHasher:
        def verify(self, password, password_hash):
            return password == "oldpass123"

        def hash(self, password):
            return f"hash:{password}"

    monkeypatch.setattr(user_service, "PASSWORD_HASHER", FakeHasher())
    monkeypatch.setattr(
        user_service.user_dao,
        "update_user_password",
        lambda **kwargs: captured.update(kwargs),
    )

    result = user_service.change_password(
        ChangePasswordRequest(
            old_password="oldpass123",
            new_password="newpass123",
        ),
        db=object(),
        user_id=7,
    )

    assert result["status"] is True
    assert captured["user_id"] == 7
    assert captured["new_password_hash"] == "hash:newpass123"


def test_delete_user_marks_account_deleted(monkeypatch):
    user = make_user()
    monkeypatch.setattr(user_service.user_dao, "get_user_by_id", lambda **_: user)
    monkeypatch.setattr(user_service.PASSWORD_HASHER, "verify", lambda *_: True)

    def delete_user(**_):
        user.status = "deleted"
        return user

    monkeypatch.setattr(user_service.user_dao, "delete_user", delete_user)

    result = user_service.delete_user(
        DeleteUserRequest(password="password123"),
        db=object(),
        user_id=7,
    )

    assert result == {"status": True, "message": "User deleted successfully"}


def test_logout_invalidates_all_sessions(monkeypatch):
    user = make_user()
    monkeypatch.setattr(
        user_service.user_dao,
        "invalidate_user_sessions",
        lambda **_: user,
    )

    result = user_service.logout_user(db=object(), user_id=7)

    assert result == {"status": True, "message": "Logged out successfully"}


def test_account_mutation_requests_reject_client_supplied_user_ids():
    with pytest.raises(ValidationError):
        ChangePasswordRequest(
            user_id=99,
            old_password="oldpass123",
            new_password="newpass123",
        )

    with pytest.raises(ValidationError):
        DeleteUserRequest(user_id=99, password="password123")
