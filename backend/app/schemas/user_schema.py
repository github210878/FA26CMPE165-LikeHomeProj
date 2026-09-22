# app/schemas/user.py

from pydantic import BaseModel, EmailStr, ConfigDict, Field


class RegisterUserRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    full_name: str | None = Field(default=None, max_length=100)
    phone: str | None = Field(default=None, max_length=30)


class RegisterUserResponse(BaseModel):
    user_id: int
    email: EmailStr
    full_name: str | None = None
    phone: str | None = None


class LoginUserRequest(BaseModel):
    email: EmailStr
    password: str


class LoginUserResponse(BaseModel):
    user_id: int
    email: EmailStr
    full_name: str | None = None
    phone: str | None = None
