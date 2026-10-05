"""Isolated contract checks; never connect to the configured MySQL database."""

from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.models.cache_hotel import CacheHotel
from app.models.hotel import Hotel
from app.models.partner_model import HotelPartner
from app.repositories import booking_dao, hotel_dao, partner_dao
from app.routers import hotel_router
from app.schemas.booking_schema import BookingRequest
from app.schemas.hotel_schema import HotelSearchRequest, HotelSearchResponse
from app.schemas.partner_schema import PartnerRegisterRequest
from app.services import booking_service, hotel_service, partner_service
from app.utilities import auth


@pytest.fixture
def sqlite_session():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Hotel.__table__.create(engine)
    CacheHotel.__table__.create(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def search_request():
    return HotelSearchRequest(
        q="San Jose", check_in_date="2026-10-05", check_out_date="2026-10-08"
    )


def test_hotel_lookup_uses_token_and_unique_constraint(sqlite_session):
    first = Hotel(name="Old name", hotel_token="real-property-1")
    sqlite_session.add(first)
    sqlite_session.commit()

    assert booking_dao.is_hotel_in_db(
        sqlite_session, Hotel(name="Renamed", hotel_token="real-property-1")
    ) == first.hotel_id
    assert booking_dao.is_hotel_in_db(
        sqlite_session, Hotel(name="Old name", hotel_token="real-property-2")
    ) is None

    sqlite_session.add(Hotel(name="Duplicate", hotel_token="real-property-1"))
    with pytest.raises(IntegrityError):
        sqlite_session.commit()
    sqlite_session.rollback()
    assert sqlite_session.query(Hotel).count() == 1


def test_booking_requires_external_token_and_uses_hotel_model_field(monkeypatch):
    base = dict(
        hotel_name="Hotel A",
        q="San Jose hotels",
        check_in_date=date(2026, 10, 5),
        check_out_date=date(2026, 10, 8),
        room_type_name="Standard",
        price_per_night=100,
        accepted_payment_amount=340.20,
    )
    with pytest.raises(ValidationError):
        BookingRequest(**base)
    with pytest.raises(ValidationError):
        BookingRequest(**base, hotel_token="legacy:4")

    request = BookingRequest(**base, hotel_token="real-property-1")
    monkeypatch.setattr(
        booking_service.hotel_service,
        "revalidate_hotel",
        lambda info: SimpleNamespace(
            current_price_per_night=100,
            likehome_reservation_total=315,
            likehome_payment_amount=340.20,
            hotel_name="Hotel A",
            property_token=info.property_token,
            source="Provider A",
        ),
    )
    monkeypatch.setattr(
        booking_service.booking_dao,
        "check_if_user_booked_by_date_range",
        lambda *args: False,
    )
    captured = {}

    def capture_hotel(db, hotel):
        captured["hotel"] = hotel
        raise RuntimeError("stop before any persistence")

    monkeypatch.setattr(booking_service.booking_dao, "is_hotel_in_db", capture_hotel)
    from fastapi import HTTPException

    class FakeDb:
        def rollback(self):
            pass

    with pytest.raises(HTTPException) as error:
        booking_service.create_booking(FakeDb(), request, user_id=7)
    assert error.value.status_code == 500
    assert captured["hotel"].hotel_token == "real-property-1"


def test_search_caches_tokened_results_and_preserves_response(monkeypatch, sqlite_session):
    monkeypatch.setattr(
        hotel_service.serpapi_client,
        "search_google_hotels",
        lambda params: {
            "properties": [
                {"name": "A", "property_token": "token-a", "rate_per_night": {"extracted_lowest": 120}},
                {"name": "No token"},
            ],
            "next_page_token": "next-1",
        },
    )
    response = hotel_service.search_hotels(search_request(), sqlite_session)
    assert response.result_count == 2
    assert [p.name for p in response.properties] == ["A", "No token"]
    assert response.next_page_token == "next-1"
    assert sqlite_session.query(CacheHotel).count() == 1
    assert sqlite_session.get(CacheHotel, "token-a").price_per_night == 120

    hotel_dao.upsert_cache_hotels(sqlite_session, [
        {"property_token": "token-a", "name": "Renamed"},
        {"property_token": "token-a", "name": "Latest"},
    ])
    assert sqlite_session.query(CacheHotel).count() == 1
    assert sqlite_session.get(CacheHotel, "token-a").name == "Latest"


def test_cache_commit_failure_rolls_back_and_search_still_returns(monkeypatch, sqlite_session):
    monkeypatch.setattr(
        hotel_service.serpapi_client,
        "search_google_hotels",
        lambda params: {"properties": [{"name": "A", "property_token": "token-a"}]},
    )
    original_commit = sqlite_session.commit
    rollbacks = []

    def fail_commit():
        raise SQLAlchemyError("cache unavailable")

    original_rollback = sqlite_session.rollback

    def record_rollback():
        rollbacks.append(True)
        original_rollback()

    monkeypatch.setattr(sqlite_session, "commit", fail_commit)
    monkeypatch.setattr(sqlite_session, "rollback", record_rollback)
    response = hotel_service.search_hotels(search_request(), sqlite_session)
    assert response.result_count == 1
    assert len(rollbacks) >= 1
    monkeypatch.setattr(sqlite_session, "commit", original_commit)
    assert sqlite_session.query(CacheHotel).count() == 0


def test_local_search_router_uses_cache_service(monkeypatch):
    expected = HotelSearchResponse(
        search_query="San Jose", check_in_date="2026-10-05",
        check_out_date="2026-10-08", result_count=0, properties=[],
    )
    sentinel_db = object()
    monkeypatch.setattr(
        hotel_router.hotel_service, "local_search_hotels",
        lambda search_info, db: expected if db is sentinel_db else None,
    )
    monkeypatch.setattr(
        hotel_router.hotel_service, "search_hotels",
        lambda *args, **kwargs: pytest.fail("live search called"),
    )
    assert hotel_router.local_search_hotels(search_request(), sentinel_db) is expected


def test_partner_hotel_id_is_integer_and_internal_token_is_not_external(monkeypatch):
    monkeypatch.setattr(partner_dao, "get_hotel_id_by_partner_id", lambda db, partner_id: 17)
    assert partner_service.get_hotel_id_by_partner_id(object(), 3) == 17

    request = PartnerRegisterRequest(user_name="partner", password="password", hotel_name="A")
    with pytest.raises(ValidationError):
        PartnerRegisterRequest(user_name="partner", password="password", hotel_name="A", hotel_token="legacy:1")
    captured = {}
    monkeypatch.setattr(partner_service.booking_dao, "is_hotel_in_db", lambda db, hotel: captured.setdefault("hotel", hotel) and 17)
    monkeypatch.setattr(partner_service.PASSWORD_HASHER, "hash", lambda password: "hashed")

    class FakeDb:
        def add(self, partner):
            partner.partner_id = 3
            captured["partner"] = partner

        def commit(self):
            pass

    response = partner_service.register_partner(FakeDb(), request)
    assert response.partner_id == 3
    assert captured["hotel"].hotel_token.startswith("partner:")
    assert captured["partner"].hotel_token == captured["hotel"].hotel_token


def test_sql_contract_matches_cache_and_partner_models():
    sql = (Path(__file__).parents[1] / "database/like_home_database_init.sql").read_text()
    migration = (Path(__file__).parents[1] / "database/migrations/002_add_hotel_tokens_cache_and_partners.sql").read_text()
    for definition in ("name VARCHAR(255) NULL", "rating DECIMAL(3, 2)", "overall_rating DECIMAL(3, 2)"):
        assert definition in sql and definition in migration
    assert "legacy:" in migration
    assert "ADD CONSTRAINT uq_hotels_hotel_token UNIQUE" in migration
    assert CacheHotel.__table__.c.name.nullable
    assert CacheHotel.__table__.c.rating.type.precision == 3
    assert Hotel.__table__.c.hotel_token.unique
    assert HotelPartner.__table__.c.created_at.nullable
    assert HotelPartner.__table__.c.hotel_id.foreign_keys


def test_partner_token_must_not_authenticate_as_same_id_user(monkeypatch):
    monkeypatch.setattr(auth, "JWT_SECRET_KEY", "isolated-test-secret-32-characters")
    monkeypatch.setattr(
        auth.user_dao, "get_user_by_id",
        lambda **kwargs: SimpleNamespace(status="active", session_version=0),
    )
    partner_token = auth.create_access_token(7, subject_type="partner")
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=partner_token)
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as error:
        auth.get_current_user_id(db=object(), credentials=credentials)
    assert error.value.status_code == 401
