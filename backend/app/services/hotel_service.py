from fastapi import HTTPException

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
)


def _build_serpapi_params(search_info: HotelSearchRequest) -> dict:
    return {
        "q": search_info.q,
        "check_in_date": search_info.check_in_date,
        "check_out_date": search_info.check_out_date,
        "adults": search_info.adults,
        "children": search_info.children,
        "currency": search_info.currency,
        "gl": search_info.gl,
        "hl": search_info.hl,
    }


def _to_hotel_result(raw_property: dict) -> HotelSearchResult:
    # .get(...) everywhere on purpose: SerpApi's fields are not guaranteed to
    # be present on every property, and this endpoint should degrade
    # gracefully rather than 500 on a single odd result.
    return HotelSearchResult(
        name=raw_property.get("name"),
        property_token=raw_property.get("property_token"),
        hotel_class=raw_property.get("hotel_class"),
        overall_rating=raw_property.get("overall_rating"),
        reviews=raw_property.get("reviews"),
        rate_per_night=raw_property.get("rate_per_night"),
        total_rate=raw_property.get("total_rate"),
        amenities=raw_property.get("amenities"),
        thumbnail=raw_property.get("images", [{}])[0].get("thumbnail")
        if raw_property.get("images")
        else None,
        link=raw_property.get("link"),
        gps_coordinates=raw_property.get("gps_coordinates"),
    )


def search_hotels(search_info: HotelSearchRequest) -> HotelSearchResponse:
    params = _build_serpapi_params(search_info)

    try:
        raw_response = serpapi_client.search_google_hotels(params)
    except SerpApiConfigError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except SerpApiTimeoutError as exc:
        raise HTTPException(status_code=504, detail=str(exc)) from exc
    except (SerpApiRequestError, SerpApiResponseError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    raw_properties = raw_response.get("properties") or []
    properties = [_to_hotel_result(item) for item in raw_properties]

    return HotelSearchResponse(
        search_query=search_info.q,
        check_in_date=search_info.check_in_date,
        check_out_date=search_info.check_out_date,
        result_count=len(properties),
        properties=properties,
    )
