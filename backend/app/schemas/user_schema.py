# app/schemas/user.py

from pydantic import BaseModel, EmailStr, ConfigDict


class RegisterUserRequest(BaseModel):
    email: EmailStr
    password: str
    full_name: str | None = None
    phone: str | None = None


class RegisterUserResponse(BaseModel):
    user_id: int
    email: EmailStr
    full_name: str | None = None
    phone: str | None = None
