from fastapi import APIRouter, Query

from app.schemas.hotel_schema import HotelSearchRequest, HotelSearchResponse
from app.services import hotel_service

router = APIRouter(prefix="/hotels", tags=["Hotels"])


@router.get("/search", response_model=HotelSearchResponse)
def search_hotels(
    q: str = Query(..., description="Destination / search text, e.g. 'San Jose hotels'"),
    check_in_date: str = Query(..., description="YYYY-MM-DD"),
    check_out_date: str = Query(..., description="YYYY-MM-DD"),
    adults: int = Query(default=2, ge=1, le=20),
    children: int = Query(default=0, ge=0, le=20),
    currency: str = Query(default="USD"),
    gl: str = Query(default="us"),
    hl: str = Query(default="en"),
):
    search_info = HotelSearchRequest(
        q=q,
        check_in_date=check_in_date,
        check_out_date=check_out_date,
        adults=adults,
        children=children,
        currency=currency,
        gl=gl,
        hl=hl,
    )

    return hotel_service.search_hotels(search_info)
