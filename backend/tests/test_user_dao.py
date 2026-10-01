"""Tests for user persistence operations that affect authentication state."""

from types import SimpleNamespace

from app.repositories import user_dao


class FakeQuery:
    def __init__(self, result):
        self.result = result

    def filter(self, *_conditions):
        return self

    def first(self):
        return self.result


class FakeSession:
    def __init__(self, user):
        self.user = user

    def query(self, *_models):
        return FakeQuery(self.user)

    def commit(self):
        pass

    def refresh(self, _entity):
        pass


def make_user():
    return SimpleNamespace(
        user_id=7,
        password_hash="old-hash",
        status="active",
        session_version=0,
    )


def test_delete_user_soft_deletes_and_invalidates_sessions():
    user = make_user()

    result = user_dao.delete_user(FakeSession(user), user_id=7)

    assert result is user
    assert user.status == "deleted"
    assert user.session_version == 1


def test_password_update_invalidates_existing_sessions():
    user = make_user()

    result = user_dao.update_user_password(
        FakeSession(user),
        user_id=7,
        new_password_hash="new-hash",
    )

    assert result is user
    assert user.password_hash == "new-hash"
    assert user.session_version == 1


def test_logout_invalidates_existing_sessions():
    user = make_user()

    result = user_dao.invalidate_user_sessions(FakeSession(user), user_id=7)

    assert result is user
    assert user.session_version == 1
