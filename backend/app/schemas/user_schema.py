# app/schemas/user.py

from pydantic import BaseModel, EmailStr, ConfigDict, Field


class RegisterUserRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=20)
    full_name: str | None = Field(default=None, max_length=100)
    phone: str | None = Field(default=None, max_length=30)


class RegisterUserResponse(BaseModel):
    user_id: int
    email: EmailStr
    full_name: str | None = None
    phone: str | None = None


class LoginUserRequest(BaseModel):
    email: EmailStr
    password: str = Field(max_length=20)


class LoginUserResponse(BaseModel):
    user_id: int
    email: EmailStr
    full_name: str | None = None
    phone: str | None = None
    access_token: str
    token_type: str = "bearer"


class ChangePasswordRequest(BaseModel):
    user_id: int
    old_password: str = Field(max_length=20)
    new_password: str = Field(min_length=8, max_length=20)


class DeleteUserRequest(BaseModel):
    user_id: int
    password: str = Field(max_length=20)
