"""JWT role boundaries using only test secrets, mocks, and in-process HTTP."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import jwt
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from fastapi.testclient import TestClient
from fastapi.routing import APIRoute

from app.config.database import get_db
from app.routers.booking_router import router as booking_router
from app.routers.partner_router import router as partner_router
from app.routers.user_router import router as user_router
from app.schemas.partner_schema import PartnerLoginRequest
from app.schemas.user_schema import LoginUserRequest
from app.services import booking_service, partner_service, user_service
from app.utilities import auth


@pytest.fixture(autouse=True)
def test_jwt_config(monkeypatch):
    monkeypatch.setattr(auth, "JWT_SECRET_KEY", "test-role-separation-secret-32chars")
    monkeypatch.setattr(auth, "JWT_ALGORITHM", "HS256")


def credentials(subject_type, version=0):
    token = auth.create_access_token(
        1, session_version=version, subject_type=subject_type
    )
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)


def mock_colliding_accounts(monkeypatch, *, user_version=0, partner_version=0):
    monkeypatch.setattr(
        auth.user_dao,
        "get_user_by_id",
        lambda **_: SimpleNamespace(status="active", session_version=user_version),
    )
    monkeypatch.setattr(
        auth.partner_dao,
        "get_partner_by_id",
        lambda **_: SimpleNamespace(session_version=partner_version),
    )


def test_id_collision_cannot_cross_account_types(monkeypatch):
    mock_colliding_accounts(monkeypatch)
    for guard, wrong_type in (
        (auth.get_current_user_id, "partner"),
        (auth.get_current_partner_id, "user"),
    ):
        with pytest.raises(HTTPException) as error:
            guard(db=object(), credentials=credentials(wrong_type))
        assert error.value.status_code == 401
        assert "partner" not in error.value.detail.lower()


def test_wrong_type_is_rejected_before_account_lookup(monkeypatch):
    monkeypatch.setattr(
        auth.user_dao, "get_user_by_id", lambda **_: pytest.fail("user lookup called")
    )
    monkeypatch.setattr(
        auth.partner_dao,
        "get_partner_by_id",
        lambda **_: pytest.fail("partner lookup called"),
    )
    with pytest.raises(HTTPException) as user_error:
        auth.get_current_user_id(db=object(), credentials=credentials("partner"))
    with pytest.raises(HTTPException) as partner_error:
        auth.get_current_partner_id(db=object(), credentials=credentials("user"))
    assert user_error.value.status_code == partner_error.value.status_code == 401


def test_same_role_tokens_work_and_session_versions_still_apply(monkeypatch):
    mock_colliding_accounts(monkeypatch, user_version=2, partner_version=0)
    assert auth.get_current_user_id(db=object(), credentials=credentials("user", 2)) == 1
    assert auth.get_current_partner_id(db=object(), credentials=credentials("partner")) == 1

    with pytest.raises(HTTPException) as old_user:
        auth.get_current_user_id(db=object(), credentials=credentials("user", 1))
    with pytest.raises(HTTPException) as wrong_partner_version:
        auth.get_current_partner_id(db=object(), credentials=credentials("partner", 1))
    assert old_user.value.status_code == wrong_partner_version.value.status_code == 401

    # Logout and password changes increment this version; deletion also sets
    # status to deleted. All three existing account-state checks remain active.
    mock_colliding_accounts(monkeypatch, user_version=3)
    with pytest.raises(HTTPException):
        auth.get_current_user_id(db=object(), credentials=credentials("user", 2))
    monkeypatch.setattr(
        auth.user_dao,
        "get_user_by_id",
        lambda **_: SimpleNamespace(status="deleted", session_version=3),
    )
    with pytest.raises(HTTPException):
        auth.get_current_user_id(db=object(), credentials=credentials("user", 3))


@pytest.mark.parametrize("subject_type", [None, "admin", 1, ["user"]])
def test_missing_or_invalid_signed_type_is_rejected(monkeypatch, subject_type):
    payload = {
        "sub": "1",
        "ver": 0,
        "iat": datetime.now(timezone.utc),
        "exp": datetime.now(timezone.utc) + timedelta(minutes=10),
    }
    if subject_type is not None:
        payload["type"] = subject_type
    token = jwt.encode(payload, auth.JWT_SECRET_KEY, algorithm=auth.JWT_ALGORITHM)
    bearer = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
    mock_colliding_accounts(monkeypatch)
    for guard in (auth.get_current_user_id, auth.get_current_partner_id):
        with pytest.raises(HTTPException) as error:
            guard(db=object(), credentials=bearer)
        assert error.value.status_code == 401


def test_user_login_issues_signed_user_type(monkeypatch):
    user = SimpleNamespace(
        user_id=1, email="person@example.com", full_name=None, phone=None,
        password_hash="stored", status="active", session_version=4,
    )
    monkeypatch.setattr(user_service.user_dao, "get_user_by_email", lambda **_: user)
    monkeypatch.setattr(user_service.PASSWORD_HASHER, "verify", lambda *_: True)
    response = user_service.login_user(
        LoginUserRequest(email="person@example.com", password="password123"), object()
    )
    claims = jwt.decode(response.access_token, auth.JWT_SECRET_KEY, algorithms=["HS256"])
    assert (claims["sub"], claims["type"], claims["ver"]) == ("1", "user", 4)
    assert response.token_type == "bearer"


def test_partner_login_issues_signed_partner_type(monkeypatch):
    partner = SimpleNamespace(partner_id=1, password_hash="stored")

    class FakeDb:
        def query(self, model):
            return self

        def filter_by(self, **filters):
            return self

        def first(self):
            return partner

    monkeypatch.setattr(partner_service.PASSWORD_HASHER, "verify", lambda *_: True)
    response = partner_service.login_partner(
        FakeDb(), PartnerLoginRequest(user_name="partner", password="password123")
    )
    claims = jwt.decode(response.access_token, auth.JWT_SECRET_KEY, algorithms=["HS256"])
    assert (claims["sub"], claims["type"], claims["ver"]) == ("1", "partner", 0)
    assert response.token_type == "bearer"


def test_http_routes_reject_opposite_type_and_accept_correct_type(monkeypatch):
    mock_colliding_accounts(monkeypatch)
    monkeypatch.setattr(
        booking_service, "get_all_booking_by_user_id", lambda db, user_id: []
    )
    monkeypatch.setattr(partner_service, "check_booking", lambda db, partner_id: [])
    app = FastAPI()
    app.include_router(user_router)
    app.include_router(booking_router)
    app.include_router(partner_router)
    app.dependency_overrides[get_db] = lambda: object()
    client = TestClient(app)

    for path in ("/users/me", "/bookings/get-all-bookings"):
        response = client.get(
            path,
            headers={"Authorization": f"Bearer {credentials('partner').credentials}"},
        )
        assert response.status_code == 401
        assert "partner" not in response.json()["detail"].lower()
    response = client.get(
        "/partners/check_booking/",
        headers={"Authorization": f"Bearer {credentials('user').credentials}"},
    )
    assert response.status_code == 401
    assert client.get(
        "/users/me",
        headers={"Authorization": f"Bearer {credentials('user').credentials}"},
    ).status_code == 200
    assert client.get(
        "/partners/check_booking/",
        headers={"Authorization": f"Bearer {credentials('partner').credentials}"},
    ).status_code == 200


def test_protected_routes_share_the_role_checked_dependencies():
    public_user_paths = {"/users/register", "/users/login"}
    public_partner_paths = {"/partners/register", "/partners/login"}
    for router, public_paths, guard in (
        (user_router, public_user_paths, auth.get_current_user_id),
        (booking_router, set(), auth.get_current_user_id),
        (partner_router, public_partner_paths, auth.get_current_partner_id),
    ):
        for route in router.routes:
            if not isinstance(route, APIRoute) or route.path in public_paths:
                continue
            assert guard in {dependency.call for dependency in route.dependant.dependencies}, route.path
