"""EmailVerification model."""

import datetime

import sqlalchemy as sa
from azcommon.uuid import uuid7
from sqlalchemy.orm import Mapped, mapped_column

from azents.rdb.models.base import RDBModel
from azents.rdb.types.datetime import TimeZoneDateTime


class RDBEmailVerification(RDBModel):
    """EmailVerification table.

    Stores email verification codes.
    Used for user authentication.
    """

    __tablename__ = "email_verifications"

    id: Mapped[str] = mapped_column(
        sa.String(32),
        primary_key=True,
        init=False,
        default_factory=lambda: uuid7().hex,
    )
    email: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    code: Mapped[str] = mapped_column(sa.String(6), nullable=False)
    csrf_token: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    expires_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime,
        nullable=False,
    )

    verified_at: Mapped[datetime.datetime | None] = mapped_column(
        TimeZoneDateTime,
        default=None,
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime,
        init=False,
        server_default=sa.func.now(),
    )
