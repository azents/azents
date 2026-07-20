"""Shared unread terminal Run projection for AgentSessions."""

import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from azents.rdb.models.base import RDBModel
from azents.rdb.types.datetime import TimeZoneDateTime


class RDBAgentSessionUnreadRun(RDBModel):
    """Current terminal Run requiring shared Session review."""

    __tablename__ = "agent_session_unread_runs"

    CK_RUN_INDEX = sa.CheckConstraint(
        "run_index > 0",
        name="ck_agent_session_unread_runs_run_index_positive",
    )
    UQ_RUN_ID = sa.UniqueConstraint(
        "run_id",
        name="uq_agent_session_unread_runs_run_id",
    )

    session_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("agent_sessions.id", ondelete="CASCADE"),
        primary_key=True,
    )
    run_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("agent_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    run_index: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime,
        init=False,
        server_default=sa.func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime,
        init=False,
        server_default=sa.func.now(),
        onupdate=sa.func.now(),
        nullable=False,
    )

    __table_args__ = (CK_RUN_INDEX, UQ_RUN_ID)
