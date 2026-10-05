from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Literal

import jwt
from dotenv import load_dotenv
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt.exceptions import InvalidTokenError
from sqlalchemy.orm import Session

from app.config.config import Config
from app.config.database import get_db
from app.repositories import user_dao
from app.repositories import partner_dao

load_dotenv()

# These module-level values remain patchable in unit tests while sourcing their
# defaults from the central application configuration.
JWT_SECRET_KEY = Config.JWT_SECRET_KEY
JWT_ALGORITHM = Config.JWT_ALGORITHM
JWT_EXPIRE_MINUTES = Config.JWT_EXPIRE_MINUTES

# auto_error=False lets the dependency return a consistent 401 for a missing
# or malformed Authorization header instead of FastAPI's default 403.
bearer_scheme = HTTPBearer(auto_error=False)
SubjectType = Literal["user", "partner"]
SUBJECT_TYPES = ("user", "partner")


def _authentication_error(detail: str) -> HTTPException:
    return HTTPException(
        status_code=401,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def create_access_token(
    subject_id: int, session_version: int = 0, *, subject_type: SubjectType
) -> str:
    """Create a short-lived, account-type-bound access token."""

    if not JWT_SECRET_KEY:
        raise RuntimeError("JWT_SECRET_KEY is not configured")

    if subject_id <= 0:
        raise ValueError("subject_id must be positive")

    if session_version < 0:
        raise ValueError("session_version cannot be negative")

    if subject_type not in SUBJECT_TYPES:
        raise ValueError("Invalid subject type")

    issued_at = datetime.now(timezone.utc)
    expiration = issued_at + timedelta(minutes=JWT_EXPIRE_MINUTES)

    payload = {
        "sub": str(subject_id),
        "type": subject_type,
        "ver": session_version,
        "iat": issued_at,
        "exp": expiration,
    }

    return jwt.encode(
        payload,
        JWT_SECRET_KEY,
        algorithm=JWT_ALGORITHM,
    )


def decode_access_token(
    credentials: HTTPAuthorizationCredentials | None,
) -> dict[str, Any]:
    """Validate a bearer token and return its claims.

    This function only validates cryptographic token data. It does not query or
    mutate the database; account-state checks happen in get_current_user_id.
    """

    if not JWT_SECRET_KEY:
        raise RuntimeError("JWT_SECRET_KEY is not configured")

    if credentials is None or credentials.scheme.lower() != "bearer":
        raise _authentication_error("Bearer authentication is required")

    try:
        payload = jwt.decode(
            credentials.credentials,
            JWT_SECRET_KEY,
            algorithms=[JWT_ALGORITHM],
            options={"require": ["exp", "sub", "type"]},
        )
    except InvalidTokenError as exc:
        raise _authentication_error("Invalid or expired authentication token") from exc

    if not isinstance(payload, dict):
        raise _authentication_error("Invalid authentication token")

    if payload.get("type") not in SUBJECT_TYPES:
        raise _authentication_error("Invalid authentication token")

    raw_user_id = payload.get("sub")
    if isinstance(raw_user_id, bool):
        raise _authentication_error("Invalid authentication token")

    try:
        user_id = int(raw_user_id)
    except (TypeError, ValueError, OverflowError) as exc:
        raise _authentication_error("Invalid authentication token") from exc

    if user_id <= 0:
        raise _authentication_error("Invalid authentication token")

    raw_session_version = payload.get("ver", 0)
    if isinstance(raw_session_version, bool):
        raise _authentication_error("Invalid authentication token")

    try:
        session_version = int(raw_session_version)
    except (TypeError, ValueError, OverflowError) as exc:
        raise _authentication_error("Invalid authentication token") from exc

    if session_version < 0:
        raise _authentication_error("Invalid authentication token")

    # Normalize values so downstream code does not need to handle strings from
    # legacy tokens differently from the current integer claims.
    payload["sub"] = str(user_id)
    payload["ver"] = session_version
    return payload


def verify_access_token(
    credentials: HTTPAuthorizationCredentials | None,
    *,
    subject_type: SubjectType = "user",
) -> int:
    """Validate claims for the expected account type without a DB lookup."""

    payload = decode_access_token(credentials)
    if payload["type"] != subject_type:
        raise _authentication_error("Invalid authentication token")
    return int(payload["sub"])


def get_current_user_id(
    db: Session = Depends(get_db),
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> int:
    """Authorize a request for an existing, active user.

    This dependency is intentionally read-only with respect to user status.
    Authentication must never reactivate a soft-deleted account.
    """

    payload = decode_access_token(credentials)
    if payload["type"] != "user":
        raise _authentication_error("Invalid authentication token")
    user_id = int(payload["sub"])
    user = user_dao.get_user_by_id(db=db, user_id=user_id)

    if not user or user.status != "active":
        raise _authentication_error("User is inactive or does not exist")

    current_session_version = getattr(user, "session_version", 0) or 0
    if payload["ver"] != current_session_version:
        raise _authentication_error("Session is no longer valid")

    return user_id


def get_current_partner_id(
    db: Session = Depends(get_db),
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> int:
    """Authorize a request for an existing, active partner.

    This dependency is intentionally read-only with respect to partner status.
    Authentication must never reactivate a soft-deleted account.
    """

    payload = decode_access_token(credentials)
    if payload["type"] != "partner":
        raise _authentication_error("Invalid authentication token")
    partner_id = int(payload["sub"])
    partner = partner_dao.get_partner_by_id(db=db, partner_id=partner_id)

    if not partner:
        raise _authentication_error("Partner does not exist")

    current_session_version = getattr(partner, "session_version", 0) or 0
    if payload["ver"] != current_session_version:
        raise _authentication_error("Session is no longer valid")

    return partner_id
