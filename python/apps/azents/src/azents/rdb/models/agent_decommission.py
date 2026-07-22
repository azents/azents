"""Durable Agent decommission job model."""

import datetime
import enum

import sqlalchemy as sa
from azcommon.uuid import uuid7
from sqlalchemy.dialects.postgresql import ENUM
from sqlalchemy.orm import Mapped, mapped_column

from azents.core.enums import AgentDecommissionStatus
from azents.rdb.models.base import RDBModel
from azents.rdb.types.datetime import TimeZoneDateTime


def _enum_values(enum_cls: type[enum.StrEnum]) -> list[str]:
    """Return enum values stored in PostgreSQL."""
    return [value.value for value in enum_cls]


agent_decommission_status_enum = ENUM(
    AgentDecommissionStatus,
    name="agent_decommission_status",
    create_type=False,
    values_callable=_enum_values,
)


class RDBAgentDecommissionJob(RDBModel):
    """Content-free durable Agent decommission state."""

    __tablename__ = "agent_decommission_jobs"

    UQ_AGENT_ID = sa.UniqueConstraint(
        "agent_id",
        name="uq_agent_decommission_jobs_agent_id",
    )
    IX_STATUS_NEXT_ATTEMPT_AT = sa.Index(
        "ix_agent_decommission_jobs_status_next_attempt_at",
        "status",
        "next_attempt_at",
    )

    id: Mapped[str] = mapped_column(
        sa.String(32),
        primary_key=True,
        init=False,
        default_factory=lambda: uuid7().hex,
    )
    agent_id: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    workspace_id: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    requested_by_workspace_user_id: Mapped[str | None] = mapped_column(
        sa.String(32),
        nullable=True,
        default=None,
    )
    status: Mapped[AgentDecommissionStatus] = mapped_column(
        agent_decommission_status_enum,
        init=False,
        nullable=False,
        server_default=AgentDecommissionStatus.PENDING.value,
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

    __table_args__ = (UQ_AGENT_ID, IX_STATUS_NEXT_ATTEMPT_AT)
