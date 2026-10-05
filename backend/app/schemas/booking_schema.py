from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from datetime import date
from typing import Literal


class BookingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hotel_name: str | None = Field(default=None, min_length=1, max_length=255)
    hotel_token: str = Field(min_length=1, max_length=255)
    q: str = Field(min_length=1, max_length=255)
    adults: int = Field(default=2, ge=1, le=20)
    children: int = Field(default=0, ge=0, le=20)
    currency: Literal["USD"] = "USD"
    gl: Literal["us"] = "us"
    hl: Literal["en"] = "en"
    hotel_description: str | None = Field(default=None, max_length=5000)
    hotel_street: str | None = Field(default=None, max_length=255)
    hotel_city: str | None = Field(default=None, max_length=100)
    hotel_state: str | None = Field(default=None, max_length=100)
    hotel_zip_code: str | None = Field(default=None, max_length=20)
    hotel_country: str | None = Field(default=None, max_length=100)
    hotel_phone: str | None = Field(default=None, max_length=100)
    check_in_date: date
    check_out_date: date
    room_type_name: str | None = Field(default=None, min_length=1, max_length=100)
    room_type_description: str | None = Field(default=None, max_length=500)
    price_per_night: float = Field(
        gt=0, le=99999999.99, allow_inf_nan=False,
        description="Accepted revalidation base nightly quote; compared with provider, never authoritative.",
    )
    accepted_payment_amount: float = Field(
        gt=0, le=99999999.99, allow_inf_nan=False,
        description="User-accepted LikeHome amount from revalidation; compared with the fresh provider-derived quote.",
    )

    @field_validator("q")
    @classmethod
    def require_destination(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("A destination is required")
        return value

    @field_validator("hotel_token")
    @classmethod
    def require_real_property_token(cls, value: str) -> str:
        token = value.strip()
        if not token or token.startswith(("legacy:", "partner:")):
            raise ValueError("A SerpApi property token is required")
        return token

    @model_validator(mode="after")
    def checkout_after_checkin(self) -> "BookingRequest":
        if self.check_in_date < date.today():
            raise ValueError("check_in_date cannot be in the past")
        if self.check_out_date <= self.check_in_date:
            raise ValueError("check_out_date must be after check_in_date")
        return self


class BookingResponse(BaseModel):
    user_id: int
    hotel_id: int
    room_type_id: int
    reservation_id: int
    payment_id: int


class CancellationResponse(BaseModel):
    reservation_id: int
    status: Literal["cancelled"]
    booking_payment_id: int
    booking_payment_status: Literal["refunded"]
    cancellation_payment_id: int
    cancellation_amount: float
    cancellation_payment_status: Literal["pending"]
