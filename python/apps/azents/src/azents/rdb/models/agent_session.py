"""AgentSession model."""

import datetime

import sqlalchemy as sa
from azcommon.uuid import uuid7
from sqlalchemy.dialects.postgresql import ENUM, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from azents.core.enums import (
    AgentSessionEndReason,
    AgentSessionRunState,
    AgentSessionStartReason,
    AgentSessionStatus,
)
from azents.core.llm_catalog import ModelReasoningEffort
from azents.rdb.models.base import RDBModel
from azents.rdb.models.conversation import RDBConversation
from azents.rdb.models.inference_profile_types import model_reasoning_effort_enum
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
agent_session_run_state_enum = ENUM(
    AgentSessionRunState,
    name="agent_session_run_state",
    create_type=False,
    values_callable=_agent_session_run_state_values,
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
    """Shared durable execution state, without public Conversation identity."""

    __tablename__ = "agent_sessions"

    FK_LIFECYCLE_ROOT = sa.ForeignKeyConstraint(
        ["lifecycle_root_session_id"],
        ["agent_sessions.id"],
        name="fk_session_lifecycle_root",
        ondelete="RESTRICT",
    )
    UQ_LIFECYCLE_IDENTITY = sa.UniqueConstraint(
        "id", "agent_id", "status", name="uq_session_lifecycle_identity"
    )

    CK_CURRENT_INFERENCE_STATE = sa.CheckConstraint(
        "(current_model_target_label IS NULL "
        "AND current_model_selection IS NULL "
        "AND current_model_settings IS NULL "
        "AND current_reasoning_effort IS NULL "
        "AND current_enabled_execution_options = '[]'::jsonb "
        "AND current_effective_context_window_tokens IS NULL "
        "AND current_effective_auto_compaction_threshold_tokens IS NULL "
        "AND current_inference_resolved_at IS NULL) OR "
        "(current_model_target_label IS NOT NULL "
        "AND current_model_selection IS NOT NULL "
        "AND current_model_settings IS NOT NULL "
        "AND current_effective_context_window_tokens IS NOT NULL "
        "AND current_effective_auto_compaction_threshold_tokens IS NOT NULL "
        "AND current_inference_resolved_at IS NOT NULL)",
        name="ck_agent_sessions_current_inference_state",
    )
    CK_CURRENT_CONTEXT_WINDOW = sa.CheckConstraint(
        "current_effective_context_window_tokens IS NULL "
        "OR current_effective_context_window_tokens > 0",
        name="ck_agent_sessions_current_context_window",
    )
    CK_CURRENT_COMPACTION_THRESHOLD = sa.CheckConstraint(
        "current_effective_auto_compaction_threshold_tokens IS NULL "
        "OR current_effective_auto_compaction_threshold_tokens > 0",
        name="ck_agent_sessions_current_compaction_threshold",
    )
    CK_APPLIED_INFERENCE_PROFILE = sa.CheckConstraint(
        "applied_model_target_label IS NOT NULL OR "
        "(applied_reasoning_effort IS NULL "
        "AND applied_enabled_execution_options = '[]'::jsonb)",
        name="ck_agent_sessions_applied_inference_profile",
    )
    IX_LIFECYCLE_ROOT = sa.Index(
        "ix_agent_sessions_lifecycle_root_session_id",
        "lifecycle_root_session_id",
        postgresql_where=sa.text("lifecycle_root_session_id IS NOT NULL"),
    )
    IX_WORKSPACE_ID = sa.Index("ix_agent_sessions_workspace_id", "workspace_id")
    IX_AGENT_ID = sa.Index("ix_agent_sessions_agent_id", "agent_id")
    IX_MODEL_INPUT_HEAD_EVENT_ID = sa.Index(
        "ix_agent_sessions_model_input_head_event_id",
        "model_input_head_event_id",
    )
    IX_MODEL_FILE_GC_CURSOR = sa.Index(
        "ix_agent_sessions_model_file_gc_cursor",
        sa.text("model_file_gc_cursor_event_id ASC NULLS FIRST"),
        "model_input_head_event_id",
        postgresql_where=sa.text("model_input_head_event_id IS NOT NULL"),
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
    IX_ARCHIVED_PURGE_AFTER = sa.Index(
        "ix_agent_sessions_archived_purge_after",
        "purge_after",
        postgresql_where=sa.text(
            "status = 'archived' AND lifecycle_root_session_id IS NULL "
            "AND purge_after IS NOT NULL"
        ),
    )

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
    lifecycle_root_session_id: Mapped[str | None] = mapped_column(
        sa.String(32),
        nullable=True,
    )
    conversation: Mapped[RDBConversation | None] = relationship(
        init=False,
        lazy="selectin",
        uselist=False,
        viewonly=True,
        primaryjoin="RDBAgentSession.id == RDBConversation.session_id",
        foreign_keys="RDBConversation.session_id",
    )
    current_model_target_label: Mapped[str | None] = mapped_column(
        sa.String(80),
        nullable=True,
    )
    applied_model_target_label: Mapped[str | None] = mapped_column(
        sa.String(80),
        nullable=True,
    )
    current_model_selection: Mapped[dict[str, object] | None] = mapped_column(
        JSONB(none_as_null=True),
        nullable=True,
    )
    current_model_settings: Mapped[dict[str, object] | None] = mapped_column(
        JSONB(none_as_null=True),
        nullable=True,
    )
    current_reasoning_effort: Mapped[ModelReasoningEffort | None] = mapped_column(
        model_reasoning_effort_enum,
        nullable=True,
    )
    applied_reasoning_effort: Mapped[ModelReasoningEffort | None] = mapped_column(
        model_reasoning_effort_enum,
        nullable=True,
    )
    current_enabled_execution_options: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=sa.text("'[]'::jsonb"),
    )
    applied_enabled_execution_options: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=sa.text("'[]'::jsonb"),
    )
    applied_profile_generation: Mapped[int] = mapped_column(
        sa.BigInteger,
        init=False,
        nullable=False,
        server_default="0",
    )
    current_effective_context_window_tokens: Mapped[int | None] = mapped_column(
        sa.Integer,
        nullable=True,
    )
    current_effective_auto_compaction_threshold_tokens: Mapped[int | None] = (
        mapped_column(
            sa.Integer,
            nullable=True,
        )
    )
    current_inference_resolved_at: Mapped[datetime.datetime | None] = mapped_column(
        TimeZoneDateTime,
        nullable=True,
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
    last_activity_at: Mapped[datetime.datetime] = mapped_column(
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
    model_file_gc_cursor_event_id: Mapped[str | None] = mapped_column(
        sa.String(32),
        nullable=True,
        default=None,
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
    owner_generation: Mapped[int] = mapped_column(
        sa.BigInteger,
        init=False,
        server_default="0",
        nullable=False,
    )
    stop_requested_at: Mapped[datetime.datetime | None] = mapped_column(
        TimeZoneDateTime,
        init=False,
        nullable=True,
        default=None,
    )
    stop_requester_user_id: Mapped[str | None] = mapped_column(
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
    archived_at: Mapped[datetime.datetime | None] = mapped_column(
        TimeZoneDateTime,
        init=False,
        nullable=True,
        default=None,
    )
    purge_after: Mapped[datetime.datetime | None] = mapped_column(
        TimeZoneDateTime,
        init=False,
        nullable=True,
        default=None,
    )
    archive_policy_revision: Mapped[int | None] = mapped_column(
        sa.BigInteger,
        init=False,
        nullable=True,
        default=None,
    )
    archive_retention_days_snapshot: Mapped[int | None] = mapped_column(
        sa.Integer,
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
        FK_LIFECYCLE_ROOT,
        UQ_LIFECYCLE_IDENTITY,
        IX_LIFECYCLE_ROOT,
        CK_CURRENT_INFERENCE_STATE,
        CK_CURRENT_CONTEXT_WINDOW,
        CK_CURRENT_COMPACTION_THRESHOLD,
        CK_APPLIED_INFERENCE_PROFILE,
        IX_WORKSPACE_ID,
        IX_AGENT_ID,
        IX_MODEL_INPUT_HEAD_EVENT_ID,
        IX_MODEL_FILE_GC_CURSOR,
        IX_STOP_REQUESTED_AT,
        IX_RUN_STATE_RUNNING,
        IX_ARCHIVED_PURGE_AFTER,
    )
