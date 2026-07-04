"""Session initialization lifecycle models."""

import datetime

import sqlalchemy as sa
from azcommon.uuid import uuid7
from sqlalchemy.dialects.postgresql import ENUM, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from azents.core.enums import (
    SessionInitializationEventKind,
    SessionInitializationStatus,
    SessionInitializationStepStatus,
    SessionInitializationStepType,
)
from azents.rdb.models.base import RDBModel
from azents.rdb.types.datetime import TimeZoneDateTime


def _session_initialization_status_values(
    enum_cls: type[SessionInitializationStatus],
) -> list[str]:
    """Return SessionInitializationStatus enum values stored in the DB."""
    return [v.value for v in enum_cls]


def _session_initialization_step_status_values(
    enum_cls: type[SessionInitializationStepStatus],
) -> list[str]:
    """Return SessionInitializationStepStatus enum values stored in the DB."""
    return [v.value for v in enum_cls]


def _session_initialization_step_type_values(
    enum_cls: type[SessionInitializationStepType],
) -> list[str]:
    """Return SessionInitializationStepType enum values stored in the DB."""
    return [v.value for v in enum_cls]


def _session_initialization_event_kind_values(
    enum_cls: type[SessionInitializationEventKind],
) -> list[str]:
    """Return SessionInitializationEventKind enum values stored in the DB."""
    return [v.value for v in enum_cls]


session_initialization_status_enum = ENUM(
    SessionInitializationStatus,
    name="session_initialization_status",
    create_type=False,
    values_callable=_session_initialization_status_values,
)
session_initialization_step_status_enum = ENUM(
    SessionInitializationStepStatus,
    name="session_initialization_step_status",
    create_type=False,
    values_callable=_session_initialization_step_status_values,
)
session_initialization_step_type_enum = ENUM(
    SessionInitializationStepType,
    name="session_initialization_step_type",
    create_type=False,
    values_callable=_session_initialization_step_type_values,
)
session_initialization_event_kind_enum = ENUM(
    SessionInitializationEventKind,
    name="session_initialization_event_kind",
    create_type=False,
    values_callable=_session_initialization_event_kind_values,
)


class RDBSessionInitialization(RDBModel):
    """One initialization lifecycle for an AgentSession."""

    __tablename__ = "session_initializations"

    UQ_SESSION_ID = sa.UniqueConstraint(
        "session_id",
        name="uq_session_initializations_session_id",
    )
    IX_SESSION_ID = sa.Index(
        "ix_session_initializations_session_id",
        "session_id",
    )
    IX_STATUS = sa.Index(
        "ix_session_initializations_status",
        "status",
    )

    session_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("agent_sessions.id", ondelete="CASCADE"),
        nullable=False,
    )

    id: Mapped[str] = mapped_column(
        sa.String(32),
        primary_key=True,
        init=False,
        default_factory=lambda: uuid7().hex,
    )
    status: Mapped[SessionInitializationStatus] = mapped_column(
        session_initialization_status_enum,
        nullable=False,
        default=SessionInitializationStatus.PENDING,
    )
    failure_summary: Mapped[str | None] = mapped_column(
        sa.Text,
        nullable=True,
        default=None,
    )
    retry_count: Mapped[int] = mapped_column(
        sa.Integer,
        nullable=False,
        default=0,
        server_default="0",
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
    canceled_at: Mapped[datetime.datetime | None] = mapped_column(
        TimeZoneDateTime,
        nullable=True,
        default=None,
    )
    cleaned_at: Mapped[datetime.datetime | None] = mapped_column(
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

    __table_args__ = (UQ_SESSION_ID, IX_SESSION_ID, IX_STATUS)


class RDBSessionInitializationStep(RDBModel):
    """Ordered typed step in an AgentSession initialization lifecycle."""

    __tablename__ = "session_initialization_steps"

    UQ_INITIALIZATION_SEQUENCE = sa.UniqueConstraint(
        "initialization_id",
        "sequence",
        name="uq_session_initialization_steps_initialization_sequence",
    )
    UQ_INITIALIZATION_STEP_KEY = sa.UniqueConstraint(
        "initialization_id",
        "step_key",
        name="uq_session_initialization_steps_initialization_step_key",
    )
    IX_INITIALIZATION_SEQUENCE = sa.Index(
        "ix_session_initialization_steps_initialization_sequence",
        "initialization_id",
        "sequence",
    )
    IX_SESSION_STATUS = sa.Index(
        "ix_session_initialization_steps_session_status",
        "session_id",
        "status",
    )

    initialization_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("session_initializations.id", ondelete="CASCADE"),
        nullable=False,
    )
    session_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("agent_sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    sequence: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    step_key: Mapped[str] = mapped_column(sa.String(120), nullable=False)
    step_type: Mapped[SessionInitializationStepType] = mapped_column(
        session_initialization_step_type_enum,
        nullable=False,
    )
    blocking: Mapped[bool] = mapped_column(sa.Boolean, nullable=False)
    retryable: Mapped[bool] = mapped_column(sa.Boolean, nullable=False)

    id: Mapped[str] = mapped_column(
        sa.String(32),
        primary_key=True,
        init=False,
        default_factory=lambda: uuid7().hex,
    )
    status: Mapped[SessionInitializationStepStatus] = mapped_column(
        session_initialization_step_status_enum,
        nullable=False,
        default=SessionInitializationStepStatus.PENDING,
    )
    attempt: Mapped[int] = mapped_column(
        sa.Integer,
        nullable=False,
        default=1,
        server_default="1",
    )
    depends_on_step_keys: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        default_factory=list,
        server_default=sa.text("'[]'::jsonb"),
    )
    resource_descriptors: Mapped[list[object]] = mapped_column(
        JSONB,
        nullable=False,
        default_factory=list,
        server_default=sa.text("'[]'::jsonb"),
    )
    failure_reason: Mapped[str | None] = mapped_column(
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
        UQ_INITIALIZATION_SEQUENCE,
        UQ_INITIALIZATION_STEP_KEY,
        IX_INITIALIZATION_SEQUENCE,
        IX_SESSION_STATUS,
    )


class RDBSessionInitializationEvent(RDBModel):
    """Append-only event in an AgentSession initialization lifecycle."""

    __tablename__ = "session_initialization_events"

    UQ_INITIALIZATION_SEQUENCE = sa.UniqueConstraint(
        "initialization_id",
        "sequence",
        name="uq_session_initialization_events_initialization_sequence",
    )
    IX_INITIALIZATION_SEQUENCE = sa.Index(
        "ix_session_initialization_events_initialization_sequence",
        "initialization_id",
        "sequence",
    )
    IX_SESSION_CREATED = sa.Index(
        "ix_session_initialization_events_session_created",
        "session_id",
        "created_at",
    )
    IX_STEP_ID = sa.Index(
        "ix_session_initialization_events_step_id",
        "step_id",
    )

    initialization_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("session_initializations.id", ondelete="CASCADE"),
        nullable=False,
    )
    session_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("agent_sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    sequence: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    kind: Mapped[SessionInitializationEventKind] = mapped_column(
        session_initialization_event_kind_enum,
        nullable=False,
    )

    id: Mapped[str] = mapped_column(
        sa.String(32),
        primary_key=True,
        init=False,
        default_factory=lambda: uuid7().hex,
    )
    step_id: Mapped[str | None] = mapped_column(
        sa.String(32),
        sa.ForeignKey("session_initialization_steps.id", ondelete="SET NULL"),
        nullable=True,
        default=None,
    )
    command_argv: Mapped[list[str] | None] = mapped_column(
        JSONB,
        nullable=True,
        default=None,
    )
    content: Mapped[str | None] = mapped_column(
        sa.Text,
        nullable=True,
        default=None,
    )
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
        UQ_INITIALIZATION_SEQUENCE,
        IX_INITIALIZATION_SEQUENCE,
        IX_SESSION_CREATED,
        IX_STEP_ID,
    )
