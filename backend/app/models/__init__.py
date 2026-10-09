"""Register change-ledger tables and their existing FK targets on import."""

from app.models.hotel import Hotel
from app.models.payment import Payment
from app.models.reservation import Reservation
from app.models.room_type import RoomType
from app.models.user import User
from app.models.reservation_change_event import ReservationChangeEvent
from app.models.reservation_change_adjustment import ReservationChangeAdjustment

__all__ = [
    "Hotel", "Payment", "Reservation", "RoomType", "User",
    "ReservationChangeEvent", "ReservationChangeAdjustment",
]
