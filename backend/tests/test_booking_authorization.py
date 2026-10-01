"""Tests that booking services preserve the authenticated user boundary."""

from app.services import booking_service


def test_get_booking_details_passes_authenticated_user_id(monkeypatch):
    captured = {}

    def get_booking_by_id(db, booking_id, user_id):
        captured.update(db=db, booking_id=booking_id, user_id=user_id)
        return {"reservation_id": booking_id}

    monkeypatch.setattr(
        booking_service.booking_dao,
        "get_booking_by_id",
        get_booking_by_id,
    )

    result = booking_service.get_booking_by_id("db", 12, 7)

    assert result == {"reservation_id": 12}
    assert captured == {"db": "db", "booking_id": 12, "user_id": 7}


def test_get_payment_details_passes_authenticated_user_id(monkeypatch):
    captured = {}

    def get_payment_by_id(db, payment_id, user_id):
        captured.update(db=db, payment_id=payment_id, user_id=user_id)
        return {"payment_id": payment_id}

    monkeypatch.setattr(
        booking_service.booking_dao,
        "get_payment_by_id",
        get_payment_by_id,
    )

    result = booking_service.get_payment_by_id("db", 15, 7)

    assert result == {"payment_id": 15}
    assert captured == {"db": "db", "payment_id": 15, "user_id": 7}