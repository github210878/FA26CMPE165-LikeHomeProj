
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.config.database import get_db
from app.schemas.rewards_schema import RewardsBalanceResponse
from app.services import rewards_service
from app.utilities.auth import get_current_user_id


router = APIRouter(prefix="/users/rewards", tags=["Rewards"])


@router.get("/balance", response_model=RewardsBalanceResponse)
def get_rewards_balance(
        db: Session = Depends(get_db),
        user_id: int = Depends(get_current_user_id),
):
    """Return the authenticated user's reward points balance."""
    return rewards_service.get_rewards_balance(db, user_id)
