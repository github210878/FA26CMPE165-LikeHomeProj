import math
import logging
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

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
    HotelRevalidationRequest,
    HotelRevalidationResponse,
)
from app.config.constants import Constants

logger = logging.getLogger(__name__)
CENT = Decimal("0.01")


def _provider_money(value: object) -> Decimal | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return amount if amount.is_finite() and 0 < amount <= Decimal("99999999.99") else None


def _extracted(rate: object, field: str) -> Decimal | None:
    return _provider_money(rate.get(field)) if isinstance(rate, dict) else None


def _cents(amount: Decimal) -> Decimal:
    return amount.quantize(CENT, rounding=ROUND_HALF_UP)


def revalidate_hotel(info: HotelRevalidationRequest) -> HotelRevalidationResponse:
    """Quote the cheapest eligible provider listing for this property and stay.

    A property card selects no room. We therefore use a documented property-level
    rule and never claim that a specific room or supplier reservation was held.
    """
    params = {
        "q": info.q,
        "property_token": info.property_token,
        "check_in_date": info.check_in_date.isoformat(),
        "check_out_date": info.check_out_date.isoformat(),
        "adults": info.adults,
        "children": info.children,
        "currency": info.currency,
        "gl": info.gl,
        "hl": info.hl,
    }
    try:
        details = serpapi_client.search_google_hotels(params)
    except SerpApiConfigError as exc:
        raise HTTPException(status_code=500, detail="Hotel rate service is not configured") from exc
    except SerpApiTimeoutError as exc:
        raise HTTPException(status_code=504, detail="Hotel rate service timed out") from exc
    except (SerpApiRequestError, SerpApiResponseError) as exc:
        raise HTTPException(status_code=502, detail="Hotel rate service is temporarily unavailable") from exc

    if not isinstance(details, dict):
        raise HTTPException(status_code=502, detail="Hotel rate service returned an invalid response")
    hotel_name = _optional_text(details.get("name"))
    if details.get("property_token") != info.property_token or not hotel_name or len(hotel_name) > 255:
        raise HTTPException(status_code=409, detail="Property could not be verified; search again")

    offers = details.get("prices")
    if not isinstance(offers, list):
        raise HTTPException(status_code=409, detail="No usable rate for this stay; search again")

    nights = (info.check_out_date - info.check_in_date).days
    party_size = info.adults + info.children
    candidates = []
    for offer in offers:
        if not isinstance(offer, dict):
            continue
        source = _optional_text(offer.get("source"))
        capacity = offer.get("num_guests")
        nightly = _extracted(offer.get("rate_per_night"), "extracted_before_taxes_fees")
        total = _extracted(offer.get("total_rate"), "extracted_before_taxes_fees")
        total_with_fees = _extracted(offer.get("total_rate"), "extracted_lowest")
        if (
            not source or isinstance(capacity, bool) or not isinstance(capacity, int)
            or capacity < party_size or nightly is None or total is None
        ):
            continue
        # Google rounds nightly display values. Large disagreement means the
        # listing cannot safely support the existing nightly/stay contract.
        if abs(nightly * nights - total) > Decimal(nights):
            continue
        if total_with_fees is not None and total_with_fees < total:
            continue
        candidates.append((total, source, capacity, total_with_fees))

    if not candidates:
        raise HTTPException(status_code=409, detail="No usable rate for this stay; search again")

    base_total, source, capacity, provider_total = min(candidates, key=lambda row: (row[0], row[1]))
    base_total = _cents(base_total)
    nightly_average = _cents(base_total / nights)
    reservation_total = _cents(base_total * Decimal(str(Constants.SERVICE_FEE)))
    payment_amount = _cents(reservation_total * Decimal(str(Constants.SALE_TAX)))
    if max(nightly_average, reservation_total, payment_amount) > Decimal("99999999.99"):
        raise HTTPException(status_code=409, detail="No usable rate for this stay; search again")
    displayed = info.displayed_price_per_night
    changed = (
        None if displayed is None or provider_total is None
        else _cents(Decimal(str(displayed))) != _cents(provider_total / nights)
    )
    return HotelRevalidationResponse(
        property_token=info.property_token,
        hotel_name=hotel_name,
        check_in_date=info.check_in_date,
        check_out_date=info.check_out_date,
        adults=info.adults,
        children=info.children,
        currency=info.currency,
        number_of_nights=nights,
        availability="available",
        rate_rule="lowest_eligible_provider_base_total",
        source=source,
        guest_capacity=capacity,
        current_price_per_night=float(nightly_average),
        provider_base_total=float(_cents(base_total)),
        provider_total_with_taxes_fees=float(_cents(provider_total)) if provider_total is not None else None,
        likehome_reservation_total=float(reservation_total),
        likehome_payment_amount=float(payment_amount),
        price_changed=changed,
    )


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


def _next_page_token(response: object) -> str | None:
    """Read pagination tokens from both current and SerpApi response shapes."""
    if not isinstance(response, dict):
        return None
    direct = _optional_text(response.get("next_page_token"))
    if direct:
        return direct
    pagination = response.get("serpapi_pagination")
    return _optional_text(pagination.get("next_page_token")) if isinstance(pagination, dict) else None


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
        next_page_token=_next_page_token(raw_response),
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
