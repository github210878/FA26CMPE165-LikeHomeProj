from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.config.database import get_db
from app.schemas.user_schema import (
    RegisterUserRequest,
    RegisterUserResponse,
    LoginUserRequest,
    LoginUserResponse,
    ChangePasswordRequest,
    DeleteUserRequest,
)
from app.services import user_service
from app.utilities.auth import get_current_user_id

router = APIRouter(prefix="/users", tags=["Users"])


@router.post("/register", response_model=RegisterUserResponse, status_code=201)
def register_user(user_info: RegisterUserRequest, db: Session = Depends(get_db)):
    return user_service.register_user(user_info, db)


@router.post("/login", response_model=LoginUserResponse)
def login_user(login_info: LoginUserRequest, db: Session = Depends(get_db)):
    return user_service.login_user(login_info, db)


@router.post("/change-password")
def change_password(
    change_password_info: ChangePasswordRequest, db: Session = Depends(get_db)
):
    return user_service.change_password(change_password_info, db)


@router.delete("/delete")
def delete_user(delete_user_info: DeleteUserRequest, db: Session = Depends(get_db)):
    return user_service.delete_user(delete_user_info, db)

@router.get("/me")
def get_current_user(
        user_id: int = Depends(get_current_user_id),
):
    return {
        "message": "Protected route accessed successfully",
        "user_id": user_id,
    }