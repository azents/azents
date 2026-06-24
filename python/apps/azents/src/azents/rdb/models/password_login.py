"""PasswordLogin model."""

import datetime

import sqlalchemy as sa
from azcommon.uuid import uuid7
from sqlalchemy.orm import Mapped, mapped_column

from azents.rdb.models.base import RDBModel
from azents.rdb.types.datetime import TimeZoneDateTime


class RDBPasswordLogin(RDBModel):
    """PasswordLogin table.

    t password auth t managet.
    """

    __tablename__ = "password_logins"

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
    password_hash: Mapped[str] = mapped_column(
        sa.String(255),
        nullable=False,
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

    # Constraint condition. (t 1t password)
    UQ_USER_ID = sa.UniqueConstraint("user_id", name="uq_password_logins_user_id")

    __table_args__ = (UQ_USER_ID,)
