
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.repositories import shortlist_dao
from app.schemas.shortlist_schema import (
    ShortlistItemResponse,
    ShortlistResponse,
)


def add_hotel(db: Session, user_id: int, property_token: str):
    """Save a hotel to the authenticated user's shortlist."""

    existing = shortlist_dao.get_saved_hotel(
        db, user_id, property_token
    )

    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Hotel is already in your shortlist",
        )

    saved_hotel = shortlist_dao.add_saved_hotel(
        db, user_id, property_token
    )

    return ShortlistItemResponse(
        property_token=saved_hotel.property_token
    )


def get_hotels(db: Session, user_id: int) -> ShortlistResponse:
    """Return saved hotels belonging to the authenticated user."""

    saved_hotels = shortlist_dao.get_saved_hotels(db, user_id)

    return ShortlistResponse(
        properties=[
            ShortlistItemResponse(property_token=hotel.property_token)
            for hotel in saved_hotels
        ]
    )


def remove_hotel(
        db: Session, user_id: int, property_token: str
) -> None:
    """Remove a hotel from the authenticated user's shortlist."""

    removed = shortlist_dao.delete_saved_hotel(
        db, user_id, property_token
    )

    if not removed:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Hotel not found in your shortlist",
        )
