
from datetime import datetime

from pydantic import BaseModel, Field


class RewardsBalanceResponse(BaseModel):
    """Current reward points for an authenticated user."""

    reward_points: int = Field(ge=0)


class RewardTransactionResponse(BaseModel):
    """One reward points transaction."""

    transaction_id: int
    points: int
    transaction_type: str
    created_at: datetime
    description: str | None = None


class RewardsHistoryResponse(BaseModel):
    """Reward transactions belonging to the authenticated user."""

    transactions: list[RewardTransactionResponse]
