"""Scheduled Task persistence model."""

import datetime
import enum

import sqlalchemy as sa
from azcommon.uuid import uuid7
from sqlalchemy.dialects.postgresql import ENUM
from sqlalchemy.orm import Mapped, mapped_column

from azents.core.enums import ScheduledTaskScheduleType
from azents.rdb.models.base import RDBModel
from azents.rdb.types.datetime import TimeZoneDateTime


def _enum_values(enum_cls: type[enum.StrEnum]) -> list[str]:
    """Return StrEnum values stored in PostgreSQL."""
    return [value.value for value in enum_cls]


scheduled_task_schedule_type_enum = ENUM(
    ScheduledTaskScheduleType,
    name="scheduled_task_schedule_type",
    create_type=False,
    values_callable=_enum_values,
)


class RDBScheduledTask(RDBModel):
    """One durable Scheduled Task definition and cursor owned by a Session."""

    __tablename__ = "scheduled_tasks"

    FK_WORKSPACE = sa.ForeignKeyConstraint(
        ["workspace_id"],
        ["workspaces.id"],
        name="fk_scheduled_tasks_workspace_id",
        ondelete="RESTRICT",
    )
    FK_AGENT = sa.ForeignKeyConstraint(
        ["agent_id"],
        ["agents.id"],
        name="fk_scheduled_tasks_agent_id",
        ondelete="RESTRICT",
    )
    FK_SESSION = sa.ForeignKeyConstraint(
        ["session_id"],
        ["agent_sessions.id"],
        name="fk_scheduled_tasks_session_id",
        ondelete="RESTRICT",
    )
    FK_BINDING = sa.ForeignKeyConstraint(
        ["binding_id"],
        ["external_channel_bindings.id"],
        name="fk_scheduled_tasks_binding_id",
        ondelete="RESTRICT",
    )
    CK_SCHEDULE_SHAPE = sa.CheckConstraint(
        "("
        "(schedule_type = 'once' "
        "AND scheduled_at IS NOT NULL "
        "AND cron_expression IS NULL "
        "AND timezone IS NULL) "
        "OR "
        "(schedule_type = 'cron' "
        "AND scheduled_at IS NULL "
        "AND cron_expression IS NOT NULL "
        "AND timezone IS NOT NULL)"
        ")",
        name="ck_scheduled_tasks_schedule_shape",
    )
    CK_ACTIVE_CYCLE_FENCE = sa.CheckConstraint(
        "("
        "(active_cycle_id IS NULL AND active_scheduled_for IS NULL) "
        "OR "
        "(active_cycle_id IS NOT NULL AND active_scheduled_for IS NOT NULL)"
        ")",
        name="ck_scheduled_tasks_active_cycle_fence",
    )
    CK_PENDING_OCCURRENCE = sa.CheckConstraint(
        "("
        "pending_scheduled_for IS NULL "
        "OR (schedule_type = 'cron' AND active_cycle_id IS NOT NULL)"
        ")",
        name="ck_scheduled_tasks_pending_occurrence",
    )
    IX_NEXT_ELIGIBLE_ID = sa.Index(
        "ix_scheduled_tasks_next_eligible_at_id",
        "next_eligible_at",
        "id",
    )
    IX_SESSION_ID = sa.Index("ix_scheduled_tasks_session_id", "session_id")
    IX_BINDING_ID = sa.Index("ix_scheduled_tasks_binding_id", "binding_id")
    IX_ACTIVE_CYCLE_ID = sa.Index(
        "ix_scheduled_tasks_active_cycle_id",
        "active_cycle_id",
    )

    id: Mapped[str] = mapped_column(
        sa.String(32),
        primary_key=True,
        init=False,
        default_factory=lambda: uuid7().hex,
    )
    workspace_id: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    agent_id: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    session_id: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    title: Mapped[str] = mapped_column(sa.String(120), nullable=False)
    objective: Mapped[str] = mapped_column(sa.Text, nullable=False)
    schedule_type: Mapped[ScheduledTaskScheduleType] = mapped_column(
        scheduled_task_schedule_type_enum,
        nullable=False,
    )
    next_eligible_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime,
        nullable=False,
    )
    binding_id: Mapped[str | None] = mapped_column(
        sa.String(32),
        nullable=True,
        default=None,
    )
    scheduled_at: Mapped[datetime.datetime | None] = mapped_column(
        TimeZoneDateTime,
        nullable=True,
        default=None,
    )
    cron_expression: Mapped[str | None] = mapped_column(
        sa.String(100),
        nullable=True,
        default=None,
    )
    timezone: Mapped[str | None] = mapped_column(
        sa.String(64),
        nullable=True,
        default=None,
    )
    active_cycle_id: Mapped[str | None] = mapped_column(
        sa.String(32),
        nullable=True,
        default=None,
    )
    active_scheduled_for: Mapped[datetime.datetime | None] = mapped_column(
        TimeZoneDateTime,
        nullable=True,
        default=None,
    )
    pending_scheduled_for: Mapped[datetime.datetime | None] = mapped_column(
        TimeZoneDateTime,
        nullable=True,
        default=None,
    )
    lease_owner: Mapped[str | None] = mapped_column(
        sa.String(120),
        nullable=True,
        default=None,
    )
    lease_until: Mapped[datetime.datetime | None] = mapped_column(
        TimeZoneDateTime,
        nullable=True,
        default=None,
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime,
        init=False,
        server_default=sa.func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime,
        init=False,
        server_default=sa.func.now(),
        onupdate=sa.func.now(),
        nullable=False,
    )

    __table_args__ = (
        FK_WORKSPACE,
        FK_AGENT,
        FK_SESSION,
        FK_BINDING,
        CK_SCHEDULE_SHAPE,
        CK_ACTIVE_CYCLE_FENCE,
        CK_PENDING_OCCURRENCE,
        IX_NEXT_ELIGIBLE_ID,
        IX_SESSION_ID,
        IX_BINDING_ID,
        IX_ACTIVE_CYCLE_ID,
    )
