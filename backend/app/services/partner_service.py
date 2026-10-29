from uuid import uuid4

from fastapi import HTTPException
from pwdlib import PasswordHash
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.models.hotel import Hotel
from app.models.partner_model import HotelPartner as Partner
from app.repositories import booking_dao, partner_dao
from app.schemas.partner_schema import (
    PartnerLoginRequest,
    PartnerLoginResponse,
    PartnerRegisterRequest,
    PartnerRegisterResponse,
)
from app.utilities.auth import create_access_token

PASSWORD_HASHER = PasswordHash.recommended()


def register_partner(
    db: Session, partner_info: PartnerRegisterRequest
) -> PartnerRegisterResponse:
    # Also enforce this for internal callers that bypass schema validation.
    if partner_info.hotel_token is not None:
        raise HTTPException(
            status_code=422, detail="Public registration cannot use a supplied hotel token",
        )
    hotel_token = f"partner:{uuid4()}"
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

    password_hash = PASSWORD_HASHER.hash(partner_info.password)
    try:
        # Always create a new isolated hotel; even a token collision must never
        # fall back to associating this account with an existing hotel's data.
        db.add(hotel)
        db.flush()
        new_partner = Partner(
            user_name=partner_info.user_name,
            hotel_token=hotel_token,
            password_hash=password_hash,
            hotel_id=hotel.hotel_id,
        )
        db.add(new_partner)
        db.flush()
        response = PartnerRegisterResponse(partner_id=new_partner.partner_id)
        db.commit()
        return response
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(
            status_code=500, detail="Hotel registration could not be completed",
        ) from exc


def login_partner(
    db: Session, partner_info: PartnerLoginRequest
) -> PartnerLoginResponse:
    partner = db.query(Partner).filter_by(user_name=partner_info.user_name).first()

    if not partner or not PASSWORD_HASHER.verify(
        partner_info.password, partner.password_hash
    ):
        raise HTTPException(
            status_code=401, detail="Invalid username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    access_token = create_access_token(
        partner.partner_id,
        session_version=getattr(partner, "session_version", 0),
        subject_type="partner",
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
    if hotel_id is None:
        # Authenticate the account normally, but withhold customer data when
        # its hotel association lacks the server-created provenance below.
        raise HTTPException(status_code=403, detail="Booking access is not available")
    bookings = partner_dao.check_booking_by_hotel_id(db, hotel_id=hotel_id)
    return bookings
