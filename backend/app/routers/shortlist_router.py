
from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.config.database import get_db
from app.schemas.shortlist_schema import ShortlistAddRequest, ShortlistResponse
from app.services import shortlist_service
from app.utilities.auth import get_current_user_id


router = APIRouter(prefix="/shortlist", tags=["Shortlist"])


@router.post("", status_code=status.HTTP_201_CREATED)
def add_to_shortlist(
        request: ShortlistAddRequest,
        db: Session = Depends(get_db),
        user_id: int = Depends(get_current_user_id),
):
    """Save a hotel to the current user's shortlist."""
    return shortlist_service.add_hotel(db, user_id, request.property_token)


@router.get("", response_model=ShortlistResponse)
def get_shortlist(
        db: Session = Depends(get_db),
        user_id: int = Depends(get_current_user_id),
):
    """Retrieve hotels saved by the current user."""
    return shortlist_service.get_hotels(db, user_id)


@router.delete("/{property_token}", status_code=status.HTTP_204_NO_CONTENT)
def remove_from_shortlist(
        property_token: str,
        db: Session = Depends(get_db),
        user_id: int = Depends(get_current_user_id),
):
    """Remove a hotel from the current user's shortlist."""
    shortlist_service.remove_hotel(db, user_id, property_token)
    return None
