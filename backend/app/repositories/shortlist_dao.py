
from sqlalchemy.orm import Session

# TODO: Import Jesse's shortlist model when available.
# Expected model fields: user_id, property_token


def get_saved_hotel(
        db: Session, user_id: int, property_token: str
):
    """Find one saved hotel for this user."""
    raise NotImplementedError("Waiting for shortlist database model")


def get_saved_hotels(db: Session, user_id: int):
    """Retrieve all hotels saved by this user."""
    raise NotImplementedError("Waiting for shortlist database model")


def add_saved_hotel(
        db: Session, user_id: int, property_token: str
):
    """Save a hotel for this user."""
    raise NotImplementedError("Waiting for shortlist database model")


def delete_saved_hotel(
        db: Session, user_id: int, property_token: str
):
    """Remove a hotel saved by this user."""
    raise NotImplementedError("Waiting for shortlist database model")
