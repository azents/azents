"""Session Routine definitions and retained work, not active execution state."""

import datetime
import enum

import sqlalchemy as sa
from azcommon.uuid import uuid7
from sqlalchemy.dialects.postgresql import ENUM, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from azents.core.json_value import JSONValue
from azents.core.routine import RoutineDeliveryStatus, RoutineObjectiveOutcome
from azents.rdb.models.base import RDBModel
from azents.rdb.types.datetime import TimeZoneDateTime


def _enum_values(enum_cls: type[enum.StrEnum]) -> list[str]:
    """Return the values owned by the PostgreSQL migration."""
    return [value.value for value in enum_cls]


routine_objective_outcome_enum = ENUM(
    RoutineObjectiveOutcome,
    name="routine_objective_outcome",
    values_callable=_enum_values,
    create_type=False,
)
routine_delivery_status_enum = ENUM(
    RoutineDeliveryStatus,
    name="routine_delivery_status",
    values_callable=_enum_values,
    create_type=False,
)


class RDBRoutine(RDBModel):
    """One Session-owned definition with exactly comparable content."""

    __tablename__ = "routines"

    UQ_SESSION_SLUG = sa.UniqueConstraint(
        "session_id", "slug", name="uq_routines_session_slug"
    )
    IX_SESSION_ID = sa.Index("ix_routines_session_id", "session_id")
    IX_AGENT_ID = sa.Index("ix_routines_agent_id", "agent_id")

    id: Mapped[str] = mapped_column(
        sa.String(32), primary_key=True, init=False, default_factory=lambda: uuid7().hex
    )
    workspace_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("workspaces.id", ondelete="RESTRICT"),
        nullable=False,
    )
    agent_id: Mapped[str] = mapped_column(
        sa.String(32), sa.ForeignKey("agents.id", ondelete="RESTRICT"), nullable=False
    )
    session_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("agent_sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    slug: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    title: Mapped[str] = mapped_column(sa.Text, nullable=False)
    objective: Mapped[str] = mapped_column(sa.Text, nullable=False)
    sources: Mapped[list[dict[str, JSONValue]]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime, init=False, nullable=False, server_default=sa.func.now()
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime,
        init=False,
        nullable=False,
        server_default=sa.func.now(),
        onupdate=sa.func.now(),
    )

    __table_args__ = (UQ_SESSION_SLUG, IX_SESSION_ID, IX_AGENT_ID)


class RDBRoutineWorkRecord(RDBModel):
    """Latest retained completed work, never a pending-notification outbox."""

    __tablename__ = "routine_work_records"

    UQ_EXECUTION_ID = sa.UniqueConstraint(
        "execution_id", name="uq_routine_work_records_execution_id"
    )
    IX_ROUTINE_RECENCY = sa.Index(
        "ix_routine_work_records_recency", "routine_id", "completed_at", "id"
    )
    IX_SESSION_ID = sa.Index("ix_routine_work_records_session_id", "session_id")
    CK_NOTIFICATION_MESSAGE = sa.CheckConstraint(
        "(notify AND message IS NOT NULL) OR (NOT notify AND message IS NULL)",
        name="ck_routine_work_records_notification_message",
    )
    CK_DELIVERY_CHOICE = sa.CheckConstraint(
        "(NOT notify AND delivery_status = 'not_requested') OR "
        "(notify AND delivery_status <> 'not_requested')",
        name="ck_routine_work_records_delivery_choice",
    )

    id: Mapped[str] = mapped_column(
        sa.String(32), primary_key=True, init=False, default_factory=lambda: uuid7().hex
    )
    routine_id: Mapped[str] = mapped_column(
        sa.String(32), sa.ForeignKey("routines.id", ondelete="CASCADE"), nullable=False
    )
    session_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("agent_sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    execution_id: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    started_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime, nullable=False
    )
    objective_outcome: Mapped[RoutineObjectiveOutcome] = mapped_column(
        routine_objective_outcome_enum, nullable=False
    )
    result: Mapped[str] = mapped_column(sa.Text, nullable=False)
    next_hint: Mapped[str] = mapped_column(sa.Text, nullable=False)
    notify: Mapped[bool] = mapped_column(sa.Boolean, nullable=False)
    message: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    delivery_status: Mapped[RoutineDeliveryStatus] = mapped_column(
        routine_delivery_status_enum, nullable=False
    )
    delivery_error: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    completed_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime, init=False, nullable=False, server_default=sa.func.now()
    )

    __table_args__ = (
        UQ_EXECUTION_ID,
        IX_ROUTINE_RECENCY,
        IX_SESSION_ID,
        CK_NOTIFICATION_MESSAGE,
        CK_DELIVERY_CHOICE,
    )
