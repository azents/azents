"""AgentSession model."""

import datetime

import sqlalchemy as sa
from azcommon.uuid import uuid7
from sqlalchemy.dialects.postgresql import ENUM, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from azents.core.enums import (
    AgentSessionEndReason,
    AgentSessionKind,
    AgentSessionPrimaryKind,
    AgentSessionRunState,
    AgentSessionStartReason,
    AgentSessionStatus,
    AgentSessionTitleSource,
)
from azents.rdb.models.base import RDBModel
from azents.rdb.types.datetime import TimeZoneDateTime


def _agent_session_status_values(
    enum_cls: type[AgentSessionStatus],
) -> list[str]:
    """Return AgentSessionStatus enum values stored in the DB."""
    return [v.value for v in enum_cls]


def _agent_session_run_state_values(
    enum_cls: type[AgentSessionRunState],
) -> list[str]:
    """Return AgentSessionRunState enum values stored in the DB."""
    return [v.value for v in enum_cls]


def _agent_session_kind_values(
    enum_cls: type[AgentSessionKind],
) -> list[str]:
    """Return AgentSessionKind enum values stored in the DB."""
    return [v.value for v in enum_cls]


def _agent_session_primary_kind_values(
    enum_cls: type[AgentSessionPrimaryKind],
) -> list[str]:
    """Return AgentSessionPrimaryKind enum values stored in the DB."""
    return [v.value for v in enum_cls]


def _agent_session_start_reason_values(
    enum_cls: type[AgentSessionStartReason],
) -> list[str]:
    """Return AgentSessionStartReason enum values stored in the DB."""
    return [v.value for v in enum_cls]


def _agent_session_title_source_values(
    enum_cls: type[AgentSessionTitleSource],
) -> list[str]:
    """Return AgentSessionTitleSource enum values stored in the DB."""
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
agent_session_run_state_enum = ENUM(
    AgentSessionRunState,
    name="agent_session_run_state",
    create_type=False,
    values_callable=_agent_session_run_state_values,
)
agent_session_kind_enum = ENUM(
    AgentSessionKind,
    name="agent_session_kind",
    create_type=False,
    values_callable=_agent_session_kind_values,
)
agent_session_primary_kind_enum = ENUM(
    AgentSessionPrimaryKind,
    name="agent_session_primary_kind",
    create_type=False,
    values_callable=_agent_session_primary_kind_values,
)
agent_session_start_reason_enum = ENUM(
    AgentSessionStartReason,
    name="agent_session_start_reason",
    create_type=False,
    values_callable=_agent_session_start_reason_values,
)
agent_session_title_source_enum = ENUM(
    AgentSessionTitleSource,
    name="agent_session_title_source",
    create_type=False,
    values_callable=_agent_session_title_source_values,
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

    UQ_HANDLE = sa.UniqueConstraint("handle", name="uq_agent_sessions_handle")
    IX_WORKSPACE_ID = sa.Index("ix_agent_sessions_workspace_id", "workspace_id")
    IX_AGENT_ID = sa.Index("ix_agent_sessions_agent_id", "agent_id")
    IX_SESSION_KIND = sa.Index("ix_agent_sessions_session_kind", "session_kind")
    IX_AGENT_ACTIVE_LAST_USER_INPUT = sa.Index(
        "ix_agent_sessions_agent_active_last_user_input",
        "agent_id",
        "primary_kind",
        "last_user_input_at",
        postgresql_where=sa.text("status = 'active'"),
    )
    IX_MODEL_INPUT_HEAD_EVENT_ID = sa.Index(
        "ix_agent_sessions_model_input_head_event_id",
        "model_input_head_event_id",
    )
    IX_MODEL_FILE_GC_LAG = sa.Index(
        "ix_agent_sessions_model_file_gc_lag",
        "model_file_gc_cursor_model_order",
        "model_input_head_model_order",
    )
    IX_PENDING_COMMAND = sa.Index(
        "ix_agent_sessions_pending_command",
        "pending_command_created_at",
        postgresql_where=sa.text("pending_command_id IS NOT NULL"),
    )
    IX_STOP_REQUESTED_AT = sa.Index(
        "ix_agent_sessions_stop_requested_at",
        "stop_requested_at",
        postgresql_where=sa.text("stop_requested_at IS NOT NULL"),
    )
    IX_RUN_STATE_RUNNING = sa.Index(
        "ix_agent_sessions_run_state_running",
        "run_heartbeat_at",
        postgresql_where=sa.text("run_state = 'running'"),
    )
    UQ_AGENT_ACTIVE_TEAM_PRIMARY = sa.Index(
        "uq_agent_sessions_agent_active_team_primary",
        "agent_id",
        unique=True,
        postgresql_where=sa.text("status = 'active' AND primary_kind = 'team_primary'"),
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
    agent_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=False,
    )
    handle: Mapped[str] = mapped_column(sa.String(120), nullable=False)
    session_kind: Mapped[AgentSessionKind] = mapped_column(
        agent_session_kind_enum,
        nullable=False,
        default=AgentSessionKind.ROOT,
    )
    status: Mapped[AgentSessionStatus] = mapped_column(
        agent_session_status_enum,
        nullable=False,
        default=AgentSessionStatus.ACTIVE,
    )
    primary_kind: Mapped[AgentSessionPrimaryKind | None] = mapped_column(
        agent_session_primary_kind_enum,
        nullable=True,
        default=None,
    )
    start_reason: Mapped[AgentSessionStartReason] = mapped_column(
        agent_session_start_reason_enum,
        nullable=False,
        default=AgentSessionStartReason.INITIAL,
    )
    title: Mapped[str | None] = mapped_column(
        sa.String(200),
        nullable=True,
        default=None,
    )
    title_source: Mapped[AgentSessionTitleSource | None] = mapped_column(
        agent_session_title_source_enum,
        nullable=True,
        default=None,
    )
    title_generated_at: Mapped[datetime.datetime | None] = mapped_column(
        TimeZoneDateTime,
        nullable=True,
        default=None,
    )
    title_generation_event_id: Mapped[str | None] = mapped_column(
        sa.String(32),
        nullable=True,
        default=None,
    )
    last_user_input_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime,
        init=False,
        server_default=sa.func.now(),
        nullable=False,
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
    model_input_head_model_order: Mapped[int | None] = mapped_column(
        sa.BigInteger,
        nullable=True,
        default=None,
    )
    model_file_gc_cursor_event_id: Mapped[str | None] = mapped_column(
        sa.String(32),
        nullable=True,
        default=None,
    )
    model_file_gc_cursor_model_order: Mapped[int] = mapped_column(
        sa.BigInteger,
        init=False,
        server_default="0",
        nullable=False,
    )
    model_file_gc_updated_at: Mapped[datetime.datetime | None] = mapped_column(
        TimeZoneDateTime,
        init=False,
        nullable=True,
        default=None,
    )
    run_state: Mapped[AgentSessionRunState] = mapped_column(
        agent_session_run_state_enum,
        init=False,
        server_default=AgentSessionRunState.IDLE.value,
        nullable=False,
    )
    run_heartbeat_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime,
        init=False,
        server_default=sa.func.now(),
        nullable=False,
    )
    pending_command_id: Mapped[str | None] = mapped_column(
        sa.String(32),
        init=False,
        nullable=True,
        default=None,
    )
    pending_command_name: Mapped[str | None] = mapped_column(
        sa.String(120),
        init=False,
        nullable=True,
        default=None,
    )
    pending_command_payload: Mapped[dict[str, object] | None] = mapped_column(
        JSONB,
        init=False,
        nullable=True,
        default=None,
    )
    pending_command_user_id: Mapped[str | None] = mapped_column(
        sa.String(32),
        sa.ForeignKey("users.id", ondelete="SET NULL"),
        init=False,
        nullable=True,
        default=None,
    )
    pending_command_created_at: Mapped[datetime.datetime | None] = mapped_column(
        TimeZoneDateTime,
        init=False,
        nullable=True,
        default=None,
    )
    stop_requested_at: Mapped[datetime.datetime | None] = mapped_column(
        TimeZoneDateTime,
        init=False,
        nullable=True,
        default=None,
    )
    stop_requested_by: Mapped[str | None] = mapped_column(
        sa.String(32),
        sa.ForeignKey("users.id", ondelete="SET NULL"),
        init=False,
        nullable=True,
        default=None,
    )
    stop_request_id: Mapped[str | None] = mapped_column(
        sa.String(32),
        init=False,
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
        UQ_HANDLE,
        IX_WORKSPACE_ID,
        IX_AGENT_ID,
        IX_SESSION_KIND,
        IX_AGENT_ACTIVE_LAST_USER_INPUT,
        IX_MODEL_INPUT_HEAD_EVENT_ID,
        IX_MODEL_FILE_GC_LAG,
        IX_PENDING_COMMAND,
        IX_STOP_REQUESTED_AT,
        IX_RUN_STATE_RUNNING,
        UQ_AGENT_ACTIVE_TEAM_PRIMARY,
    )
