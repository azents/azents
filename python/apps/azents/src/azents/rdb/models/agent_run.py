"""Event agent_runs table model."""

import datetime
import enum

import sqlalchemy as sa
from azcommon.uuid import uuid7
from sqlalchemy.dialects.postgresql import ENUM, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from azents.core.enums import AgentRunPhase, AgentRunStatus
from azents.core.inference_profile import (
    InferenceProfileFailureCode,
    InferenceProfileSource,
)
from azents.core.llm_catalog import ModelReasoningEffort
from azents.rdb.models.base import RDBModel
from azents.rdb.models.inference_profile_types import (
    inference_profile_failure_code_enum,
    inference_profile_source_enum,
    model_reasoning_effort_enum,
)
from azents.rdb.types.datetime import TimeZoneDateTime

type JSONScalar = str | int | float | bool | None
type JSONValue = JSONScalar | list[JSONValue] | dict[str, JSONValue]


def _enum_values(enum_cls: type[enum.StrEnum]) -> list[str]:
    """Return StrEnum values stored in the DB."""
    return [value.value for value in enum_cls]


agent_run_phase_enum = ENUM(
    AgentRunPhase,
    name="agent_run_phase",
    create_type=False,
    values_callable=_enum_values,
)
agent_run_status_enum = ENUM(
    AgentRunStatus,
    name="agent_run_status",
    create_type=False,
    values_callable=_enum_values,
)


class RDBAgentRun(RDBModel):
    """agent_runs tablet durable run state row."""

    __tablename__ = "agent_runs"

    CK_REQUESTED_PROFILE = sa.CheckConstraint(
        "requested_reasoning_effort IS NULL "
        "OR requested_model_target_label IS NOT NULL",
        name="ck_agent_runs_requested_profile",
    )
    CK_RESOLVED_PROFILE = sa.CheckConstraint(
        "resolved_reasoning_effort IS NULL OR resolved_model_selection IS NOT NULL",
        name="ck_agent_runs_resolved_profile",
    )
    CK_EFFECTIVE_CONTEXT_WINDOW = sa.CheckConstraint(
        "effective_context_window_tokens IS NULL "
        "OR effective_context_window_tokens > 0",
        name="ck_agent_runs_effective_context_window",
    )
    CK_EFFECTIVE_COMPACTION_THRESHOLD = sa.CheckConstraint(
        "effective_auto_compaction_threshold_tokens IS NULL "
        "OR effective_auto_compaction_threshold_tokens > 0",
        name="ck_agent_runs_effective_compaction_threshold",
    )
    IX_SESSION_ID = sa.Index("ix_agent_runs_session_id", "session_id")
    UQ_SESSION_RUN_INDEX = sa.UniqueConstraint(
        "session_id",
        "run_index",
        name="uq_agent_runs_session_run_index",
    )
    IX_SESSION_STATUS = sa.Index(
        "ix_agent_runs_session_status",
        "session_id",
        "status",
    )
    IX_PHASE = sa.Index("ix_agent_runs_phase", "phase")
    IX_STATUS = sa.Index("ix_agent_runs_status", "status")
    IX_PARENT_AGENT_RUN_ID = sa.Index(
        "ix_agent_runs_parent_agent_run_id",
        "parent_agent_run_id",
    )
    UQ_SESSION_PENDING = sa.Index(
        "uq_agent_runs_session_pending",
        "session_id",
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
    )

    id: Mapped[str] = mapped_column(
        sa.String(32),
        primary_key=True,
        init=False,
        default_factory=lambda: uuid7().hex,
    )
    session_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("agent_sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    run_index: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    requested_model_target_label: Mapped[str | None] = mapped_column(
        sa.String(80),
        nullable=True,
    )
    requested_reasoning_effort: Mapped[ModelReasoningEffort | None] = mapped_column(
        model_reasoning_effort_enum,
        nullable=True,
    )
    inference_profile_source: Mapped[InferenceProfileSource | None] = mapped_column(
        inference_profile_source_enum,
        nullable=True,
    )
    resolved_model_selection: Mapped[dict[str, JSONValue] | None] = mapped_column(
        JSONB,
        nullable=True,
    )
    resolved_reasoning_effort: Mapped[ModelReasoningEffort | None] = mapped_column(
        model_reasoning_effort_enum,
        nullable=True,
    )
    resolved_at: Mapped[datetime.datetime | None] = mapped_column(
        TimeZoneDateTime,
        nullable=True,
    )
    effective_context_window_tokens: Mapped[int | None] = mapped_column(
        sa.Integer,
        nullable=True,
    )
    effective_auto_compaction_threshold_tokens: Mapped[int | None] = mapped_column(
        sa.Integer,
        nullable=True,
    )
    inference_profile_failure_code: Mapped[InferenceProfileFailureCode | None] = (
        mapped_column(
            inference_profile_failure_code_enum,
            nullable=True,
        )
    )
    inference_profile_failure_message: Mapped[str | None] = mapped_column(
        sa.Text,
        nullable=True,
    )
    parent_agent_run_id: Mapped[str | None] = mapped_column(
        sa.String(32),
        sa.ForeignKey("agent_runs.id", ondelete="SET NULL"),
        nullable=True,
    )
    phase: Mapped[AgentRunPhase] = mapped_column(
        agent_run_phase_enum,
        nullable=False,
        default=AgentRunPhase.IDLE,
        server_default=AgentRunPhase.IDLE.value,
    )
    status: Mapped[AgentRunStatus] = mapped_column(
        agent_run_status_enum,
        nullable=False,
        default=AgentRunStatus.RUNNING,
        server_default=AgentRunStatus.RUNNING.value,
    )
    active_tool_calls: Mapped[list[dict[str, JSONValue]]] = mapped_column(
        JSONB,
        nullable=False,
        default_factory=list,
        server_default=sa.text("'[]'::jsonb"),
    )
    retry_state: Mapped[dict[str, JSONValue] | None] = mapped_column(
        JSONB,
        nullable=True,
        default=None,
    )
    last_completed_event_id: Mapped[str | None] = mapped_column(
        sa.String(32),
        nullable=True,
        default=None,
    )
    terminal_result_event_id: Mapped[str | None] = mapped_column(
        sa.String(32),
        nullable=True,
        default=None,
    )
    terminal_result_message: Mapped[str | None] = mapped_column(
        sa.Text,
        nullable=True,
        default=None,
    )
    stop_requested_at: Mapped[datetime.datetime | None] = mapped_column(
        TimeZoneDateTime,
        init=False,
        nullable=True,
        default=None,
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime,
        init=False,
        server_default=sa.func.now(),
        nullable=False,
    )
    started_at: Mapped[datetime.datetime | None] = mapped_column(
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
    updated_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime,
        init=False,
        server_default=sa.func.now(),
        onupdate=sa.func.now(),
    )

    __table_args__ = (
        CK_REQUESTED_PROFILE,
        CK_RESOLVED_PROFILE,
        CK_EFFECTIVE_CONTEXT_WINDOW,
        CK_EFFECTIVE_COMPACTION_THRESHOLD,
        IX_SESSION_ID,
        UQ_SESSION_RUN_INDEX,
        IX_SESSION_STATUS,
        IX_PHASE,
        IX_STATUS,
        IX_PARENT_AGENT_RUN_ID,
        UQ_SESSION_PENDING,
    )
