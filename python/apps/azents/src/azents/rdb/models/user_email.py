"""UserEmail model."""

import datetime

import sqlalchemy as sa
from azcommon.uuid import uuid7
from sqlalchemy.orm import Mapped, mapped_column

from azents.rdb.models.base import RDBModel
from azents.rdb.types.datetime import TimeZoneDateTime


class RDBUserEmail(RDBModel):
    """UserEmail table.

    usert email addresst managet.
    onet usert multiple emailt can have..
    """

    __tablename__ = "user_emails"

    id: Mapped[str] = mapped_column(
        sa.String(32),
        primary_key=True,
        init=False,
        default_factory=lambda: uuid7().hex,
    )
    user_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    email: Mapped[str] = mapped_column(sa.String(255), nullable=False)

    verified_at: Mapped[datetime.datetime | None] = mapped_column(
        TimeZoneDateTime,
        default=None,
    )

    created_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime,
        init=False,
        server_default=sa.func.now(),
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime,
        init=False,
        server_default=sa.func.now(),
        onupdate=sa.func.now(),
    )

    # Constraint condition.
    UQ_EMAIL = sa.UniqueConstraint("email", name="uq_user_emails_email")

    __table_args__ = (UQ_EMAIL,)
