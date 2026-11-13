from decimal import Decimal

from fastapi import Depends, HTTPException
from pwdlib import PasswordHash
from sqlalchemy.orm import Session

from app.config.constants import Constants
from app.repositories import user_dao
from app.schemas.user_schema import (
    ChangePasswordRequest,
    DeleteUserRequest,
    LoginUserRequest,
    LoginUserResponse,
    RegisterUserRequest,
    RegisterUserResponse,
)
from app.utilities.auth import create_access_token, get_current_user_id

PASSWORD_HASHER = PasswordHash.recommended()
REWARD_POINT_CONVERSION_RATE = Constants.REWARD_POINTS_PER_DOLLAR


def register_user(user_info: RegisterUserRequest, db: Session):
    email = user_info.email.lower()
    existing_user = user_dao.get_user_by_email(db=db, email=email)

    if existing_user:
        raise HTTPException(status_code=409, detail="Email already registered")

    new_user = user_dao.create_user(
        db=db,
        email=email,
        password_hash=PASSWORD_HASHER.hash(user_info.password),
        full_name=user_info.full_name,
        phone=user_info.phone,
    )

    user_dao.create_user_balance(db=db, user_id=new_user.user_id)

    return RegisterUserResponse(
        user_id=new_user.user_id,
        email=new_user.email,
        full_name=new_user.full_name,
        phone=new_user.phone,
    )


def login_user(login_info: LoginUserRequest, db: Session):
    user = user_dao.get_user_by_email(db=db, email=login_info.email.lower())

    if (
        not user
        or user.status != "active"
        or not PASSWORD_HASHER.verify(login_info.password, user.password_hash)
    ):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    access_token = create_access_token(
        user.user_id,
        session_version=getattr(user, "session_version", 0),
        subject_type="user",
    )

    return LoginUserResponse(
        user_id=user.user_id,
        email=user.email,
        full_name=user.full_name,
        phone=user.phone,
        access_token=access_token,
        token_type="bearer",
    )


def change_password(
    change_password_info: ChangePasswordRequest,
    db: Session,
    user_id: int,
):
    user = user_dao.get_user_by_id(db=db, user_id=user_id)

    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if not PASSWORD_HASHER.verify(
        change_password_info.old_password, user.password_hash
    ):
        raise HTTPException(status_code=401, detail="Old password is incorrect")

    new_password_hash = PASSWORD_HASHER.hash(change_password_info.new_password)
    user_dao.update_user_password(
        db=db, user_id=user_id, new_password_hash=new_password_hash
    )

    return {"status": True, "message": "Password changed successfully"}


def delete_user(
    delete_user_info: DeleteUserRequest,
    db: Session,
    user_id: int,
):
    user = user_dao.get_user_by_id(db=db, user_id=user_id)

    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if not PASSWORD_HASHER.verify(delete_user_info.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Password is incorrect")

    deleted_user = user_dao.delete_user(db=db, user_id=user_id)
    if not deleted_user or deleted_user.status != "deleted":
        raise HTTPException(status_code=500, detail="Failed to delete user")
    else:
        return {"status": True, "message": "User deleted successfully"}


def logout_user(db: Session, user_id: int):
    """Invalidate all currently issued access tokens for a user."""

    user = user_dao.invalidate_user_sessions(db=db, user_id=user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    return {"status": True, "message": "Logged out successfully"}



def get_my_reward_points(db: Session, user_id: int):
    """Return the authenticated user's current reward points."""

    user = user_dao.get_user_by_id(
        db=db,
        user_id=user_id,
    )

    if not user:
        raise HTTPException(
            status_code=404,
            detail="User not found",
        )

    return {
        "status": True,
        "reward_points": user.reward_points,
    }
def get_balance(db: Session, user_id: int = Depends(get_current_user_id)):
    """Query balance by the user_id via user_dao"""

    user = user_dao.get_user_by_id(user_id=user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user_balance = user_dao.get_user_balance(db=db, user_id=user_id)
    return {
        "status": True,
        "balance": user_balance,
    }


def redeem_reward_points(db: Session, user_id: int, amount: int):
    """Redeem reward points for a user"""

    if amount <= 0:
        raise HTTPException(
            status_code=400,
            detail="Amount must be greater than zero",
        )

    user = user_dao.get_user_by_id(user_id=user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if user.reward_points < amount:
        raise HTTPException(
            status_code=400, detail="Insufficient reward points to redeem"
        )

    converted_amount = Decimal(amount) / Decimal(str(REWARD_POINT_CONVERSION_RATE))

    # Deduct the reward points and update the balance
    new_reward_points = user.reward_points - amount
    new_balance = user_dao.get_user_balance(db=db, user_id=user_id) + converted_amount

    user, user_balance = user_dao.update_user_reward_points_and_balance(
        db=db,
        user_id=user_id,
        new_reward_points=new_reward_points,
        new_balance=new_balance,
    )

    user_dao.create_redeem_history(
        db=db, user_id=user_id, reward_points_redeemed=amount
    )
    return {
        "status": True,
        "message": f"Successfully redeemed {amount} reward points",
        "new_reward_points": new_reward_points,
        "new_balance": user_balance.balance,
    }


def get_redeem_history(db: Session, user_id: int):
    """Get redeem history for a user"""

    user = user_dao.get_user_by_id(user_id=user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    redeem_history = user_dao.get_redeem_history(db=db, user_id=user_id)
    return {
        "status": True,
        "redeem_history": redeem_history,
    }


def get_reservation_history(db: Session, user_id: int):
    """Get reservation history for a user"""

    user = user_dao.get_user_by_id(user_id=user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    reservations = user_dao.get_reservation_history(db=db, user_id=user_id)
    return {
        "status": True,
        "reservations": reservations,
    }


def get_payment_history(db: Session, user_id: int):
    """Get payment history for a user"""

    user = user_dao.get_user_by_id(user_id=user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    payments = user_dao.get_payment_history(db=db, user_id=user_id)
    return {
        "status": True,
        "payments": payments,
    }


def get_reward_points_history(db: Session, user_id: int):
    """Get reward points history for a user"""

    user = user_dao.get_user_by_id(user_id=user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    reward_points_history = []

    payment_history = user_dao.get_payment_history(db=db, user_id=user_id)

    for payment in payment_history:
        if payment.payment_status == "paid":
            reward_points_history.append(
                {
                    "reward_points_change": payment.amount
                    * Decimal(str(REWARD_POINT_CONVERSION_RATE)),
                    "type": "earned",
                    "created_at": payment.created_at,
                }
            )

    redeem_history = user_dao.get_redeem_history(db=db, user_id=user_id)

    for redeem in redeem_history:
        reward_points_history.append(
            {
                "reward_points_change": -redeem.reward_points_redeemed,
                "type": "redeemed",
                "created_at": redeem.created_at,
            }
        )

    # Sort the history by created_at in descending order
    reward_points_history.sort(key=lambda x: x["created_at"], reverse=True)

    return {
        "status": True,
        "reward_points_history": reward_points_history,
    }
def get_my_reward_history(db: Session, user_id: int):
    """Retrieve rewards history for the authenticated user."""

    user = user_dao.get_user_by_id(db=db, user_id=user_id)

    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    raise HTTPException(
        status_code=503,
        detail="Rewards history is not available yet",
    )