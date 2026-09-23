from sqlalchemy.orm import Session

from app.models.user import User


def get_user_by_email(db: Session, email: str):
    return db.query(User).filter(User.email == email).first()


def get_user_by_id(db: Session, user_id: int):
    return db.query(User).filter(User.user_id == user_id).first()


def create_user(
    db: Session,
    email: str,
    password_hash: str,
    full_name: str | None,
    phone: str | None,
):
    user = User(
        email=email, password_hash=password_hash, full_name=full_name, phone=phone
    )

    db.add(user)
    db.commit()
    db.refresh(user)

    return user


def update_user_password(db: Session, user_id: int, new_password_hash: str):
    user = db.query(User).filter(User.user_id == user_id).first()
    if user:
        user.password_hash = new_password_hash
        db.commit()
        db.refresh(user)
    return user


def delete_user(db: Session, user_id: int):
    user = db.query(User).filter(User.user_id == user_id).first()
    if user:
        user.status = "deleted"
        db.commit()
        db.refresh(user)
    return user
