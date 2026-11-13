
from sqlalchemy import ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.config.database import Base


class Shortlist(Base):
    __tablename__ = "shortlists"

    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "property_token",
            name="uq_shortlist_user_property",
        ),
    )

    shortlist_id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )

    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.user_id", ondelete="CASCADE"),
        nullable=False,
    )

    property_token: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )