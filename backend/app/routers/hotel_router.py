from typing import Annotated

from fastapi import APIRouter, Query, Depends
from sqlalchemy.orm import Session
from app.config.database import get_db
from app.schemas.hotel_schema import HotelSearchRequest, HotelSearchResponse
from app.services import hotel_service

router = APIRouter(prefix="/hotels", tags=["Hotels"])


@router.get("/search", response_model=HotelSearchResponse)
def search_hotels(
    search_info: Annotated[HotelSearchRequest, Query()],
    db: Session = Depends(get_db),
):
    return hotel_service.search_hotels(search_info, db)


@router.get("/local_search", response_model=HotelSearchResponse)
def local_search_hotels(
    search_info: HotelSearchRequest = Depends(),
    db: Session = Depends(get_db),
):

    return hotel_service.search_hotels(
        db=db,
        search_info=search_info,
    )
