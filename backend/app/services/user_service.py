from fastapi import HTTPException
from sqlalchemy.orm import Session
from pwdlib import PasswordHash

from app.repositories import user_dao
from app.utilities.auth import create_access_token
from app.schemas.user_schema import (
    RegisterUserRequest,
    RegisterUserResponse,
    LoginUserRequest,
    LoginUserResponse,
    ChangePasswordRequest,
    DeleteUserRequest,
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

    access_token = create_access_token(user.user_id)

    return LoginUserResponse(
        user_id=user.user_id,
        email=user.email,
        full_name=user.full_name,
        phone=user.phone,
        access_token=access_token,
        token_type="bearer",
    )

def change_password(change_password_info: ChangePasswordRequest, db: Session):
    user = user_dao.get_user_by_id(db=db, user_id=change_password_info.user_id)

    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if not PASSWORD_HASHER.verify(
        change_password_info.old_password, user.password_hash
    ):
        raise HTTPException(status_code=401, detail="Old password is incorrect")

    new_password_hash = PASSWORD_HASHER.hash(change_password_info.new_password)
    user_dao.update_user_password(
        db=db, user_id=user.user_id, new_password_hash=new_password_hash
    )

    return {"status": True, "message": "Password changed successfully"}


def delete_user(delete_user_info: DeleteUserRequest, db: Session):
    user = user_dao.get_user_by_id(db=db, user_id=delete_user_info.user_id)

    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if not PASSWORD_HASHER.verify(delete_user_info.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Password is incorrect")

    deleted_user = user_dao.delete_user(db=db, user_id=user.user_id)
    if not deleted_user:
        raise HTTPException(status_code=500, detail="Failed to delete user")
    elif deleted_user.status != "deleted":
        raise HTTPException(status_code=500, detail="Failed to delete user")
    else:
        return {"status": True, "message": "User deleted successfully"}
