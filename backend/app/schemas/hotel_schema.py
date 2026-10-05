import re
from datetime import date

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator, model_validator


class HotelSearchRequest(BaseModel):
    q: str = Field(..., description="Destination / search text, e.g. 'San Jose hotels'")
    check_in_date: str = Field(..., description="YYYY-MM-DD; today or later")
    check_out_date: str = Field(..., description="YYYY-MM-DD; after check-in")
    adults: int = Field(default=2, ge=1, le=20)
    children: int = Field(default=0, ge=0, le=20)
    currency: str = Field(default="USD", max_length=10)
    gl: str = Field(default="us", max_length=5, description="Country code for SerpApi")
    hl: str = Field(default="en", max_length=5, description="Language code for SerpApi")
    next_page_token: str | None = Field(
        default=None,
        description="SerpApi token used to request the next page of hotel results",
    )

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
    next_page_token: str | None = None


class HotelRevalidationRequest(BaseModel):
    """Property-only selection and the stay context used for the search."""

    model_config = ConfigDict(extra="forbid")

    property_token: str = Field(min_length=1, max_length=255)
    q: str = Field(min_length=1, max_length=255)
    check_in_date: date
    check_out_date: date
    adults: int = Field(ge=1, le=20)
    children: int = Field(default=0, ge=0, le=20)
    currency: Literal["USD"] = "USD"
    gl: Literal["us"] = "us"
    hl: Literal["en"] = "en"
    displayed_price_per_night: float | None = Field(
        default=None, gt=0, le=99999999.99, allow_inf_nan=False,
        description="Optional search-card price used only to flag a change; never used for pricing.",
    )

    @field_validator("property_token", "q")
    @classmethod
    def nonblank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("A nonblank value is required")
        return value

    @field_validator("property_token")
    @classmethod
    def provider_token(cls, value: str) -> str:
        if value.startswith(("legacy:", "partner:")):
            raise ValueError("A SerpApi property token is required")
        return value

    @model_validator(mode="after")
    def valid_stay(self) -> "HotelRevalidationRequest":
        if self.check_in_date < date.today():
            raise ValueError("Check-in date cannot be in the past")
        if self.check_out_date <= self.check_in_date:
            raise ValueError("Check-out date must be after check-in date")
        return self


class HotelRevalidationResponse(BaseModel):
    property_token: str
    hotel_name: str
    check_in_date: date
    check_out_date: date
    adults: int
    children: int
    currency: Literal["USD"]
    number_of_nights: int
    availability: Literal["available"]
    rate_rule: Literal["lowest_eligible_provider_base_total"]
    source: str
    guest_capacity: int
    current_price_per_night: float
    provider_base_total: float
    provider_total_with_taxes_fees: float | None
    likehome_reservation_total: float
    likehome_payment_amount: float
    price_changed: bool | None
