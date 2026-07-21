"""Toolkit State RDB model."""

import datetime
from typing import Any

import sqlalchemy as sa
from azcommon.uuid import uuid7
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from azents.rdb.models.base import RDBModel
from azents.rdb.types.datetime import TimeZoneDateTime


class RDBToolkitState(RDBModel):
    """Session-bound Toolkit State table.

    Stores durable JSON state by AgentSession, Toolkit namespace, and state name.
    """

    __tablename__ = "toolkit_states"

    id: Mapped[str] = mapped_column(
        sa.String(32),
        primary_key=True,
        init=False,
        default_factory=lambda: uuid7().hex,
    )
    agent_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("agents.id", ondelete="RESTRICT"),
        nullable=False,
    )
    session_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("agent_sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    toolkit_namespace: Mapped[str] = mapped_column(sa.String(100), nullable=False)
    state_name: Mapped[str] = mapped_column(sa.String(100), nullable=False)
    state_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    schema_version: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    version: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=1)
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

    UQ_IDENTITY = sa.UniqueConstraint(
        "agent_id",
        "session_id",
        "toolkit_namespace",
        "state_name",
        name="uq_toolkit_states_identity",
    )
    IX_AGENT_ID = sa.Index("ix_toolkit_states_agent_id", "agent_id")
    IX_SESSION_ID = sa.Index("ix_toolkit_states_session_id", "session_id")

    __table_args__ = (
        UQ_IDENTITY,
        IX_AGENT_ID,
        IX_SESSION_ID,
    )
