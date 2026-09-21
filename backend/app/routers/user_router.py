from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.config.database import get_db
from app.schemas.user_schema import RegisterUserRequest, RegisterUserResponse
from app.services import user_service

router = APIRouter(prefix="/users", tags=["Users"])


@router.post("/register", response_model=RegisterUserResponse, status_code=201)
def register_user(user_info: RegisterUserRequest, db: Session = Depends(get_db)):
    return user_service.register_user(user_info, db)
