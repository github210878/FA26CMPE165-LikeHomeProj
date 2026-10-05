from typing import Annotated

from fastapi import APIRouter, Query, Depends
from sqlalchemy.orm import Session
from app.config.database import get_db
from app.schemas.partner_schema import (
    PartnerLoginRequest,
    PartnerRegisterRequest,
    PartnerRegisterResponse,
    CheckBookingRequest,
)
from app.services import partner_service
from app.utilities.auth import get_current_partner_id

router = APIRouter(prefix="/partners", tags=["Partners"])


@router.post("/register")
def register_partner(
    partner_info: Annotated[PartnerRegisterRequest, Query()],
    db: Session = Depends(get_db),
):
    return partner_service.register_partner(db, partner_info)


@router.post("/login")
def login_partner(
    partner_info: Annotated[PartnerLoginRequest, Query()],
    db: Session = Depends(get_db),
):
    return partner_service.login_partner(db, partner_info)


@router.get("/check_booking/")
def check_booking(
    db: Session = Depends(get_db),
    partner_id: int = Depends(get_current_partner_id),
):
    return partner_service.check_booking(db, partner_id=partner_id)
