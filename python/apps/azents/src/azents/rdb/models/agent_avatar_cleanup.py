"""Durable cleanup jobs for superseded Agent avatars."""

import datetime
from typing import Any

import sqlalchemy as sa
from azcommon.uuid import uuid7
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

import azents.rdb.models.agent as _  # noqa: F401  # Register Agent FK metadata.
from azents.rdb.models.base import RDBModel
from azents.rdb.types.datetime import TimeZoneDateTime


class RDBAgentAvatarCleanupJob(RDBModel):
    """Durable deletion responsibility for one immutable prior avatar."""

    __tablename__ = "agent_avatar_cleanup_jobs"

    IX_NEXT_ATTEMPT_LEASE_UNTIL = sa.Index(
        "ix_agent_avatar_cleanup_jobs_next_attempt_lease_until",
        "next_attempt_at",
        "lease_until",
    )
    IX_AGENT_ID = sa.Index(
        "ix_agent_avatar_cleanup_jobs_agent_id",
        "agent_id",
    )
    CK_ATTEMPT_COUNT_NONNEGATIVE = sa.CheckConstraint(
        "attempt_count >= 0",
        name="ck_agent_avatar_cleanup_jobs_attempt_count_nonnegative",
    )

    id: Mapped[str] = mapped_column(
        sa.String(32),
        primary_key=True,
        init=False,
        default_factory=lambda: uuid7().hex,
    )
    avatar: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    agent_id: Mapped[str | None] = mapped_column(
        sa.String(32),
        sa.ForeignKey("agents.id", ondelete="SET NULL"),
        nullable=True,
        default=None,
    )
    attempt_count: Mapped[int] = mapped_column(
        sa.Integer,
        init=False,
        nullable=False,
        server_default="0",
    )
    next_attempt_at: Mapped[datetime.datetime | None] = mapped_column(
        TimeZoneDateTime,
        init=False,
        nullable=True,
        server_default=sa.func.now(),
    )
    lease_token: Mapped[str | None] = mapped_column(
        sa.String(120),
        init=False,
        nullable=True,
        default=None,
    )
    lease_until: Mapped[datetime.datetime | None] = mapped_column(
        TimeZoneDateTime,
        init=False,
        nullable=True,
        default=None,
    )
    last_failure_kind: Mapped[str | None] = mapped_column(
        sa.String(120),
        init=False,
        nullable=True,
        default=None,
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime,
        init=False,
        nullable=False,
        server_default=sa.func.now(),
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime,
        init=False,
        nullable=False,
        server_default=sa.func.now(),
        onupdate=sa.func.now(),
    )

    __table_args__ = (
        IX_NEXT_ATTEMPT_LEASE_UNTIL,
        IX_AGENT_ID,
        CK_ATTEMPT_COUNT_NONNEGATIVE,
    )
