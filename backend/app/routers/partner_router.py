from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from sqlalchemy.orm import Session

from app.config.database import get_db
from app.schemas.partner_schema import (
    PartnerLoginRequest,
    PartnerRegisterRequest,
)
from app.services import partner_service
from app.utilities.auth import get_current_partner_id


class _PartnerRoute(APIRoute):
    """Keep credential input out of request-validation error responses."""

    def get_route_handler(self):
        handler = super().get_route_handler()

        async def safe_validation(request: Request):
            try:
                return await handler(request)
            except RequestValidationError as exc:
                raise HTTPException(
                    status_code=422,
                    detail=[
                        {key: error[key] for key in ("loc", "msg", "type")}
                        for error in exc.errors()
                    ],
                ) from exc

        return safe_validation


router = APIRouter(prefix="/partners", tags=["Partners"], route_class=_PartnerRoute)


@router.post("/register")
def register_partner(
    partner_info: PartnerRegisterRequest,
    db: Session = Depends(get_db),
):
    return partner_service.register_partner(db, partner_info)


@router.post("/login")
def login_partner(
    partner_info: PartnerLoginRequest,
    db: Session = Depends(get_db),
):
    return partner_service.login_partner(db, partner_info)


@router.get("/check_booking/")
def check_booking(
    db: Session = Depends(get_db),
    partner_id: int = Depends(get_current_partner_id),
):
    return partner_service.check_booking(db, partner_id=partner_id)
