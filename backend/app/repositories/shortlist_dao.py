
from sqlalchemy.orm import Session

from app.models.shortlist import Shortlist


def get_saved_hotel(db: Session, user_id: int, property_token: str):
    return (
        db.query(Shortlist)
        .filter(
            Shortlist.user_id == user_id,
            Shortlist.property_token == property_token,
            )
        .first()
    )


def get_saved_hotels(db: Session, user_id: int):
    return (
        db.query(Shortlist)
        .filter(Shortlist.user_id == user_id)
        .order_by(Shortlist.shortlist_id.asc())
        .all()
    )


def add_saved_hotel(db: Session, user_id: int, property_token: str):
    saved_hotel = Shortlist(
        user_id=user_id,
        property_token=property_token,
    )

    db.add(saved_hotel)

    try:
        db.commit()
        db.refresh(saved_hotel)
    except Exception:
        db.rollback()
        raise

    return saved_hotel


def delete_saved_hotel(db: Session, user_id: int, property_token: str):
    saved_hotel = get_saved_hotel(db, user_id, property_token)

    if saved_hotel is None:
        return False

    db.delete(saved_hotel)

    try:
        db.commit()
    except Exception:
        db.rollback()
        raise

    return True
