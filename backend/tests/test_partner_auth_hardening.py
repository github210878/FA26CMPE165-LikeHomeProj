"""JSON-only partner credentials with synthetic SQLite and in-process HTTP."""

import logging

import pytest
from fastapi.security import HTTPAuthorizationCredentials
from fastapi.testclient import TestClient
from pwdlib import PasswordHash
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.config.database import get_db
from app.models.hotel import Hotel
from app.models.partner_model import HotelPartner
from app.models.reservation import Reservation
from app.models.user import User
from app.schemas.partner_schema import PartnerLoginRequest
from app.services import partner_service
from app.utilities import auth
from test_partner_hotel_ownership import ownership_app as ownership_app


def registration(**changes):
    return {"user_name": "json-partner", "password": "json-secret", "hotel_name": "JSON Hotel", **changes}


def login(**changes):
    return {"user_name": "eligible-partner", "password": "password123", **changes}


def counts(engine):
    with Session(engine) as db:
        return tuple(db.query(model).count() for model in (Hotel, HotelPartner, User, Reservation))


def assert_no_sensitive_values(text, *values):
    assert all(value not in text for value in values), "Sensitive value appeared in response or log"


def test_json_registration_preserves_server_generated_identity_and_response(ownership_app):
    client, engine, _ = ownership_app
    response = client.post("/partners/register", json=registration())
    assert response.status_code == 200
    assert set(response.json()) == {"partner_id"}
    partner_id = response.json()["partner_id"]
    with Session(engine) as db:
        partner = db.get(HotelPartner, partner_id)
        hotel = db.get(Hotel, partner.hotel_id)
        assert partner.user_name == "json-partner"
        assert hotel.hotel_id not in (100, 200)
        assert hotel.hotel_token.startswith("partner:")
        assert partner.hotel_token == hotel.hotel_token
        assert db.query(Hotel).count() == db.query(HotelPartner).count() == 3
    assert response.request.url.query == b""
    assert_no_sensitive_values(response.text, registration()["password"], "password_hash")


def test_json_login_preserves_success_contract_and_partner_claims(ownership_app):
    client, engine, _ = ownership_app
    before = counts(engine)
    response = client.post("/partners/login", json=login())
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"partner_id", "access_token", "token_type"}
    assert body["partner_id"] == 20 and body["token_type"] == "bearer"
    claims = auth.decode_access_token(HTTPAuthorizationCredentials(scheme="Bearer", credentials=body["access_token"]))
    assert (claims["sub"], claims["type"], claims["ver"]) == ("20", "partner", 0)
    assert counts(engine) == before
    assert response.request.url.query == b""
    assert_no_sensitive_values(response.text, login()["password"], "password_hash")


def test_unknown_username_and_wrong_password_have_identical_generic_401(ownership_app):
    client, engine, _ = ownership_app
    before = counts(engine)
    responses = [client.post("/partners/login", json=body) for body in (
        login(user_name="synthetic-unknown"), login(password="wrong-secret"),
    )]
    for response in responses:
        assert response.status_code == 401
        assert response.headers["www-authenticate"] == "Bearer"
        assert response.json() == {"detail": "Invalid username or password"}
        assert_no_sensitive_values(response.text, "synthetic-unknown", "eligible-partner",
                                   "password123", "wrong-secret", "test:password123")
    assert responses[0].content == responses[1].content
    assert counts(engine) == before


@pytest.mark.parametrize("path", ["/partners/register", "/partners/login"])
@pytest.mark.parametrize("transport", ["query", "form"])
def test_non_json_credentials_cannot_register_or_authenticate(ownership_app, path, transport):
    client, engine, _ = ownership_app
    before = counts(engine)
    body = registration() if path.endswith("register") else login()
    # These intentionally outdated requests are rejected; upstream URL logging
    # still needs redaction if a caller puts credentials into its own URL.
    kwargs = {"params" if transport == "query" else "data": body}
    response = client.post(path, **kwargs)
    assert response.status_code == 422
    assert "access_token" not in response.json()
    assert counts(engine) == before
    assert_no_sensitive_values(response.text, body["password"], body["user_name"])


@pytest.mark.parametrize("path", ["/partners/register", "/partners/login"])
def test_query_credentials_do_not_fill_missing_json_fields(ownership_app, path):
    client, engine, _ = ownership_app
    before = counts(engine)
    body = registration() if path.endswith("register") else login()
    incomplete = {key: value for key, value in body.items() if key != "password"}
    response = client.post(path, params={"password": body["password"]}, json=incomplete)
    assert response.status_code == 422
    assert counts(engine) == before
    assert_no_sensitive_values(response.text, body["password"], body["user_name"])


def test_json_credentials_are_authoritative_without_query_fallback(ownership_app):
    client, engine, _ = ownership_app
    before = counts(engine)
    response = client.post("/partners/login", params=login(), json=login(password="wrong-secret"))
    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid username or password"}
    assert counts(engine) == before


@pytest.mark.parametrize("path", ["/partners/register", "/partners/login"])
def test_openapi_requires_json_body_and_has_no_credential_query_fields(ownership_app, path):
    client, _, _ = ownership_app
    operation = client.app.openapi()["paths"][path]["post"]
    assert operation["requestBody"]["required"] is True
    assert set(operation["requestBody"]["content"]) == {"application/json"}
    assert not any(param["name"] in {"user_name", "password", "hotel_token"}
                   for param in operation.get("parameters", []))


def test_json_requests_keep_credentials_out_of_urls_and_access_logs(ownership_app, caplog):
    client, engine, _ = ownership_app
    payload = registration()
    with caplog.at_level(logging.INFO, logger="httpx"):
        registered = client.post("/partners/register", json=payload)
        authenticated = client.post("/partners/login", json={
            "user_name": payload["user_name"], "password": payload["password"],
        })
    assert registered.status_code == authenticated.status_code == 200
    token = authenticated.json()["access_token"]
    with Session(engine) as db:
        password_hash = db.get(HotelPartner, registered.json()["partner_id"]).password_hash
    for response in (registered, authenticated):
        assert response.request.url.query == b""
        assert_no_sensitive_values(str(response.request.url), payload["user_name"], payload["password"], token)
    access_logs = [record for record in caplog.records if record.name == "httpx"]
    assert_no_sensitive_values(
        "\n".join(record.getMessage() for record in access_logs),
        payload["user_name"],
        payload["password"],
        password_hash,
        token,
    )
    assert_no_sensitive_values(caplog.text, payload["user_name"], payload["password"], password_hash, token)


@pytest.mark.parametrize("path", ["/partners/register", "/partners/login"])
@pytest.mark.parametrize("invalid", ["missing-field", "long-password", "non-string-password", "invalid-json"])
def test_validation_failures_do_not_echo_password_hash_or_jwt(ownership_app, path, invalid, caplog):
    client, engine, _ = ownership_app
    before = counts(engine)
    token = auth.create_access_token(20, subject_type="partner")
    password, password_hash = "body-secret", "synthetic-hash-marker"
    body = {"password": password, "password_hash": password_hash, "access_token": token}
    if invalid != "missing-field":
        body.update(registration() if path.endswith("register") else login())
        body["password"] = "overlong-secret-value" if invalid == "long-password" else {"secret": password}
    with caplog.at_level(logging.INFO, logger="httpx"):
        if invalid == "invalid-json":
            response = client.post(path, content='{"password":"body-secret",', headers={"Content-Type": "application/json"})
        else:
            response = client.post(path, json=body)
    assert response.status_code == 422
    for error in response.json()["detail"]:
        assert set(error) == {"loc", "msg", "type"}
    assert_no_sensitive_values(response.text, password, password_hash, token, "overlong-secret-value")
    assert_no_sensitive_values(caplog.text, password, password_hash, token, "overlong-secret-value")
    assert counts(engine) == before


@pytest.mark.parametrize("provided_token", ["public-property-other", "unknown-property", "legacy:100", "partner:claimed", " "])
def test_json_registration_still_rejects_public_hotel_claims(ownership_app, provided_token):
    client, engine, _ = ownership_app
    before = counts(engine)
    response = client.post("/partners/register", json=registration(hotel_token=provided_token))
    assert response.status_code == 422
    assert counts(engine) == before
    assert_no_sensitive_values(response.text, registration()["password"])
    if provided_token.strip():
        assert_no_sensitive_values(response.text, provided_token)


def test_json_login_does_not_grant_unverified_partner_booking_access(ownership_app):
    client, engine, _ = ownership_app
    before = counts(engine)
    response = client.post("/partners/login", json=login(user_name="previous-claim"))
    assert response.status_code == 200
    token = response.json()["access_token"]
    denied = client.get("/partners/check_booking/", headers={"Authorization": f"Bearer {token}"})
    assert denied.status_code == 403
    assert denied.json() == {"detail": "Booking access is not available"}
    assert_no_sensitive_values(denied.text, token, "other-customer@example.test")
    assert counts(engine) == before


def test_eligible_json_login_keeps_booking_scope_and_customer_role_boundary(ownership_app):
    client, _, _ = ownership_app
    response = client.post("/partners/login", json=login())
    assert response.status_code == 200
    token = response.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    bookings = client.get("/partners/check_booking/", headers=headers)
    assert bookings.status_code == 200
    assert len(bookings.json()) == 1
    assert bookings.json()[0]["email"] == "own-customer@example.test"
    assert_no_sensitive_values(bookings.text, "other-customer@example.test", token)
    assert client.get("/users/me", headers=headers).status_code == 401
    customer_token = auth.create_access_token(7, subject_type="user")
    assert client.get("/partners/check_booking/", headers={"Authorization": f"Bearer {customer_token}"}).status_code == 401


def test_genuine_database_failure_is_not_reported_as_invalid_credentials(ownership_app, monkeypatch):
    client, engine, _ = ownership_app
    before = counts(engine)

    class UnavailableDb:
        def query(self, *args):
            raise SQLAlchemyError("synthetic database unavailable")

    with pytest.raises(SQLAlchemyError):
        partner_service.login_partner(UnavailableDb(), PartnerLoginRequest(**login()))
    monkeypatch.setitem(client.app.dependency_overrides, get_db, lambda: UnavailableDb())
    with TestClient(client.app, raise_server_exceptions=False) as error_client:
        response = error_client.post("/partners/login", json=login())
    assert response.status_code == 500
    assert response.text == "Internal Server Error"
    assert_no_sensitive_values(response.text, login()["password"], "synthetic database unavailable")
    assert counts(engine) == before


def test_real_password_verification_keeps_success_and_generic_failure(ownership_app, monkeypatch):
    client, engine, _ = ownership_app
    hasher = PasswordHash.recommended()
    monkeypatch.setattr(partner_service, "PASSWORD_HASHER", hasher)
    with Session(engine) as db:
        db.get(HotelPartner, 20).password_hash = hasher.hash(login()["password"])
        db.commit()
    success = client.post("/partners/login", json=login())
    rejected = client.post("/partners/login", json=login(password="wrong-secret"))
    assert success.status_code == 200
    assert rejected.status_code == 401
    assert rejected.json() == {"detail": "Invalid username or password"}


def test_invalid_login_access_logs_and_failure_messages_do_not_expose_credentials(ownership_app, caplog):
    client, _, _ = ownership_app
    payload = login(password="wrong-secret")
    with caplog.at_level(logging.INFO, logger="httpx"):
        response = client.post("/partners/login", json=payload)
    assert response.status_code == 401
    assert_no_sensitive_values(response.text, payload["password"], "test:password123")
    assert_no_sensitive_values(caplog.text, payload["password"], "test:password123")
