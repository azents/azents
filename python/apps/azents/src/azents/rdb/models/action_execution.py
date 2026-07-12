"""Durable TurnAction execution models."""

import datetime
import enum

import sqlalchemy as sa
from azcommon.uuid import uuid7
from sqlalchemy.dialects.postgresql import ENUM, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from azents.core.enums import ActionExecutionEventKind, ActionExecutionStatus
from azents.rdb.models.base import RDBModel
from azents.rdb.types.datetime import TimeZoneDateTime


def _enum_values(enum_cls: type[enum.StrEnum]) -> list[str]:
    """Return StrEnum values stored in the DB."""
    return [value.value for value in enum_cls]


action_execution_status_enum = ENUM(
    ActionExecutionStatus,
    name="action_execution_status",
    create_type=False,
    values_callable=_enum_values,
)
action_execution_event_kind_enum = ENUM(
    ActionExecutionEventKind,
    name="action_execution_event_kind",
    create_type=False,
    values_callable=_enum_values,
)


class RDBActionExecution(RDBModel):
    """Durable execution state for one operation TurnAction event."""

    __tablename__ = "action_executions"

    IX_SESSION_ID = sa.Index("ix_action_executions_session_id", "session_id")
    UQ_INPUT_BUFFER_ID = sa.UniqueConstraint(
        "input_buffer_id",
        name="uq_action_executions_input_buffer_id",
    )
    IX_SESSION_STATUS = sa.Index(
        "ix_action_executions_session_id_status",
        "session_id",
        "status",
    )
    IX_SESSION_INPUT_BUFFER = sa.Index(
        "ix_action_executions_session_id_input_buffer_id",
        "session_id",
        "input_buffer_id",
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
    input_buffer_id: Mapped[str] = mapped_column(
        sa.String(32),
        nullable=False,
    )
    action_type: Mapped[str] = mapped_column(sa.Text, nullable=False)
    action: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    status: Mapped[ActionExecutionStatus] = mapped_column(
        action_execution_status_enum,
        nullable=False,
        default=ActionExecutionStatus.PENDING,
        server_default=ActionExecutionStatus.PENDING.value,
    )
    failure_summary: Mapped[str | None] = mapped_column(
        sa.Text,
        nullable=True,
        default=None,
    )
    started_at: Mapped[datetime.datetime | None] = mapped_column(
        TimeZoneDateTime,
        nullable=True,
        default=None,
    )
    completed_at: Mapped[datetime.datetime | None] = mapped_column(
        TimeZoneDateTime,
        nullable=True,
        default=None,
    )
    failed_at: Mapped[datetime.datetime | None] = mapped_column(
        TimeZoneDateTime,
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
        IX_SESSION_ID,
        UQ_INPUT_BUFFER_ID,
        IX_SESSION_STATUS,
        IX_SESSION_INPUT_BUFFER,
    )


class RDBActionExecutionEvent(RDBModel):
    """Append-only progress event for one TurnAction execution."""

    __tablename__ = "action_execution_events"

    IX_ACTION_EXECUTION_ID = sa.Index(
        "ix_action_execution_events_action_execution_id",
        "action_execution_id",
    )
    IX_SESSION_ID = sa.Index("ix_action_execution_events_session_id", "session_id")
    UQ_EXECUTION_SEQUENCE = sa.UniqueConstraint(
        "action_execution_id",
        "sequence",
        name="uq_action_execution_events_execution_sequence",
    )

    id: Mapped[str] = mapped_column(
        sa.String(32),
        primary_key=True,
        init=False,
        default_factory=lambda: uuid7().hex,
    )
    action_execution_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("action_executions.id", ondelete="CASCADE"),
        nullable=False,
    )
    session_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("agent_sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    sequence: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    kind: Mapped[ActionExecutionEventKind] = mapped_column(
        action_execution_event_kind_enum,
        nullable=False,
    )
    step_key: Mapped[str | None] = mapped_column(
        sa.Text,
        nullable=True,
        default=None,
    )
    command_argv: Mapped[list[str] | None] = mapped_column(
        sa.ARRAY(sa.Text),
        nullable=True,
        default=None,
    )
    content: Mapped[str | None] = mapped_column(sa.Text, nullable=True, default=None)
    exit_code: Mapped[int | None] = mapped_column(
        sa.Integer,
        nullable=True,
        default=None,
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime,
        init=False,
        server_default=sa.func.now(),
    )

    __table_args__ = (
        IX_ACTION_EXECUTION_ID,
        IX_SESSION_ID,
        UQ_EXECUTION_SEQUENCE,
    )
