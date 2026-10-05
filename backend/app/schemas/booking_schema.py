from pydantic import BaseModel, EmailStr, ConfigDict, Field, field_validator
from datetime import date
from typing import Literal


class BookingRequest(BaseModel):
    hotel_name: str = Field(min_length=1, max_length=255)
    hotel_token: str = Field(min_length=1, max_length=255)
    hotel_description: str | None = Field(default=None, max_length=5000)
    hotel_street: str | None = Field(default=None, max_length=255)
    hotel_city: str | None = Field(default=None, max_length=100)
    hotel_state: str | None = Field(default=None, max_length=100)
    hotel_zip_code: str | None = Field(default=None, max_length=20)
    hotel_country: str | None = Field(default=None, max_length=100)
    hotel_phone: str | None = Field(default=None, max_length=100)
    check_in_date: date
    check_out_date: date
    room_type_name: str | None = Field(default=None, max_length=100)
    room_type_description: str | None = Field(default=None, max_length=500)
    price_per_night: float

    @field_validator("hotel_token")
    @classmethod
    def require_real_property_token(cls, value: str) -> str:
        token = value.strip()
        if not token or token.startswith(("legacy:", "partner:")):
            raise ValueError("A SerpApi property token is required")
        return token


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
