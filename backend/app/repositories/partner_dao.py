from sqlalchemy.orm import Session

from app.models.room_type import RoomType
from app.models.reservation import Reservation
from app.models.user import User
from app.schemas.partner_schema import BookingInfo
from app.models.partner_model import HotelPartner


def check_booking_by_hotel_id(
    db: Session,
    hotel_id: int,
) -> list[BookingInfo]:

    results = (
        db.query(
            RoomType.type_name,
            RoomType.description,
            RoomType.price_per_night,
            User.full_name,
            User.email,
            User.phone,
            Reservation.check_in_date,
            Reservation.check_out_date,
        )
        .join(
            Reservation,
            Reservation.room_type_id == RoomType.room_type_id,
        )
        .join(
            User,
            User.user_id == Reservation.user_id,
        )
        .filter(RoomType.hotel_id == hotel_id)
        .all()
    )

    return [
        BookingInfo(
            room_type_name=row.type_name,
            room_type_description=row.description,
            price_per_night=(
                float(row.price_per_night) if row.price_per_night is not None else 0.0
            ),
            full_name=row.full_name,
            email=row.email,
            phone=row.phone,
            check_in_date=(
                row.check_in_date.isoformat() if row.check_in_date else None
            ),
            check_out_date=(
                row.check_out_date.isoformat() if row.check_out_date else None
            ),
        )
        for row in results
    ]


def get_partner_by_id(db: Session, partner_id: int):
    return db.query(HotelPartner).filter(HotelPartner.partner_id == partner_id).first()


def get_hotel_id_by_partner_id(db: Session, partner_id: int):
    partner = get_partner_by_id(db, partner_id)
    if partner:
        return partner.hotel_id
    return None
