"""Public registration and development CORS checks without MySQL or SerpApi."""

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.config.database import get_db
from app.main import app
from app.schemas.user_schema import RegisterUserResponse
from app.services import user_service

client = TestClient(app)


@pytest.fixture
def fake_db():
    app.dependency_overrides[get_db] = lambda: object()
    try:
        yield
    finally:
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.parametrize("origin", ["http://localhost:3000", "http://127.0.0.1:3000"])
@pytest.mark.parametrize(
    ("path", "method"),
    [("/users/register", "POST"), ("/hotels/search", "GET")],
)
def test_public_endpoint_cors_preflight(origin, path, method):
    response = client.options(
        path,
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": method,
            "Access-Control-Request-Headers": "content-type",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == origin
    assert method in response.headers["access-control-allow-methods"]
    assert "content-type" in response.headers["access-control-allow-headers"].lower()
    assert "access-control-allow-credentials" not in response.headers


def test_unlisted_origin_is_not_allowed():
    response = client.options(
        "/users/register",
        headers={
            "Origin": "http://unlisted.example",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )

    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers


def test_registration_returns_public_201_response(monkeypatch, fake_db):
    captured = {}

    def fake_register(user_info, db):
        captured["request"] = user_info
        return RegisterUserResponse(
            user_id=17,
            email=user_info.email,
            full_name=user_info.full_name,
            phone=user_info.phone,
        )

    monkeypatch.setattr(user_service, "register_user", fake_register)
    response = client.post(
        "/users/register",
        json={"email": "person@example.com", "password": "password123"},
        headers={"Origin": "http://localhost:3000"},
    )

    assert response.status_code == 201
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"
    assert response.json() == {
        "user_id": 17,
        "email": "person@example.com",
        "full_name": None,
        "phone": None,
    }
    assert captured["request"].full_name is None
    assert captured["request"].phone is None


def test_registration_duplicate_email_returns_409(monkeypatch, fake_db):
    def fake_register(_user_info, _db):
        raise HTTPException(status_code=409, detail="Email already registered")

    monkeypatch.setattr(user_service, "register_user", fake_register)
    response = client.post(
        "/users/register",
        json={"email": "person@example.com", "password": "password123"},
    )

    assert response.status_code == 409


@pytest.mark.parametrize(
    "payload",
    [
        {"email": "invalid", "password": "password123"},
        {"email": "person@example.com", "password": "short"},
    ],
)
def test_registration_invalid_request_returns_422(payload, fake_db):
    response = client.post("/users/register", json=payload)

    assert response.status_code == 422
