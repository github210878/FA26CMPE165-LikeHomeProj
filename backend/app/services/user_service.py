from fastapi import HTTPException
from sqlalchemy.orm import Session
from pwdlib import PasswordHash

from app.repositories import user_dao
from app.schemas.user_schema import (
    RegisterUserRequest,
    RegisterUserResponse,
    LoginUserRequest,
    LoginUserResponse,
)

PASSWORD_HASHER = PasswordHash.recommended()


def register_user(user_info: RegisterUserRequest, db: Session):
    email = user_info.email.lower()
    existing_user = user_dao.get_user_by_email(db=db, email=email)

    if existing_user:
        raise HTTPException(status_code=409, detail="Email already registered")

    new_user = user_dao.create_user(
        db=db,
        email=email,
        password_hash=PASSWORD_HASHER.hash(user_info.password),
        full_name=user_info.full_name,
        phone=user_info.phone,
    )

    return RegisterUserResponse(
        user_id=new_user.user_id,
        email=new_user.email,
        full_name=new_user.full_name,
        phone=new_user.phone,
    )


def login_user(login_info: LoginUserRequest, db: Session):
    user = user_dao.get_user_by_email(db=db, email=login_info.email.lower())

    if (
        not user
        or user.status != "active"
        or not PASSWORD_HASHER.verify(login_info.password, user.password_hash)
    ):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    return LoginUserResponse(
        user_id=user.user_id,
        email=user.email,
        full_name=user.full_name,
        phone=user.phone,
    )
