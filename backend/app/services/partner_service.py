from sqlalchemy.orm import Session
from uuid import uuid4
from app.models.partner_model import HotelPartner as Partner
from app.schemas.partner_schema import (
    PartnerLoginRequest,
    PartnerLoginResponse,
    PartnerRegisterRequest,
    PartnerRegisterResponse,
)
from app.models.hotel import Hotel
from app.repositories import booking_dao
from pwdlib import PasswordHash

from app.repositories import partner_dao
from app.utilities.auth import create_access_token

PASSWORD_HASHER = PasswordHash.recommended()


def register_partner(
    db: Session, partner_info: PartnerRegisterRequest
) -> PartnerRegisterResponse:
    hotel_token = partner_info.hotel_token or f"partner:{uuid4()}"
    hotel = Hotel(
        name=partner_info.hotel_name,
        hotel_token=hotel_token,
        description=partner_info.hotel_description,
        street=partner_info.hotel_street,
        city=partner_info.hotel_city,
        state=partner_info.hotel_state,
        zip_code=partner_info.hotel_zip_code,
        country=partner_info.hotel_country,
        phone=partner_info.hotel_phone,
    )

    hotel_id = booking_dao.is_hotel_in_db(db, hotel)
    if hotel_id is None:
        hotel = booking_dao.create_hotel(db, hotel)
        hotel_id = hotel.hotel_id

    new_partner = Partner(
        user_name=partner_info.user_name,
        hotel_token=hotel_token,
        password_hash=PASSWORD_HASHER.hash(partner_info.password),
        hotel_id=hotel_id,
    )

    db.add(new_partner)
    db.commit()

    return PartnerRegisterResponse(partner_id=new_partner.partner_id)


def login_partner(
    db: Session, partner_info: PartnerLoginRequest
) -> PartnerLoginResponse:
    partner = db.query(Partner).filter_by(user_name=partner_info.user_name).first()

    if not partner or not PASSWORD_HASHER.verify(
        partner_info.password, partner.password_hash
    ):
        raise ValueError("Invalid username or password")

    access_token = create_access_token(
        partner.partner_id,
        session_version=getattr(partner, "session_version", 0),
    )

    return PartnerLoginResponse(
        partner_id=partner.partner_id,
        access_token=access_token,
        token_type="bearer",
    )


def get_hotel_id_by_partner_id(db: Session, partner_id: int) -> int | None:
    return partner_dao.get_hotel_id_by_partner_id(db, partner_id)


def check_booking(db: Session, partner_id: int):
    hotel_id = get_hotel_id_by_partner_id(db, partner_id)
    bookings = partner_dao.check_booking_by_hotel_id(db, hotel_id=hotel_id)
    return bookings
