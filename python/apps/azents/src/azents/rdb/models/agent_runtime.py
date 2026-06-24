"""AgentRuntime model."""

import datetime
import enum
from typing import Any

import sqlalchemy as sa
from azcommon.uuid import uuid7
from sqlalchemy.dialects.postgresql import ENUM, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from azents.core.enums import (
    AgentRuntimeRunState,
    RuntimeDesiredState,
    RuntimeLifecycleCommandType,
    RuntimeProviderConnectionState,
    RuntimeProviderObservedState,
    RuntimeRunnerState,
)
from azents.rdb.models.base import RDBModel
from azents.rdb.types.datetime import TimeZoneDateTime


def _enum_values(enum_cls: type[enum.StrEnum]) -> list[str]:
    """Return StrEnum values stored in the DB."""
    return [v.value for v in enum_cls]


agent_runtime_run_state_enum = ENUM(
    AgentRuntimeRunState,
    name="agent_runtime_run_state",
    create_type=False,
    values_callable=_enum_values,
)


runtime_desired_state_enum = ENUM(
    RuntimeDesiredState,
    name="runtime_desired_state",
    create_type=False,
    values_callable=_enum_values,
)
runtime_lifecycle_command_type_enum = ENUM(
    RuntimeLifecycleCommandType,
    name="runtime_lifecycle_command_type",
    create_type=False,
    values_callable=_enum_values,
)
runtime_provider_observed_state_enum = ENUM(
    RuntimeProviderObservedState,
    name="runtime_provider_observed_state",
    create_type=False,
    values_callable=_enum_values,
)
runtime_provider_connection_state_enum = ENUM(
    RuntimeProviderConnectionState,
    name="runtime_provider_connection_state",
    create_type=False,
    values_callable=_enum_values,
)
runtime_runner_state_enum = ENUM(
    RuntimeRunnerState,
    name="runtime_runner_state",
    create_type=False,
    values_callable=_enum_values,
)


class RDBAgentRuntime(RDBModel):
    """AgentRuntime table.

    Agentt t runtime identityt worker/runtime durable statet t.
    """

    __tablename__ = "agent_runtimes"

    UQ_AGENT_ID = sa.UniqueConstraint("agent_id", name="uq_agent_runtimes_agent_id")
    UQ_ID_WORKSPACE_ID = sa.UniqueConstraint(
        "id",
        "workspace_id",
        name="uq_agent_runtimes_id_workspace_id",
    )
    IX_WORKSPACE_ID = sa.Index("ix_agent_runtimes_workspace_id", "workspace_id")
    IX_RUNTIME_PROVIDER_ID = sa.Index(
        "ix_agent_runtimes_runtime_provider_id", "runtime_provider_id"
    )
    IX_DESIRED_OBSERVED = sa.Index(
        "ix_agent_runtimes_desired_observed",
        "desired_state",
        "provider_observed_state",
    )
    IX_LIFECYCLE_DISPATCH = sa.Index(
        "ix_agent_runtimes_lifecycle_dispatch",
        "desired_generation",
        "last_lifecycle_dispatch_generation",
    )
    IX_PROVIDER_CONNECTION_STATE = sa.Index(
        "ix_agent_runtimes_provider_connection_state",
        "provider_connection_state",
    )
    IX_PROVIDER_OBSERVE_REQUESTED_AT = sa.Index(
        "ix_agent_runtimes_provider_observe_requested_at",
        "provider_observe_requested_at",
    )
    IX_RUNNER_STATE = sa.Index("ix_agent_runtimes_runner_state", "runner_state")
    IX_CURRENT_SESSION_ID = sa.Index(
        "ix_agent_runtimes_current_session_id", "current_session_id"
    )
    IX_PENDING_COMMAND = sa.Index(
        "ix_agent_runtimes_pending_command",
        "pending_command_created_at",
        postgresql_where=sa.text("pending_command_id IS NOT NULL"),
    )
    IX_STOP_REQUESTED_AT = sa.Index(
        "ix_agent_runtimes_stop_requested_at",
        "stop_requested_at",
        postgresql_where=sa.text("stop_requested_at IS NOT NULL"),
    )
    IX_RUN_STATE_RUNNING = sa.Index(
        "ix_agent_runtimes_run_state_running",
        "run_heartbeat_at",
        postgresql_where=sa.text("run_state = 'running'"),
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

    runtime_provider_id: Mapped[str | None] = mapped_column(
        sa.String(120),
        nullable=True,
        default=None,
    )
    provider_config: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB,
        nullable=True,
        default=None,
    )
    desired_state: Mapped[RuntimeDesiredState] = mapped_column(
        runtime_desired_state_enum,
        init=False,
        nullable=False,
        server_default=RuntimeDesiredState.STOPPED.value,
    )
    desired_generation: Mapped[int] = mapped_column(
        sa.Integer,
        init=False,
        nullable=False,
        server_default="0",
    )
    last_lifecycle_command: Mapped[RuntimeLifecycleCommandType | None] = mapped_column(
        runtime_lifecycle_command_type_enum,
        init=False,
        nullable=True,
        default=None,
    )
    reset_final_desired_state: Mapped[RuntimeDesiredState | None] = mapped_column(
        runtime_desired_state_enum,
        init=False,
        nullable=True,
        default=None,
    )
    provider_observed_state: Mapped[RuntimeProviderObservedState] = mapped_column(
        runtime_provider_observed_state_enum,
        init=False,
        nullable=False,
        server_default=RuntimeProviderObservedState.UNKNOWN.value,
    )
    provider_observed_generation: Mapped[int] = mapped_column(
        sa.Integer,
        init=False,
        nullable=False,
        server_default="0",
    )
    provider_observed_at: Mapped[datetime.datetime | None] = mapped_column(
        TimeZoneDateTime,
        init=False,
        nullable=True,
        default=None,
    )
    provider_observe_requested_at: Mapped[datetime.datetime | None] = mapped_column(
        TimeZoneDateTime,
        init=False,
        nullable=True,
        default=None,
    )
    last_lifecycle_dispatch_generation: Mapped[int] = mapped_column(
        sa.Integer,
        init=False,
        nullable=False,
        server_default="0",
    )
    provider_connection_state: Mapped[RuntimeProviderConnectionState] = mapped_column(
        runtime_provider_connection_state_enum,
        init=False,
        nullable=False,
        server_default=RuntimeProviderConnectionState.DISCONNECTED.value,
    )
    runner_state: Mapped[RuntimeRunnerState] = mapped_column(
        runtime_runner_state_enum,
        init=False,
        nullable=False,
        server_default=RuntimeRunnerState.UNKNOWN.value,
    )
    runner_generation: Mapped[int] = mapped_column(
        sa.Integer,
        init=False,
        nullable=False,
        server_default="0",
    )
    workspace_path: Mapped[str | None] = mapped_column(
        sa.Text,
        init=False,
        nullable=True,
        default=None,
    )
    failure_generation: Mapped[int | None] = mapped_column(
        sa.Integer,
        init=False,
        nullable=True,
        default=None,
    )
    failure_code: Mapped[str | None] = mapped_column(
        sa.String(120),
        init=False,
        nullable=True,
        default=None,
    )
    failure_message: Mapped[str | None] = mapped_column(
        sa.Text,
        init=False,
        nullable=True,
        default=None,
    )
    last_state_change_at: Mapped[datetime.datetime | None] = mapped_column(
        TimeZoneDateTime,
        init=False,
        nullable=True,
        default=None,
    )

    current_session_id: Mapped[str | None] = mapped_column(
        sa.String(32),
        sa.ForeignKey("agent_sessions.id", ondelete="SET NULL"),
        nullable=True,
        default=None,
    )
    run_state: Mapped[AgentRuntimeRunState] = mapped_column(
        agent_runtime_run_state_enum,
        init=False,
        server_default=AgentRuntimeRunState.IDLE.value,
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
    pending_command_payload: Mapped[dict[str, Any] | None] = mapped_column(
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
        UQ_AGENT_ID,
        UQ_ID_WORKSPACE_ID,
        IX_WORKSPACE_ID,
        IX_RUNTIME_PROVIDER_ID,
        IX_DESIRED_OBSERVED,
        IX_LIFECYCLE_DISPATCH,
        IX_PROVIDER_CONNECTION_STATE,
        IX_PROVIDER_OBSERVE_REQUESTED_AT,
        IX_RUNNER_STATE,
        IX_CURRENT_SESSION_ID,
        IX_PENDING_COMMAND,
        IX_STOP_REQUESTED_AT,
        IX_RUN_STATE_RUNNING,
    )
