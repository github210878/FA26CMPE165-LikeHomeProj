
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.repositories import user_dao
from app.schemas.rewards_schema import RewardsBalanceResponse
from app.schemas.rewards_schema import (
    RewardsBalanceResponse,
    RewardsHistoryResponse,
)


def get_rewards_balance(
        db: Session, user_id: int
) -> RewardsBalanceResponse:
    """Get the current reward points balance for a user."""

    user = user_dao.get_user_by_id(db, user_id)

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    return RewardsBalanceResponse(
        reward_points=user.reward_points
    )

def get_rewards_history(
        db: Session, user_id: int
) -> RewardsHistoryResponse:
    """Retrieve reward transactions for the authenticated user.

    Database integration is pending the rewards ledger model.
    """
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Rewards history is not yet available",
    )
