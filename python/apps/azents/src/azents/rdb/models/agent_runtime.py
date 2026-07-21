"""AgentRuntime model."""

import datetime
import enum
from typing import Any

import sqlalchemy as sa
from azcommon.uuid import uuid7
from sqlalchemy.dialects.postgresql import ENUM, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from azents.core.enums import (
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
    id: Mapped[str] = mapped_column(
        sa.String(32),
        primary_key=True,
        init=False,
        default_factory=lambda: uuid7().hex,
    )
    workspace_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("workspaces.id", ondelete="RESTRICT"),
        nullable=False,
    )
    agent_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("agents.id", ondelete="RESTRICT"),
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
    terminal_delete_requested_generation: Mapped[int | None] = mapped_column(
        sa.Integer,
        init=False,
        nullable=True,
        default=None,
    )
    terminal_delete_acknowledged_generation: Mapped[int | None] = mapped_column(
        sa.Integer,
        init=False,
        nullable=True,
        default=None,
    )
    terminal_delete_acknowledged_at: Mapped[datetime.datetime | None] = mapped_column(
        TimeZoneDateTime,
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
    provider_generation: Mapped[int] = mapped_column(
        sa.Integer,
        init=False,
        nullable=False,
        server_default="0",
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
    )
