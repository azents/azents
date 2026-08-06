"""Durable owner-lifecycle job model."""

import datetime
import enum

import sqlalchemy as sa
from azcommon.uuid import uuid7
from sqlalchemy.dialects.postgresql import ENUM
from sqlalchemy.orm import Mapped, mapped_column

from azents.core.enums import OwnerLifecycleKind, OwnerLifecycleStatus
from azents.rdb.models.base import RDBModel
from azents.rdb.types.datetime import TimeZoneDateTime


def _enum_values(enum_cls: type[enum.StrEnum]) -> list[str]:
    """Return enum values stored in PostgreSQL."""
    return [value.value for value in enum_cls]


owner_lifecycle_kind_enum = ENUM(
    OwnerLifecycleKind,
    name="owner_lifecycle_kind",
    create_type=False,
    values_callable=_enum_values,
)

owner_lifecycle_status_enum = ENUM(
    OwnerLifecycleStatus,
    name="owner_lifecycle_status",
    create_type=False,
    values_callable=_enum_values,
)


class RDBOwnerLifecycleJob(RDBModel):
    """Content-free durable owner lifecycle state."""

    __tablename__ = "owner_lifecycle_jobs"

    UQ_MEMBERSHIP_ARCHIVE = sa.Index(
        "uq_owner_lifecycle_jobs_membership_archive",
        "workspace_id",
        "user_id",
        unique=True,
        postgresql_where=sa.text("kind = 'membership_archive'"),
    )
    UQ_ACCOUNT_PURGE = sa.Index(
        "uq_owner_lifecycle_jobs_account_purge",
        "user_id",
        unique=True,
        postgresql_where=sa.text("kind = 'account_purge'"),
    )
    IX_STATUS_NEXT_ATTEMPT_AT = sa.Index(
        "ix_owner_lifecycle_jobs_status_next_attempt_at",
        "status",
        "next_attempt_at",
    )

    id: Mapped[str] = mapped_column(
        sa.String(32),
        primary_key=True,
        init=False,
        default_factory=lambda: uuid7().hex,
    )
    kind: Mapped[OwnerLifecycleKind] = mapped_column(
        owner_lifecycle_kind_enum,
        nullable=False,
    )
    user_id: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    workspace_id: Mapped[str | None] = mapped_column(
        sa.String(32),
        nullable=True,
        default=None,
    )
    status: Mapped[OwnerLifecycleStatus] = mapped_column(
        owner_lifecycle_status_enum,
        init=False,
        nullable=False,
        server_default=OwnerLifecycleStatus.PENDING.value,
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
        UQ_MEMBERSHIP_ARCHIVE,
        UQ_ACCOUNT_PURGE,
        IX_STATUS_NEXT_ATTEMPT_AT,
        sa.CheckConstraint(
            "(kind = 'membership_archive' AND workspace_id IS NOT NULL) OR "
            "(kind = 'account_purge' AND workspace_id IS NULL)",
            name="ck_owner_lifecycle_jobs_kind_workspace",
        ),
    )
