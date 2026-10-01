import re
from datetime import date

from pydantic import BaseModel, Field, ValidationInfo, field_validator


class HotelSearchRequest(BaseModel):
    q: str = Field(..., description="Destination / search text, e.g. 'San Jose hotels'")
    check_in_date: str = Field(..., description="YYYY-MM-DD; today or later")
    check_out_date: str = Field(..., description="YYYY-MM-DD; after check-in")
    adults: int = Field(default=2, ge=1, le=20)
    children: int = Field(default=0, ge=0, le=20)
    currency: str = Field(default="USD", max_length=10)
    gl: str = Field(default="us", max_length=5, description="Country code for SerpApi")
    hl: str = Field(default="en", max_length=5, description="Language code for SerpApi")

    @field_validator("check_in_date", "check_out_date")
    @classmethod
    def validate_search_date(cls, value: str, info: ValidationInfo) -> str:
        if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
            raise ValueError("Date must be a valid date in YYYY-MM-DD format")
        try:
            parsed = date.fromisoformat(value)
        except ValueError:
            raise ValueError("Date must be a valid date in YYYY-MM-DD format") from None

        if info.field_name == "check_in_date" and parsed < date.today():
            raise ValueError("Check-in date cannot be in the past")
        check_in = info.data.get("check_in_date")
        if info.field_name == "check_out_date" and check_in is not None:
            if parsed <= date.fromisoformat(check_in):
                raise ValueError("Check-out date must be after check-in date")
        return value

    @field_validator("adults", "children", mode="before")
    @classmethod
    def validate_guest_count(cls, value: object) -> object:
        if isinstance(value, bool):
            raise ValueError("Guest counts must be whole numbers")
        if isinstance(value, str):
            value = value.strip()
            if not re.fullmatch(r"[+-]?[0-9]+", value):
                raise ValueError("Guest counts must be whole numbers")
        return value


class HotelRate(BaseModel):
    lowest: str | None = None
    extracted_lowest: float | None = None
    before_taxes_fees: str | None = None
    extracted_before_taxes_fees: float | None = None


class HotelSearchResult(BaseModel):
    """A SerpApi property mapped into LikeHome's search response."""

    name: str | None = None
    property_token: str | None = None
    price_per_night: float | None = Field(
        default=None, description="Lowest nightly rate in the requested currency"
    )
    rating: float | None = Field(default=None, description="Overall rating from 0 to 5")
    amenities: list[str] | None = None

    # Keep the existing SerpApi-shaped fields for current search consumers.
    hotel_class: str | None = None
    overall_rating: float | None = None
    reviews: int | None = None
    rate_per_night: HotelRate | None = None
    total_rate: HotelRate | None = None
    thumbnail: str | None = None
    link: str | None = None
    gps_coordinates: dict | None = None


class HotelSearchResponse(BaseModel):
    search_query: str
    check_in_date: str
    check_out_date: str
    result_count: int
    properties: list[HotelSearchResult]
