import os
import jwt
from datetime import datetime, timedelta, timezone
from sqlalchemy.orm import Session
from app.config.database import get_db
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt.exceptions import InvalidTokenError
from dotenv import load_dotenv
from app.repositories import user_dao

load_dotenv()

JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY")
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
JWT_EXPIRE_MINUTES = int(os.getenv("JWT_EXPIRE_MINUTES", "60"))

bearer_scheme = HTTPBearer()


def create_access_token(user_id: int) -> str:
    """Create an access token for a logged-in user."""

    if not JWT_SECRET_KEY:
        raise RuntimeError("JWT_SECRET_KEY is not configured")

    expiration = datetime.now(timezone.utc) + timedelta(minutes=JWT_EXPIRE_MINUTES)

    payload = {
        "sub": str(user_id),
        "exp": expiration,
    }

    return jwt.encode(
        payload,
        JWT_SECRET_KEY,
        algorithm=JWT_ALGORITHM,
    )


def verify_access_token(
    credentials: HTTPAuthorizationCredentials,
) -> int:
    """Verify a Bearer token and return the authenticated user's ID."""

    if not JWT_SECRET_KEY:
        raise RuntimeError("JWT_SECRET_KEY is not configured")

    token = credentials.credentials

    try:
        payload = jwt.decode(
            token,
            JWT_SECRET_KEY,
            algorithms=[JWT_ALGORITHM],
        )

        user_id = payload.get("sub")

        if user_id is None:
            raise HTTPException(
                status_code=401,
                detail="Invalid authentication token",
            )

        return int(user_id)

    except (InvalidTokenError, ValueError):
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired authentication token",
        )


def get_current_user_id(
    db: Session = Depends(get_db),
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
) -> int:
    """FastAPI dependency that protects routes with Bearer authentication."""

    verified_user = user_dao.verify_user(db, user_id=verify_access_token(credentials))
    if not verified_user:
        raise HTTPException(
            status_code=401,
            detail="User cannot be verified",
        )
    return verify_access_token(credentials)
