"""Registration HTTP behavior against a disposable database."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker

from app.config.database import get_db
from app.models.user import User
from app.models.user_balance import UserBalance
from app.repositories import user_dao
from app.routers.user_router import router
from app.utilities import auth


SIGNUP = {
    "email": "New.Person@Example.com",
    "password": "Registration123",
    "full_name": "New Person",
    "phone": "555-0100",
}


@pytest.fixture
def registration_db(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'registration.sqlite3'}")
    User.__table__.create(engine)
    UserBalance.__table__.create(engine)
    try:
        yield engine, sessionmaker(bind=engine, autoflush=False)
    finally:
        engine.dispose()


@pytest.fixture
def client(registration_db, monkeypatch):
    _, sessions = registration_db
    app = FastAPI()
    app.include_router(router)

    def get_isolated_db():
        with sessions() as db:
            yield db

    app.dependency_overrides[get_db] = get_isolated_db
    monkeypatch.setattr(auth, "JWT_SECRET_KEY", "registration-isolated-test-signing-key")
    monkeypatch.setattr(auth, "JWT_ALGORITHM", "HS256")
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client


def assert_empty(sessions):
    with sessions() as db:
        assert db.scalars(select(User)).all() == []
        assert db.scalars(select(UserBalance)).all() == []


def assert_new_account(sessions):
    with sessions() as db:
        user = db.scalars(select(User)).one()
        balance = db.scalars(select(UserBalance)).one()
        assert user.email == SIGNUP["email"].lower()
        assert user.password_hash != SIGNUP["password"]
        assert (user.status, user.reward_points, user.session_version) == ("active", 0, 0)
        assert (balance.user_id, balance.balance) == (user.user_id, 0)
        return user.user_id


def test_signup_persists_user_and_balance_and_allows_immediate_login(client, registration_db):
    _, sessions = registration_db
    signup = client.post("/users/register", json=SIGNUP)
    assert signup.status_code == 201
    user_id = assert_new_account(sessions)
    assert signup.json() == {
        "user_id": user_id,
        "email": SIGNUP["email"].lower(),
        "full_name": SIGNUP["full_name"],
        "phone": SIGNUP["phone"],
    }

    login = client.post("/users/login", json=SIGNUP)
    assert login.status_code == 200
    assert login.json()["user_id"] == user_id
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    assert client.get("/users/me", headers=headers).json()["user_id"] == user_id

    duplicate = client.post("/users/register", json={**SIGNUP, "email": SIGNUP["email"].upper()})
    assert duplicate.status_code == 409
    assert duplicate.json() == {"detail": "Email already registered"}
    assert assert_new_account(sessions) == user_id


def test_balance_insert_failure_is_not_email_conflict_and_allows_retry(client, registration_db):
    engine, sessions = registration_db
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TRIGGER reject_balance BEFORE INSERT ON user_balances "
            "BEGIN SELECT RAISE(ABORT, 'synthetic balance failure'); END"
        )

    assert client.post("/users/register", json=SIGNUP).status_code == 500
    assert_empty(sessions)
    assert client.post("/users/login", json=SIGNUP).status_code == 401

    with engine.begin() as connection:
        connection.exec_driver_sql("DROP TRIGGER reject_balance")
    assert client.post("/users/register", json=SIGNUP).status_code == 201
    assert_new_account(sessions)


def test_failure_after_both_inserts_before_commit_rolls_back(client, registration_db):
    _, sessions = registration_db
    staged = []

    def fail_before_commit(db):
        staged.append(
            (len(db.scalars(select(User)).all()), len(db.scalars(select(UserBalance)).all()))
        )
        raise RuntimeError("synthetic failure before commit")

    event.listen(sessions, "before_commit", fail_before_commit, once=True)
    assert client.post("/users/register", json=SIGNUP).status_code == 500
    assert staged == [(1, 1)]
    assert_empty(sessions)
    assert client.post("/users/register", json=SIGNUP).status_code == 201
    assert_new_account(sessions)


def test_balance_initialization_repairs_missing_row_and_preserves_existing_value(registration_db):
    _, sessions = registration_db
    with sessions.begin() as db:
        legacy = User(email="legacy@example.com", password_hash="unused-fixture")
        funded = User(email="funded@example.com", password_hash="unused-fixture")
        db.add_all([legacy, funded])
        db.flush()
        legacy_id, funded_id = legacy.user_id, funded.user_id
        db.add(UserBalance(user_id=funded_id, balance=42.75))

    with sessions() as db:
        assert db.get(UserBalance, legacy_id) is None
        assert user_dao.create_user_balance(db, legacy_id).balance == 0
        assert user_dao.create_user_balance(db, legacy_id).balance == 0
        assert user_dao.create_user_balance(db, funded_id).balance == 42.75
        db.rollback()

    with sessions.begin() as db:
        assert db.get(UserBalance, legacy_id) is None
        user_dao.create_user_balance(db, legacy_id)
        user_dao.create_user_balance(db, funded_id)

    with sessions() as db:
        assert db.get(UserBalance, legacy_id).balance == 0
        assert db.get(UserBalance, funded_id).balance == 42.75
        assert len(db.scalars(select(UserBalance)).all()) == 2


@pytest.mark.parametrize("invalid", [{"email": "invalid"}, {"password": "short"}])
def test_invalid_signup_does_not_persist(client, registration_db, invalid):
    _, sessions = registration_db
    assert client.post("/users/register", json={**SIGNUP, **invalid}).status_code == 422
    assert_empty(sessions)


def test_concurrent_signups_conflict_at_database_constraint(client, registration_db, monkeypatch):
    _, sessions = registration_db
    read_both = Barrier(2)
    original = user_dao.get_user_by_email

    def synchronize_empty_lookup(db, email):
        user = original(db, email)
        assert user is None
        read_both.wait(timeout=10)
        return user

    monkeypatch.setattr(user_dao, "get_user_by_email", synchronize_empty_lookup)
    with ThreadPoolExecutor(max_workers=2) as pool:
        requests = [pool.submit(client.post, "/users/register", json=SIGNUP) for _ in range(2)]
        responses = [request.result(timeout=20) for request in requests]

    assert sorted(response.status_code for response in responses) == [201, 409]
    assert next(response for response in responses if response.status_code == 409).json() == {
        "detail": "Email already registered"
    }
    assert_new_account(sessions)
