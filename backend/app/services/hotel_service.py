import math
import logging

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError
from app.config.database import get_db
from app.models.cache_hotel import CacheHotel
from app.repositories import hotel_dao
from app.utilities import serpapi_client
from app.utilities.serpapi_client import (
    SerpApiConfigError,
    SerpApiTimeoutError,
    SerpApiRequestError,
    SerpApiResponseError,
)
from app.schemas.hotel_schema import (
    HotelSearchRequest,
    HotelSearchResponse,
    HotelSearchResult,
    HotelRate,
)

logger = logging.getLogger(__name__)


def _build_serpapi_params(search_info: HotelSearchRequest) -> dict:
    params = {
        "q": search_info.q,
        "check_in_date": search_info.check_in_date,
        "check_out_date": search_info.check_out_date,
        "adults": search_info.adults,
        "children": search_info.children,
        "currency": search_info.currency,
        "gl": search_info.gl,
        "hl": search_info.hl,
    }

    if search_info.next_page_token:
        params["next_page_token"] = search_info.next_page_token

    return params


def _optional_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    return value.strip() or None


def _finite_number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        number = float(value)
    except OverflowError:
        return None
    return number if math.isfinite(number) else None


def _rate(value: object) -> HotelRate | None:
    if not isinstance(value, dict):
        return None
    try:
        return HotelRate.model_validate(value)
    except ValidationError:
        return None


def _amenities(value: object) -> list[str] | None:
    if not isinstance(value, list):
        return None
    return [text for item in value if (text := _optional_text(item))]


def _thumbnail(value: object) -> str | None:
    if not isinstance(value, list):
        return None
    for image in value:
        if isinstance(image, dict):
            thumbnail = _optional_text(image.get("thumbnail"))
            if thumbnail:
                return thumbnail
    return None


def _to_hotel_result(raw_property: dict) -> HotelSearchResult:
    raw_nightly_rate = raw_property.get("rate_per_night")
    price_per_night = (
        _finite_number(raw_nightly_rate.get("extracted_lowest"))
        if isinstance(raw_nightly_rate, dict)
        else None
    )
    if price_per_night is not None and price_per_night < 0:
        price_per_night = None

    rating = _finite_number(raw_property.get("overall_rating"))
    if rating is not None and not 0 <= rating <= 5:
        rating = None

    reviews = raw_property.get("reviews")
    if isinstance(reviews, bool) or not isinstance(reviews, int) or reviews < 0:
        reviews = None

    coordinates = raw_property.get("gps_coordinates")

    return HotelSearchResult(
        name=_optional_text(raw_property.get("name")),
        property_token=_optional_text(raw_property.get("property_token")),
        price_per_night=price_per_night,
        rating=rating,
        amenities=_amenities(raw_property.get("amenities")),
        hotel_class=_optional_text(raw_property.get("hotel_class")),
        overall_rating=rating,
        reviews=reviews,
        rate_per_night=_rate(raw_nightly_rate),
        total_rate=_rate(raw_property.get("total_rate")),
        thumbnail=_thumbnail(raw_property.get("images")),
        link=_optional_text(raw_property.get("link")),
        gps_coordinates=coordinates if isinstance(coordinates, dict) else None,
    )


def search_hotels(search_info: HotelSearchRequest, db: Session) -> HotelSearchResponse:
    params = _build_serpapi_params(search_info)

    try:
        raw_response = serpapi_client.search_google_hotels(params)
    except SerpApiConfigError as exc:
        raise HTTPException(
            status_code=500,
            detail="Hotel search service is not configured",
        ) from exc
    except SerpApiTimeoutError as exc:
        raise HTTPException(
            status_code=504,
            detail="Hotel search service timed out",
        ) from exc
    except SerpApiRequestError as exc:
        raise HTTPException(
            status_code=502,
            detail="Hotel search service is temporarily unavailable",
        ) from exc
    except SerpApiResponseError as exc:
        raise HTTPException(
            status_code=502,
            detail="Hotel search service returned an error",
        ) from exc

    raw_properties = raw_response.get("properties") or []
    properties = [
        _to_hotel_result(item) for item in raw_properties if isinstance(item, dict)
    ]

    # Cache the hotel data in the database
    try:
        _cache_hotels(properties=properties, db=db)
    except SQLAlchemyError:
        # Search results remain usable when the best-effort cache is unavailable.
        db.rollback()
        logger.warning("Could not cache hotel search results", exc_info=True)

    return HotelSearchResponse(
        search_query=search_info.q,
        check_in_date=search_info.check_in_date,
        check_out_date=search_info.check_out_date,
        result_count=len(properties),
        properties=properties,
        next_page_token=_optional_text(raw_response.get("next_page_token")),
    )


def _cache_hotels(
    db: Session,
    properties: list[HotelSearchResult],
) -> None:
    hotels_data = [hotel.model_dump() for hotel in properties if hotel.property_token]

    hotel_dao.upsert_cache_hotels(
        db=db,
        hotels_data=hotels_data,
    )


def local_search_hotels(
    search_info: HotelSearchRequest,
    db: Session,
) -> HotelSearchResponse:
    return hotel_dao.local_search_hotels(db, search_info)
