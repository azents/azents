"""Scheduled task state model."""

import datetime
import enum
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ENUM, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from azents.core.enums import ScheduledTaskStatus
from azents.rdb.models.base import RDBModel
from azents.rdb.types.datetime import TimeZoneDateTime


def _enum_values(enum_cls: type[enum.StrEnum]) -> list[str]:
    """Return StrEnum values stored in the DB."""
    return [v.value for v in enum_cls]


scheduled_task_status_enum = ENUM(
    ScheduledTaskStatus,
    name="scheduled_task_status",
    create_type=False,
    values_callable=_enum_values,
)


class RDBScheduledTaskState(RDBModel):
    """Current runtime state for a code-registered scheduled task."""

    __tablename__ = "scheduled_task_states"

    IX_NEXT_RUN_AT = sa.Index("ix_scheduled_task_states_next_run_at", "next_run_at")
    IX_LEASE_UNTIL = sa.Index("ix_scheduled_task_states_lease_until", "lease_until")

    task_key: Mapped[str] = mapped_column(sa.String(120), primary_key=True)
    latest_status: Mapped[ScheduledTaskStatus] = mapped_column(
        scheduled_task_status_enum,
        init=False,
        nullable=False,
        server_default=ScheduledTaskStatus.IDLE.value,
    )
    next_run_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime,
        nullable=False,
    )
    last_started_at: Mapped[datetime.datetime | None] = mapped_column(
        TimeZoneDateTime,
        init=False,
        nullable=True,
        default=None,
    )
    last_finished_at: Mapped[datetime.datetime | None] = mapped_column(
        TimeZoneDateTime,
        init=False,
        nullable=True,
        default=None,
    )
    last_succeeded_at: Mapped[datetime.datetime | None] = mapped_column(
        TimeZoneDateTime,
        init=False,
        nullable=True,
        default=None,
    )
    last_failed_at: Mapped[datetime.datetime | None] = mapped_column(
        TimeZoneDateTime,
        init=False,
        nullable=True,
        default=None,
    )
    failure_streak: Mapped[int] = mapped_column(
        sa.Integer,
        init=False,
        nullable=False,
        server_default="0",
    )
    latest_error_code: Mapped[str | None] = mapped_column(
        sa.String(120),
        init=False,
        nullable=True,
        default=None,
    )
    latest_error_message: Mapped[str | None] = mapped_column(
        sa.Text,
        init=False,
        nullable=True,
        default=None,
    )
    latest_result_summary: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB,
        init=False,
        nullable=True,
        default=None,
    )
    lease_owner: Mapped[str | None] = mapped_column(
        sa.String(120),
        init=False,
        nullable=True,
        default=None,
    )
    leased_at: Mapped[datetime.datetime | None] = mapped_column(
        TimeZoneDateTime,
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
    manual_requested_at: Mapped[datetime.datetime | None] = mapped_column(
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

    __table_args__ = (IX_NEXT_RUN_AT, IX_LEASE_UNTIL)
