from pydantic import BaseModel, EmailStr, ConfigDict, Field
from datetime import date


class BookingRequest(BaseModel):
    hotel_name: str | None = Field(default="Unknown", max_length=5000)
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


class BookingResponse(BaseModel):
    user_id: int
    hotel_id: int
    room_type_id: int
    reservation_id: int
    payment_id: int
