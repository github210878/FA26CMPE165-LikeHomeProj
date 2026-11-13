from tokenize import String

from sqlalchemy import Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.config.database import Base


class RedeemHistory(Base):
    __tablename__ = "redeem_histories"

    redeem_id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )

    user_id: Mapped[int] = mapped_column(Integer, nullable=False)

    reward_points_redeemed: Mapped[int] = mapped_column(Integer, nullable=False)

    created_at: Mapped[str] = mapped_column(String(100), nullable=False)
