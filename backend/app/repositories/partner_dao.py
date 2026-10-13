from uuid import UUID
from sqlalchemy.orm import Session

from app.models.room_type import RoomType
from app.models.reservation import Reservation
from app.models.user import User
from app.schemas.partner_schema import BookingInfo
from app.models.partner_model import HotelPartner
from app.models.hotel import Hotel


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


def get_hotel_id_by_partner_id(db: Session, partner_id: int) -> int | None:
    """Return only an unambiguous, server-created internal hotel association.

    External/legacy tokens were publicly claimable before this fix and cannot
    establish ownership. The existing server-generated partner UUIDv4 namespace
    was never accepted from public callers. This is provenance for an isolated
    application hotel, not verification of ownership of a provider-listed hotel.
    """
    records = (
        db.query(HotelPartner, Hotel)
        .join(Hotel, HotelPartner.hotel_id == Hotel.hotel_id)
        .filter(HotelPartner.partner_id == partner_id)
        .first()
    )
    if records is None:
        return None
    partner, hotel = records
    token = hotel.hotel_token
    if not isinstance(token, str) or not token.startswith("partner:"):
        return None
    try:
        identifier = UUID(token.removeprefix("partner:"))
    except ValueError:
        return None
    if (
        identifier.version != 4 or token != f"partner:{identifier}"
        or partner.hotel_token != token
    ):
        return None
    # With no verified co-owner mechanism, shared associations are ambiguous.
    if db.query(HotelPartner).filter(HotelPartner.hotel_id == hotel.hotel_id).count() != 1:
        return None
    return hotel.hotel_id
