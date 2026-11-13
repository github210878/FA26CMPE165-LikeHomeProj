from http.client import HTTPException

from sqlalchemy.orm import Session

from app.models.payment import Payment
from app.models.redeem_history import RedeemHistory
from app.models.reservation import Reservation
from app.models.user import User
from app.models.user_balance import UserBalance


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
        user.session_version = (user.session_version or 0) + 1
        db.commit()
        db.refresh(user)
    return user


def delete_user(db: Session, user_id: int):
    user = db.query(User).filter(User.user_id == user_id).first()
    if user:
        user.status = "deleted"
        user.session_version = (user.session_version or 0) + 1
        db.commit()
        db.refresh(user)
    return user


def invalidate_user_sessions(db: Session, user_id: int):
    """Invalidate all previously issued tokens for a user."""

    user = db.query(User).filter(User.user_id == user_id).first()
    if user:
        user.session_version = (user.session_version or 0) + 1
        db.commit()
        db.refresh(user)
    return user


def decrease_reward_points(db: Session, user_id: int, amount: int):
    user = db.query(User).filter(User.user_id == user_id).first()
    pre_points = user.reward_points
    if user:
        user.reward_points = pre_points - amount
        db.commit()
        db.refresh(user)
    return user


def create_user_balance(db: Session, user_id: int):
    user = db.query(UserBalance).filter(UserBalance.user_id == user_id).first()
    if user:
        user_balance = UserBalance(user_id=user_id, balance=0.0)
        db.add(user_balance)
        db.commit()
        db.refresh(user)
    return user_balance


def get_user_balance(db: Session, user_id: int):
    user = db.query(UserBalance).filter(UserBalance.user_id == user_id).first()
    if user:
        return user.balance
    return None


def update_user_reward_points(
    db: Session,
    user_id: int,
    new_reward_points: int,
):
    user = (
        db.query(User).filter(User.user_id == user_id).with_for_update().one_or_none()
    )

    if user is not None:
        user.reward_points = new_reward_points
        db.flush()

    return user


def update_user_balance(
    db: Session,
    user_id: int,
    new_balance: float,
):
    user_balance = (
        db.query(UserBalance)
        .filter(UserBalance.user_id == user_id)
        .with_for_update()
        .one_or_none()
    )

    if user_balance is not None:
        user_balance.balance = new_balance
        db.flush()

    return user_balance


def update_user_reward_points_and_balance(
    db: Session,
    user_id: int,
    new_reward_points: int,
    new_balance: float,
):
    try:
        user = update_user_reward_points(
            db=db,
            user_id=user_id,
            new_reward_points=new_reward_points,
        )

        if user is None:
            raise HTTPException(
                status_code=404,
                detail="User not found",
            )

        user_balance = update_user_balance(
            db=db,
            user_id=user_id,
            new_balance=new_balance,
        )

        if user_balance is None:
            raise HTTPException(
                status_code=404,
                detail="User balance not found",
            )

        db.commit()

        db.refresh(user)
        db.refresh(user_balance)

        return user, user_balance

    except HTTPException:
        db.rollback()
        raise

    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail="Failed to update user account",
        ) from exc


def lock_user_balance(db: Session, user_id: int):
    """Lock the user balance row for update to prevent race conditions."""
    return (
        db.query(UserBalance)
        .filter(UserBalance.user_id == user_id)
        .with_for_update()
        .first()
    )


def get_reservation_history(db: Session, user_id: int):
    """Get reservation history for a user"""
    user = db.query(User).filter(User.user_id == user_id).first()
    if not user:
        return None

    reservations = (
        db.query(Reservation)
        .filter(Reservation.user_id == user_id)
        .order_by(Reservation.created_at.desc())
        .all()
    )
    return reservations


def get_payment_history(db: Session, user_id: int):
    """Get payment history for a user"""
    reservations = get_reservation_history(db=db, user_id=user_id)

    payments = []

    for reservation in reservations:
        payment = (
            db.query(Payment)
            .filter(Payment.reservation_id == reservation.reservation_id)
            .first()
        )
        payments.append(payment)

    return payments


def create_redeem_history(db: Session, user_id: int, reward_points_redeemed: int):
    """Create a redeem history entry for a user"""

    redeem_history = RedeemHistory(
        user_id=user_id,
        reward_points_redeemed=reward_points_redeemed,
    )

    db.add(redeem_history)
    db.commit()
    db.refresh(redeem_history)

    return redeem_history


def get_redeem_history(db: Session, user_id: int):
    """Get redeem history for a user"""
    user = db.query(User).filter(User.user_id == user_id).first()
    if not user:
        return None

    redeem_history = (
        db.query(RedeemHistory)
        .filter(RedeemHistory.user_id == user_id)
        .order_by(RedeemHistory.created_at.desc())
        .all()
    )
    return redeem_history
