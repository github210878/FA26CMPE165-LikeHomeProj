from fastapi import HTTPException
from sqlalchemy.orm import Session
from pwdlib import PasswordHash

from app.repositories import user_dao
from app.schemas.user_schema import RegisterUserRequest, RegisterUserResponse

PASSWORD_HASHER = PasswordHash.recommended()


def register_user(user_info: RegisterUserRequest, db: Session):
    existing_user = user_dao.get_user_by_email(db=db, email=user_info.email)

    if existing_user:
        raise HTTPException(status_code=409, detail="Email already registered")

    new_user = user_dao.create_user(
        db=db,
        email=user_info.email,
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
