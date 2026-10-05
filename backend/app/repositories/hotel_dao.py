from sqlalchemy.orm import Session

from app.models.cache_hotel import CacheHotel
from app.schemas.hotel_schema import (
    HotelRate,
    HotelSearchRequest,
    HotelSearchResponse,
    HotelSearchResult,
)


def get_cache_hotel_by_property_token(
    db: Session,
    property_token: str,
) -> CacheHotel | None:
    return (
        db.query(CacheHotel).filter(CacheHotel.property_token == property_token).first()
    )


def upsert_cache_hotel(
    db: Session,
    hotel_data: dict,
) -> CacheHotel:
    property_token = hotel_data.get("property_token")

    if not property_token:
        raise ValueError("property_token is required")

    try:
        cache_hotel = get_cache_hotel_by_property_token(db, property_token)
        if cache_hotel is None:
            cache_hotel = CacheHotel(**hotel_data)
            db.add(cache_hotel)
        else:
            for key, value in hotel_data.items():
                if hasattr(cache_hotel, key):
                    setattr(cache_hotel, key, value)
        db.commit()
        db.refresh(cache_hotel)
    except Exception:
        db.rollback()
        raise

    return cache_hotel


def upsert_cache_hotels(
    db: Session,
    hotels_data: list[dict],
) -> None:
    # A provider response can repeat a property. The last occurrence wins.
    by_token = {
        hotel_data["property_token"]: hotel_data
        for hotel_data in hotels_data
        if hotel_data.get("property_token")
    }
    try:
        for property_token, hotel_data in by_token.items():
            cache_hotel = get_cache_hotel_by_property_token(db, property_token)
            if cache_hotel is None:
                db.add(CacheHotel(**hotel_data))
            else:
                for key, value in hotel_data.items():
                    if hasattr(cache_hotel, key):
                        setattr(cache_hotel, key, value)
        if by_token:
            db.commit()
    except Exception:
        db.rollback()
        raise


def delete_cache_hotel(
    db: Session,
    property_token: str,
) -> bool:
    cache_hotel = get_cache_hotel_by_property_token(
        db=db,
        property_token=property_token,
    )

    if cache_hotel is None:
        return False

    db.delete(cache_hotel)
    db.commit()

    return True


def local_search_hotels(
    db: Session,
    search_info: HotelSearchRequest,
) -> HotelSearchResponse:
    query_text = search_info.q.strip()

    cache_hotels = (
        db.query(CacheHotel).filter(CacheHotel.name.ilike(f"%{query_text}%")).all()
    )

    properties = [
        HotelSearchResult(
            name=hotel.name,
            property_token=hotel.property_token,
            price_per_night=(
                float(hotel.price_per_night)
                if hotel.price_per_night is not None
                else None
            ),
            rating=(float(hotel.rating) if hotel.rating is not None else None),
            amenities=hotel.amenities,
            hotel_class=hotel.hotel_class,
            overall_rating=(
                float(hotel.overall_rating)
                if hotel.overall_rating is not None
                else None
            ),
            reviews=hotel.reviews,
            rate_per_night=(
                HotelRate(**hotel.rate_per_night) if hotel.rate_per_night else None
            ),
            total_rate=(HotelRate(**hotel.total_rate) if hotel.total_rate else None),
            thumbnail=hotel.thumbnail,
            link=hotel.link,
            gps_coordinates=hotel.gps_coordinates,
        )
        for hotel in cache_hotels
    ]

    return HotelSearchResponse(
        search_query=search_info.q,
        check_in_date=search_info.check_in_date,
        check_out_date=search_info.check_out_date,
        result_count=len(properties),
        properties=properties,
        next_page_token=None,
    )
