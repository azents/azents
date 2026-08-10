"""Durable Agent Runtime removal operation model."""

import datetime
import enum

import sqlalchemy as sa
from azcommon.uuid import uuid7
from sqlalchemy.dialects.postgresql import ENUM
from sqlalchemy.orm import Mapped, mapped_column

from azents.core.enums import (
    AgentRuntimeRemovalStage,
    AgentRuntimeRemovalStatus,
    RuntimeTerminalDeleteAcknowledgementKind,
)
from azents.rdb.models.base import RDBModel
from azents.rdb.types.datetime import TimeZoneDateTime


def _enum_values(enum_cls: type[enum.StrEnum]) -> list[str]:
    """Return enum values stored in PostgreSQL."""
    return [value.value for value in enum_cls]


agent_runtime_removal_status_enum = ENUM(
    AgentRuntimeRemovalStatus,
    name="agent_runtime_removal_status",
    create_type=False,
    values_callable=_enum_values,
)
agent_runtime_removal_stage_enum = ENUM(
    AgentRuntimeRemovalStage,
    name="agent_runtime_removal_stage",
    create_type=False,
    values_callable=_enum_values,
)
runtime_removal_delete_acknowledgement_kind_enum = ENUM(
    RuntimeTerminalDeleteAcknowledgementKind,
    name="runtime_terminal_delete_acknowledgement_kind",
    create_type=False,
    values_callable=_enum_values,
)


class RDBAgentRuntimeRemovalOperation(RDBModel):
    """Content-free durable Agent Runtime removal state."""

    __tablename__ = "agent_runtime_removal_operations"

    UQ_ACTIVE_AGENT = sa.Index(
        "uq_agent_runtime_removal_operations_active_agent",
        "agent_id",
        unique=True,
        postgresql_where=sa.text("status != 'completed'"),
    )
    UQ_AGENT_IDEMPOTENCY_KEY = sa.Index(
        "uq_agent_runtime_removal_operations_agent_idempotency",
        "agent_id",
        "idempotency_key",
        unique=True,
    )
    IX_STATUS_NEXT_ATTEMPT_AT = sa.Index(
        "ix_agent_runtime_removal_operations_status_next_attempt_at",
        "status",
        "next_attempt_at",
    )
    IX_AGENT_CREATED_AT = sa.Index(
        "ix_agent_runtime_removal_operations_agent_created_at",
        "agent_id",
        "created_at",
    )
    CK_CAPABILITY_VERSIONS = sa.CheckConstraint(
        "expected_capability_version >= 1 "
        "AND committed_capability_version > expected_capability_version",
        name="ck_agent_runtime_removal_operations_capability_versions",
    )
    CK_DESTRUCTIVE_SCOPE_VERSION = sa.CheckConstraint(
        "destructive_scope_version >= 1",
        name="ck_agent_runtime_removal_operations_scope_version",
    )
    CK_NONNEGATIVE_COUNTS = sa.CheckConstraint(
        "active_root_session_count >= 0 "
        "AND active_subagent_count >= 0 "
        "AND active_run_count >= 0 "
        "AND queued_runtime_action_count >= 0 "
        "AND cleanup_scanned_context_count >= 0 "
        "AND cleanup_invalidated_context_count >= 0 "
        "AND cleanup_invalidated_context_count <= cleanup_scanned_context_count",
        name="ck_agent_runtime_removal_operations_nonnegative_counts",
    )
    CK_TARGET_GENERATION = sa.CheckConstraint(
        "target_terminal_delete_generation IS NULL "
        "OR target_terminal_delete_generation >= 1",
        name="ck_agent_runtime_removal_operations_target_generation",
    )
    CK_ACKNOWLEDGEMENT = sa.CheckConstraint(
        "(physical_delete_acknowledged_at IS NULL "
        "AND physical_delete_acknowledgement_kind IS NULL) OR "
        "(physical_delete_acknowledged_at IS NOT NULL "
        "AND physical_delete_acknowledgement_kind IS NOT NULL)",
        name="ck_agent_runtime_removal_operations_acknowledgement",
    )
    CK_PHYSICAL_DELETE_TARGET = sa.CheckConstraint(
        "(physical_deletion_required IS NULL "
        "AND target_terminal_delete_generation IS NULL "
        "AND physical_delete_requested_at IS NULL "
        "AND physical_delete_acknowledged_at IS NULL) OR "
        "(physical_deletion_required = false "
        "AND target_terminal_delete_generation IS NULL "
        "AND physical_delete_requested_at IS NULL "
        "AND physical_delete_acknowledged_at IS NULL) OR "
        "(physical_deletion_required = true "
        "AND target_terminal_delete_generation IS NOT NULL "
        "AND physical_delete_requested_at IS NOT NULL)",
        name="ck_agent_runtime_removal_operations_physical_target",
    )
    CK_COMPLETION = sa.CheckConstraint(
        "(status = 'completed' AND stage = 'completed' "
        "AND completed_at IS NOT NULL "
        "AND product_cleanup_completed_at IS NOT NULL "
        "AND physical_deletion_required IS NOT NULL "
        "AND (physical_deletion_required = false OR "
        "physical_delete_acknowledged_at IS NOT NULL)) OR "
        "(status != 'completed' AND stage != 'completed' "
        "AND completed_at IS NULL)",
        name="ck_agent_runtime_removal_operations_completion",
    )

    agent_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=False,
    )
    workspace_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    requested_by_workspace_user_id: Mapped[str | None] = mapped_column(
        sa.String(32),
        nullable=True,
    )
    idempotency_key: Mapped[str] = mapped_column(sa.String(120), nullable=False)
    expected_capability_version: Mapped[int] = mapped_column(
        sa.BigInteger,
        nullable=False,
    )
    committed_capability_version: Mapped[int] = mapped_column(
        sa.BigInteger,
        nullable=False,
    )
    agent_runtime_id: Mapped[str | None] = mapped_column(
        sa.String(32),
        sa.ForeignKey("agent_runtimes.id", ondelete="SET NULL"),
        nullable=True,
    )
    confirmed_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime,
        nullable=False,
    )
    destructive_scope_version: Mapped[int] = mapped_column(
        sa.Integer,
        nullable=False,
    )

    id: Mapped[str] = mapped_column(
        sa.String(32),
        primary_key=True,
        init=False,
        default_factory=lambda: uuid7().hex,
    )
    status: Mapped[AgentRuntimeRemovalStatus] = mapped_column(
        agent_runtime_removal_status_enum,
        init=False,
        nullable=False,
        server_default=AgentRuntimeRemovalStatus.PENDING.value,
    )
    stage: Mapped[AgentRuntimeRemovalStage] = mapped_column(
        agent_runtime_removal_stage_enum,
        init=False,
        nullable=False,
        server_default=AgentRuntimeRemovalStage.FENCING.value,
    )
    active_root_session_count: Mapped[int] = mapped_column(
        sa.Integer,
        init=False,
        nullable=False,
        server_default="0",
    )
    active_subagent_count: Mapped[int] = mapped_column(
        sa.Integer,
        init=False,
        nullable=False,
        server_default="0",
    )
    active_run_count: Mapped[int] = mapped_column(
        sa.Integer,
        init=False,
        nullable=False,
        server_default="0",
    )
    queued_runtime_action_count: Mapped[int] = mapped_column(
        sa.Integer,
        init=False,
        nullable=False,
        server_default="0",
    )
    cleanup_cursor_context_id: Mapped[str | None] = mapped_column(
        sa.String(32),
        init=False,
        nullable=True,
        default=None,
    )
    cleanup_scanned_context_count: Mapped[int] = mapped_column(
        sa.Integer,
        init=False,
        nullable=False,
        server_default="0",
    )
    cleanup_invalidated_context_count: Mapped[int] = mapped_column(
        sa.Integer,
        init=False,
        nullable=False,
        server_default="0",
    )
    product_cleanup_completed_at: Mapped[datetime.datetime | None] = mapped_column(
        TimeZoneDateTime,
        init=False,
        nullable=True,
        default=None,
    )
    physical_deletion_required: Mapped[bool | None] = mapped_column(
        sa.Boolean,
        init=False,
        nullable=True,
        default=None,
    )
    target_terminal_delete_generation: Mapped[int | None] = mapped_column(
        sa.BigInteger,
        init=False,
        nullable=True,
        default=None,
    )
    physical_delete_requested_at: Mapped[datetime.datetime | None] = mapped_column(
        TimeZoneDateTime,
        init=False,
        nullable=True,
        default=None,
    )
    physical_delete_acknowledgement_kind: Mapped[
        RuntimeTerminalDeleteAcknowledgementKind | None
    ] = mapped_column(
        runtime_removal_delete_acknowledgement_kind_enum,
        init=False,
        nullable=True,
        default=None,
    )
    physical_delete_acknowledged_at: Mapped[datetime.datetime | None] = mapped_column(
        TimeZoneDateTime,
        init=False,
        nullable=True,
        default=None,
    )
    attempt_count: Mapped[int] = mapped_column(
        sa.Integer,
        init=False,
        nullable=False,
        server_default="0",
    )
    lease_owner: Mapped[str | None] = mapped_column(
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
    next_attempt_at: Mapped[datetime.datetime | None] = mapped_column(
        TimeZoneDateTime,
        init=False,
        nullable=True,
        default=None,
    )
    last_error_kind: Mapped[str | None] = mapped_column(
        sa.String(120),
        init=False,
        nullable=True,
        default=None,
    )
    last_error_summary: Mapped[str | None] = mapped_column(
        sa.Text,
        init=False,
        nullable=True,
        default=None,
    )
    started_at: Mapped[datetime.datetime | None] = mapped_column(
        TimeZoneDateTime,
        init=False,
        nullable=True,
        default=None,
    )
    completed_at: Mapped[datetime.datetime | None] = mapped_column(
        TimeZoneDateTime,
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
        UQ_ACTIVE_AGENT,
        UQ_AGENT_IDEMPOTENCY_KEY,
        IX_STATUS_NEXT_ATTEMPT_AT,
        IX_AGENT_CREATED_AT,
        CK_CAPABILITY_VERSIONS,
        CK_DESTRUCTIVE_SCOPE_VERSION,
        CK_NONNEGATIVE_COUNTS,
        CK_TARGET_GENERATION,
        CK_ACKNOWLEDGEMENT,
        CK_PHYSICAL_DELETE_TARGET,
        CK_COMPLETION,
    )
