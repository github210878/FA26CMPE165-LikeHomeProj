"""Partner ownership boundaries using synthetic SQLite data and in-process HTTP."""

from datetime import date
from uuid import uuid4

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.config.database import Base, get_db
from app.models.hotel import Hotel
from app.models.partner_model import HotelPartner
from app.models.reservation import Reservation
from app.models.room_type import RoomType
from app.models.user import User
from app.repositories import partner_dao
from app.routers.partner_router import router as partner_router
from app.routers.user_router import router as user_router
from app.schemas.partner_schema import PartnerRegisterRequest
from app.services import partner_service
from app.utilities import auth


@pytest.fixture
def ownership_app(monkeypatch):
    monkeypatch.setattr(auth, "JWT_SECRET_KEY", "synthetic-ownership-test-secret-at-least-32")
    monkeypatch.setattr(auth, "JWT_ALGORITHM", "HS256")
    # Password hashing is outside this increment; JWT and ownership checks are real.
    monkeypatch.setattr(partner_service.PASSWORD_HASHER, "hash", lambda p: f"test:{p}")
    monkeypatch.setattr(partner_service.PASSWORD_HASHER, "verify", lambda p, h: h == f"test:{p}")
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    internal_token = f"partner:{uuid4()}"
    with Session(engine) as db:
        db.add_all([
            User(user_id=7, email="other-customer@example.test", full_name="Other Customer",
                 password_hash="synthetic", phone="555-0107"),
            User(user_id=8, email="own-customer@example.test", full_name="Own Customer",
                 password_hash="synthetic", phone="555-0108"),
            Hotel(hotel_id=100, hotel_token="public-property-other", name="Other Hotel"),
            Hotel(hotel_id=200, hotel_token=internal_token, name="Internal Hotel"),
        ])
        db.flush()
        db.add_all([
            RoomType(room_type_id=101, hotel_id=100, type_name="Other Room", price_per_night=100),
            RoomType(room_type_id=201, hotel_id=200, type_name="Own Room", price_per_night=150),
            HotelPartner(partner_id=20, user_name="eligible-partner", password_hash="test:password123",
                         hotel_token=internal_token, hotel_id=200),
            # Emulate a pre-fix public claim, without using the registration service.
            HotelPartner(partner_id=30, user_name="previous-claim", password_hash="test:password123",
                         hotel_token="public-property-other", hotel_id=100),
        ])
        db.flush()
        db.add_all([
            Reservation(reservation_id=102, user_id=7, room_type_id=101, total_price=210,
                        check_in_date=date(2030, 11, 1), check_out_date=date(2030, 11, 3)),
            Reservation(reservation_id=202, user_id=8, room_type_id=201, total_price=315,
                        check_in_date=date(2030, 11, 1), check_out_date=date(2030, 11, 3)),
        ])
        db.commit()

    app = FastAPI()
    app.include_router(partner_router)
    app.include_router(user_router)

    def isolated_db():
        with Session(engine) as db:
            yield db

    app.dependency_overrides[get_db] = isolated_db
    with TestClient(app) as client:
        yield client, engine, internal_token
    engine.dispose()


def partner_headers(partner_id):
    return {"Authorization": f"Bearer {auth.create_access_token(partner_id, subject_type='partner')}"}


def registration_params(**overrides):
    return {
        "user_name": "new-partner", "password": "password123", "hotel_name": "New Hotel",
        **overrides,
    }


@pytest.mark.parametrize("token", [
    "public-property-other", "unknown-property", "legacy:100", "partner:claimed", " ",
])
def test_public_registration_rejects_supplied_tokens_without_writes(ownership_app, token):
    client, engine, _ = ownership_app
    response = client.post("/partners/register", json=registration_params(hotel_token=token))
    assert response.status_code == 422
    assert "other-customer@" not in response.text
    assert "Other Hotel" not in response.text
    with Session(engine) as db:
        assert db.query(Hotel).count() == 2
        assert db.query(HotelPartner).count() == 2
        assert db.get(Hotel, 100).hotel_token == "public-property-other"
        assert db.get(HotelPartner, 30).hotel_id == 100


def test_registration_rejection_does_not_disclose_property_existence(ownership_app):
    client, _, _ = ownership_app
    messages = []
    for token in ("public-property-other", "unknown-property"):
        response = client.post("/partners/register", json=registration_params(hotel_token=token))
        assert response.status_code == 422
        messages.append([(e["type"], e["msg"]) for e in response.json()["detail"]])
    assert messages[0] == messages[1]


def test_attacker_cannot_claim_or_read_existing_hotel(ownership_app):
    client, engine, _ = ownership_app
    rejected = client.post("/partners/register", json=registration_params(hotel_token="public-property-other"))
    assert rejected.status_code == 422
    # A normal registration cannot attach to an existing hotel even with the same name.
    created = client.post("/partners/register", json=registration_params(hotel_name="Other Hotel"))
    assert created.status_code == 200
    partner_id = created.json()["partner_id"]
    response = client.get("/partners/check_booking/", headers=partner_headers(partner_id))
    assert response.status_code == 200
    assert response.json() == []
    with Session(engine) as db:
        assert db.get(HotelPartner, partner_id).hotel_id != 100
        assert db.get(Reservation, 102).user_id == 7


def test_preexisting_external_claim_can_authenticate_but_cannot_read_bookings(ownership_app):
    client, engine, _ = ownership_app
    login = client.post("/partners/login", json={"user_name": "previous-claim", "password": "password123"})
    assert login.status_code == 200
    response = client.get("/partners/check_booking/", headers={"Authorization": f"Bearer {login.json()['access_token']}"})
    assert response.status_code == 403
    assert response.json() == {"detail": "Booking access is not available"}
    assert "other-customer@" not in response.text
    with Session(engine) as db:
        # No cleanup, unlinking, deletion, or relationship rewrite.
        assert db.get(HotelPartner, 30).hotel_id == 100
        assert db.get(HotelPartner, 30).hotel_token == "public-property-other"
        assert db.get(Reservation, 102).room_type_id == 101


@pytest.mark.parametrize("token", [
    "legacy:200", "partner:not-a-uuid",
    "partner:00000000-0000-0000-0000-000000000000",
    "partner:00000000-0000-1000-8000-000000000001",
])
def test_unproven_internal_or_legacy_tokens_fail_closed(ownership_app, token):
    client, engine, _ = ownership_app
    with Session(engine) as db:
        db.get(HotelPartner, 20).hotel_token = token
        db.get(Hotel, 200).hotel_token = token
        db.commit()
    response = client.get("/partners/check_booking/", headers=partner_headers(20))
    assert response.status_code == 403
    assert response.json() == {"detail": "Booking access is not available"}


def test_token_mismatch_cannot_authorize_a_different_hotel(ownership_app):
    client, engine, internal_token = ownership_app
    with Session(engine) as db:
        db.get(HotelPartner, 20).hotel_id = 100
        db.commit()
    response = client.get("/partners/check_booking/", headers=partner_headers(20))
    assert response.status_code == 403
    assert internal_token not in response.text
    assert "Other Hotel" not in response.text


@pytest.mark.parametrize("second_token_matches", [True, False])
def test_shared_hotel_association_denies_sensitive_access_for_both_partners(ownership_app, second_token_matches):
    client, engine, internal_token = ownership_app
    with Session(engine) as db:
        db.add(HotelPartner(partner_id=40, user_name="ambiguous-partner", password_hash="test:password123",
                            hotel_token=internal_token if second_token_matches else "unknown", hotel_id=200))
        db.commit()
    for partner_id in (20, 40):
        response = client.get("/partners/check_booking/", headers=partner_headers(partner_id))
        assert response.status_code == 403
    with Session(engine) as db:
        assert db.query(HotelPartner).filter_by(hotel_id=200).count() == 2


def test_denied_access_never_queries_customer_or_reservation_data(ownership_app):
    client, engine, _ = ownership_app
    statements = []

    def record(_conn, _cursor, statement, _parameters, _context, _many):
        statements.append(statement.lower())

    event.listen(engine, "before_cursor_execute", record)
    try:
        response = client.get("/partners/check_booking/", headers=partner_headers(30))
    finally:
        event.remove(engine, "before_cursor_execute", record)
    assert response.status_code == 403
    assert not any("reservations" in s or "users." in s for s in statements)


def test_new_registration_login_and_own_eligible_hotel_access(ownership_app):
    client, engine, _ = ownership_app
    response = client.post("/partners/register", json=registration_params())
    assert response.status_code == 200
    partner_id = response.json()["partner_id"]
    with Session(engine) as db:
        partner = db.get(HotelPartner, partner_id)
        hotel = db.get(Hotel, partner.hotel_id)
        assert partner.hotel_token == hotel.hotel_token
        assert hotel.hotel_token.startswith("partner:")
        assert hotel.hotel_id not in (100, 200)
        db.add(RoomType(room_type_id=301, hotel_id=hotel.hotel_id, type_name="New Own Room", price_per_night=120))
        db.flush()
        db.add(Reservation(reservation_id=302, user_id=8, room_type_id=301, total_price=252,
                           check_in_date=date(2030, 12, 1), check_out_date=date(2030, 12, 3)))
        db.commit()
    login = client.post("/partners/login", json={"user_name": "new-partner", "password": "password123"})
    assert login.status_code == 200
    claims = auth.decode_access_token(HTTPAuthorizationCredentials(scheme="Bearer", credentials=login.json()["access_token"]))
    assert claims["type"] == "partner"
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    bookings = client.get("/partners/check_booking/", headers=headers)
    assert bookings.status_code == 200
    assert len(bookings.json()) == 1
    assert bookings.json()[0]["room_type_name"] == "New Own Room"
    assert bookings.json()[0]["email"] == "own-customer@example.test"
    assert "other-customer@" not in bookings.text
    assert client.get("/users/me", headers=headers).status_code == 401


def test_preexisting_server_generated_hotel_still_has_scoped_access(ownership_app):
    client, _, _ = ownership_app
    response = client.get("/partners/check_booking/", headers=partner_headers(20))
    assert response.status_code == 200
    assert len(response.json()) == 1
    assert response.json()[0]["email"] == "own-customer@example.test"
    assert "other-customer@" not in response.text


def test_customer_authentication_and_role_separation_are_unchanged(ownership_app):
    client, _, _ = ownership_app
    headers = {"Authorization": f"Bearer {auth.create_access_token(7, subject_type='user')}"}
    response = client.get("/users/me", headers=headers)
    assert response.status_code == 200
    assert response.json()["user_id"] == 7
    assert client.get("/partners/check_booking/", headers=headers).status_code == 401
    assert client.get("/partners/check_booking/").status_code == 401


def test_registration_service_rejects_bypassed_schema_without_touching_db():
    request = PartnerRegisterRequest.model_construct(**registration_params(hotel_token="public-property-other"))
    with pytest.raises(HTTPException) as error:
        partner_service.register_partner(object(), request)
    assert error.value.status_code == 422


def test_generated_token_collision_never_reuses_an_existing_hotel(ownership_app, monkeypatch):
    _, engine, internal_token = ownership_app
    monkeypatch.setattr(partner_service, "uuid4", lambda: internal_token.removeprefix("partner:"))
    with Session(engine) as db:
        with pytest.raises(HTTPException) as error:
            partner_service.register_partner(db, PartnerRegisterRequest(**registration_params()))
        assert error.value.status_code == 500
        assert db.query(Hotel).count() == 2
        assert db.query(HotelPartner).count() == 2
        assert db.get(HotelPartner, 20).hotel_id == 200


def test_partner_insert_failure_rolls_back_the_new_hotel(ownership_app, monkeypatch):
    _, engine, _ = ownership_app
    with Session(engine) as db:
        original_flush = db.flush
        calls = 0

        def fail_partner_flush(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise SQLAlchemyError("synthetic insert failure")
            return original_flush(*args, **kwargs)

        monkeypatch.setattr(db, "flush", fail_partner_flush)
        with pytest.raises(HTTPException) as error:
            partner_service.register_partner(db, PartnerRegisterRequest(**registration_params()))
        assert error.value.status_code == 500
        assert "synthetic" not in error.value.detail
        monkeypatch.setattr(db, "flush", original_flush)
        assert db.query(Hotel).count() == 2
        assert db.query(HotelPartner).count() == 2


def test_missing_hotel_relationship_is_denied(ownership_app):
    client, engine, _ = ownership_app
    with Session(engine) as db:
        db.get(HotelPartner, 20).hotel_id = 999
        db.commit()
    assert client.get("/partners/check_booking/", headers=partner_headers(20)).status_code == 403


def test_dao_does_not_return_an_external_claim_as_eligible(ownership_app):
    _, engine, _ = ownership_app
    with Session(engine) as db:
        assert partner_dao.get_hotel_id_by_partner_id(db, 30) is None
        assert partner_dao.get_hotel_id_by_partner_id(db, 20) == 200
        assert partner_dao.get_hotel_id_by_partner_id(db, 999) is None
