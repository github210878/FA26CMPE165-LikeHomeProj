from pydantic import BaseModel, Field


class PartnerRegisterRequest(BaseModel):
    user_name: str | None = Field(default="Unknown", max_length=100)
    password: str = Field(max_length=15)
    hotel_name: str | None = Field(default="Unknown", max_length=255)
    hotel_token: str | None = Field(default=None, max_length=255)
    hotel_description: str | None = Field(default=None, max_length=5000)
    hotel_street: str | None = Field(default=None, max_length=255)
    hotel_city: str | None = Field(default=None, max_length=100)
    hotel_state: str | None = Field(default=None, max_length=100)
    hotel_zip_code: str | None = Field(default=None, max_length=20)
    hotel_country: str | None = Field(default=None, max_length=100)
    hotel_phone: str | None = Field(default=None, max_length=100)


class PartnerRegisterResponse(BaseModel):
    partner_id: int


class PartnerLoginRequest(BaseModel):
    user_name: str = Field(max_length=100)
    password: str = Field(max_length=15)


class PartnerLoginResponse(BaseModel):
    partner_id: int
    access_token: str
    token_type: str = "bearer"


class CheckBookingRequest(BaseModel):
    access_token: str


class BookingInfo(BaseModel):
    room_type_name: str | None = Field(default="Unknown", max_length=255)
    room_type_description: str | None = Field(default=None, max_length=5000)
    price_per_night: float | None = Field(default=0.0)
    full_name: str | None = Field(default="Unknown", max_length=100)
    email: str | None = Field(default="Unknown", max_length=100)
    phone: str | None = Field(default="Unknown", max_length=100)
    check_in_date: str | None = Field(default=None)
    check_out_date: str | None = Field(default=None)
