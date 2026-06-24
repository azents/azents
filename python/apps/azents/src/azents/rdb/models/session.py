"""Session model."""

import datetime

import sqlalchemy as sa
from azcommon.uuid import uuid7
from sqlalchemy.orm import Mapped, mapped_column

from azents.rdb.models.base import RDBModel
from azents.rdb.types.datetime import TimeZoneDateTime


class RDBSession(RDBModel):
    """Session table.

    user auth sessiont managet.
    """

    __tablename__ = "sessions"

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
        index=True,
    )
    refresh_token: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    expires_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime,
        nullable=False,
    )

    prev_refresh_token: Mapped[str | None] = mapped_column(
        sa.String(64),
        default=None,
    )
    revoked_at: Mapped[datetime.datetime | None] = mapped_column(
        TimeZoneDateTime,
        default=None,
    )
    user_agent: Mapped[str | None] = mapped_column(
        sa.Text,
        default=None,
    )
    ip_address: Mapped[str | None] = mapped_column(
        sa.String(45),
        default=None,
    )
    max_expires_at: Mapped[datetime.datetime | None] = mapped_column(
        TimeZoneDateTime,
        default=None,
    )

    refresh_token_created_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime,
        init=False,
        server_default=sa.func.now(),
    )
    last_used_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime,
        init=False,
        server_default=sa.func.now(),
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

    # Constraint condition and index.
    UQ_REFRESH_TOKEN = sa.UniqueConstraint(
        "refresh_token", name="uq_sessions_refresh_token"
    )
    IX_REFRESH_TOKEN = sa.Index("ix_sessions_refresh_token", "refresh_token")
    IX_PREV_REFRESH_TOKEN = sa.Index(
        "ix_sessions_prev_refresh_token", "prev_refresh_token"
    )

    __table_args__ = (UQ_REFRESH_TOKEN, IX_REFRESH_TOKEN, IX_PREV_REFRESH_TOKEN)
