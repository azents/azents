"""AgentSession model."""

import datetime

import sqlalchemy as sa
from azcommon.uuid import uuid7
from sqlalchemy.dialects.postgresql import ENUM
from sqlalchemy.orm import Mapped, mapped_column

from azents.core.enums import (
    AgentSessionEndReason,
    AgentSessionStartReason,
    AgentSessionStatus,
)
from azents.rdb.models.base import RDBModel
from azents.rdb.types.datetime import TimeZoneDateTime


def _agent_session_status_values(
    enum_cls: type[AgentSessionStatus],
) -> list[str]:
    """Return AgentSessionStatus enum values stored in the DB."""
    return [v.value for v in enum_cls]


def _agent_session_start_reason_values(
    enum_cls: type[AgentSessionStartReason],
) -> list[str]:
    """Return AgentSessionStartReason enum values stored in the DB."""
    return [v.value for v in enum_cls]


def _agent_session_end_reason_values(
    enum_cls: type[AgentSessionEndReason],
) -> list[str]:
    """Return AgentSessionEndReason enum values stored in the DB."""
    return [v.value for v in enum_cls]


agent_session_status_enum = ENUM(
    AgentSessionStatus,
    name="agent_session_status",
    create_type=False,
    values_callable=_agent_session_status_values,
)
agent_session_start_reason_enum = ENUM(
    AgentSessionStartReason,
    name="agent_session_start_reason",
    create_type=False,
    values_callable=_agent_session_start_reason_values,
)
agent_session_end_reason_enum = ENUM(
    AgentSessionEndReason,
    name="agent_session_end_reason",
    create_type=False,
    values_callable=_agent_session_end_reason_values,
)


class RDBAgentSession(RDBModel):
    """AgentSession table."""

    __tablename__ = "agent_sessions"

    IX_WORKSPACE_ID = sa.Index("ix_agent_sessions_workspace_id", "workspace_id")
    IX_AGENT_ID = sa.Index("ix_agent_sessions_agent_id", "agent_id")
    IX_AGENT_RUNTIME_ID = sa.Index(
        "ix_agent_sessions_agent_runtime_id", "agent_runtime_id"
    )
    IX_MODEL_INPUT_HEAD_EVENT_ID = sa.Index(
        "ix_agent_sessions_model_input_head_event_id",
        "model_input_head_event_id",
    )
    UQ_RUNTIME_ACTIVE = sa.Index(
        "uq_agent_sessions_runtime_active",
        "agent_runtime_id",
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )

    id: Mapped[str] = mapped_column(
        sa.String(32),
        primary_key=True,
        init=False,
        default_factory=lambda: uuid7().hex,
    )
    workspace_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    agent_runtime_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("agent_runtimes.id", ondelete="CASCADE"),
        nullable=False,
    )
    agent_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=False,
    )
    status: Mapped[AgentSessionStatus] = mapped_column(
        agent_session_status_enum,
        nullable=False,
        default=AgentSessionStatus.ACTIVE,
    )
    start_reason: Mapped[AgentSessionStartReason] = mapped_column(
        agent_session_start_reason_enum,
        nullable=False,
        default=AgentSessionStartReason.INITIAL,
    )

    end_reason: Mapped[AgentSessionEndReason | None] = mapped_column(
        agent_session_end_reason_enum,
        nullable=True,
        default=None,
    )
    model_input_head_event_id: Mapped[str | None] = mapped_column(
        sa.String(32),
        nullable=True,
        default=None,
    )
    started_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime,
        init=False,
        server_default=sa.func.now(),
        nullable=False,
    )
    lifecycle_started_at: Mapped[datetime.datetime | None] = mapped_column(
        TimeZoneDateTime,
        init=False,
        nullable=True,
        default=None,
    )
    ended_at: Mapped[datetime.datetime | None] = mapped_column(
        TimeZoneDateTime,
        init=False,
        nullable=True,
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

    __table_args__ = (
        IX_WORKSPACE_ID,
        IX_AGENT_ID,
        IX_AGENT_RUNTIME_ID,
        IX_MODEL_INPUT_HEAD_EVENT_ID,
        UQ_RUNTIME_ACTIVE,
    )
