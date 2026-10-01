from typing import Annotated

from fastapi import APIRouter, Query

from app.schemas.hotel_schema import HotelSearchRequest, HotelSearchResponse
from app.services import hotel_service

router = APIRouter(prefix="/hotels", tags=["Hotels"])


@router.get("/search", response_model=HotelSearchResponse)
def search_hotels(
    search_info: Annotated[HotelSearchRequest, Query()],
):
    return hotel_service.search_hotels(search_info)
