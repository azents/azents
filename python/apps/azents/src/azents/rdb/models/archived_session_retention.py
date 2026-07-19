"""Archived-session retention persistence models."""

import datetime
import enum

import sqlalchemy as sa
from azcommon.uuid import uuid7
from sqlalchemy.dialects.postgresql import ENUM
from sqlalchemy.orm import Mapped, mapped_column

from azents.core.enums import (
    ArchivedSessionPurgeStatus,
    ArchivedSessionRetentionApplicationStatus,
)
from azents.rdb.models.base import RDBModel
from azents.rdb.types.datetime import TimeZoneDateTime


def _enum_values(enum_cls: type[enum.StrEnum]) -> list[str]:
    """Return StrEnum values stored in the DB."""
    return [value.value for value in enum_cls]


retention_application_status_enum = ENUM(
    ArchivedSessionRetentionApplicationStatus,
    name="archived_session_retention_application_status",
    create_type=False,
    values_callable=_enum_values,
)

purge_status_enum = ENUM(
    ArchivedSessionPurgeStatus,
    name="archived_session_purge_status",
    create_type=False,
    values_callable=_enum_values,
)


class RDBSystemFileLifecycleSetting(RDBModel):
    """Singleton instance-wide file lifecycle settings."""

    __tablename__ = "system_file_lifecycle_settings"

    CK_SINGLETON_ID = sa.CheckConstraint(
        "id = 1",
        name="ck_system_file_lifecycle_settings_singleton_id",
    )
    CK_ARCHIVED_SESSION_RETENTION_DAYS = sa.CheckConstraint(
        "archived_session_retention_days IS NULL "
        "OR archived_session_retention_days >= 0",
        name="ck_system_file_lifecycle_settings_retention_days",
    )

    id: Mapped[int] = mapped_column(
        sa.SmallInteger,
        primary_key=True,
        init=False,
        server_default="1",
    )
    archived_session_retention_days: Mapped[int | None] = mapped_column(
        sa.Integer,
        nullable=True,
        server_default="30",
    )
    updated_by_user_id: Mapped[str | None] = mapped_column(
        sa.String(32),
        sa.ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    revision: Mapped[int] = mapped_column(
        sa.BigInteger,
        init=False,
        nullable=False,
        server_default="1",
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
        CK_SINGLETON_ID,
        CK_ARCHIVED_SESSION_RETENTION_DAYS,
    )


class RDBArchivedSessionRetentionApplication(RDBModel):
    """Durable application of one retention revision to existing archives."""

    __tablename__ = "archived_session_retention_applications"

    CK_TARGET_RETENTION_DAYS = sa.CheckConstraint(
        "target_retention_days IS NULL OR target_retention_days >= 0",
        name="ck_archived_session_retention_applications_target_days",
    )
    IX_STATUS_CREATED_AT = sa.Index(
        "ix_archived_session_retention_applications_status_created_at",
        "status",
        "created_at",
    )
    IX_LEASE_UNTIL = sa.Index(
        "ix_archived_session_retention_applications_lease_until",
        "lease_until",
    )
    UQ_ACTIVE = sa.Index(
        "uq_archived_session_retention_applications_active",
        sa.literal_column("1"),
        unique=True,
        postgresql_where=sa.text("status IN ('pending', 'running', 'retry_wait')"),
    )

    id: Mapped[str] = mapped_column(
        sa.String(32),
        primary_key=True,
        init=False,
        default_factory=lambda: uuid7().hex,
    )
    target_revision: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    target_retention_days: Mapped[int | None] = mapped_column(
        sa.Integer,
        nullable=True,
    )
    requested_by_user_id: Mapped[str | None] = mapped_column(
        sa.String(32),
        sa.ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    status: Mapped[ArchivedSessionRetentionApplicationStatus] = mapped_column(
        retention_application_status_enum,
        init=False,
        nullable=False,
        server_default=ArchivedSessionRetentionApplicationStatus.PENDING.value,
    )
    cursor_session_id: Mapped[str | None] = mapped_column(
        sa.String(32),
        init=False,
        nullable=True,
        default=None,
    )
    affected_count: Mapped[int] = mapped_column(
        sa.Integer, init=False, nullable=False, server_default="0"
    )
    immediately_eligible_count: Mapped[int] = mapped_column(
        sa.Integer, init=False, nullable=False, server_default="0"
    )
    cancelled_count: Mapped[int] = mapped_column(
        sa.Integer, init=False, nullable=False, server_default="0"
    )
    scheduled_count: Mapped[int] = mapped_column(
        sa.Integer, init=False, nullable=False, server_default="0"
    )
    skipped_count: Mapped[int] = mapped_column(
        sa.Integer, init=False, nullable=False, server_default="0"
    )
    attempt_count: Mapped[int] = mapped_column(
        sa.Integer, init=False, nullable=False, server_default="0"
    )
    lease_owner: Mapped[str | None] = mapped_column(
        sa.String(120), init=False, nullable=True, default=None
    )
    lease_until: Mapped[datetime.datetime | None] = mapped_column(
        TimeZoneDateTime, init=False, nullable=True, default=None
    )
    next_attempt_at: Mapped[datetime.datetime | None] = mapped_column(
        TimeZoneDateTime, init=False, nullable=True, default=None
    )
    last_error_kind: Mapped[str | None] = mapped_column(
        sa.String(120), init=False, nullable=True, default=None
    )
    last_error_summary: Mapped[str | None] = mapped_column(
        sa.Text, init=False, nullable=True, default=None
    )
    started_at: Mapped[datetime.datetime | None] = mapped_column(
        TimeZoneDateTime, init=False, nullable=True, default=None
    )
    completed_at: Mapped[datetime.datetime | None] = mapped_column(
        TimeZoneDateTime, init=False, nullable=True, default=None
    )
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

    __table_args__ = (
        CK_TARGET_RETENTION_DAYS,
        IX_STATUS_CREATED_AT,
        IX_LEASE_UNTIL,
        UQ_ACTIVE,
    )


class RDBArchivedSessionPurgeJob(RDBModel):
    """Durable purge work and content-free terminal tombstone for one root."""

    __tablename__ = "archived_session_purge_jobs"

    IX_STATUS_ELIGIBLE_AT = sa.Index(
        "ix_archived_session_purge_jobs_status_eligible_at",
        "status",
        "eligible_at",
    )
    IX_LEASE_UNTIL = sa.Index(
        "ix_archived_session_purge_jobs_lease_until",
        "lease_until",
    )
    UQ_ROOT_SESSION_ID = sa.UniqueConstraint(
        "root_session_id",
        name="uq_archived_session_purge_jobs_root_session_id",
    )

    id: Mapped[str] = mapped_column(
        sa.String(32),
        primary_key=True,
        init=False,
        default_factory=lambda: uuid7().hex,
    )
    root_session_id: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    eligible_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime,
        nullable=False,
    )
    policy_revision: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    status: Mapped[ArchivedSessionPurgeStatus] = mapped_column(
        purge_status_enum,
        init=False,
        nullable=False,
        server_default=ArchivedSessionPurgeStatus.PENDING.value,
    )
    fencing_started_at: Mapped[datetime.datetime | None] = mapped_column(
        TimeZoneDateTime, init=False, nullable=True, default=None
    )
    attempt_count: Mapped[int] = mapped_column(
        sa.Integer, init=False, nullable=False, server_default="0"
    )
    lease_owner: Mapped[str | None] = mapped_column(
        sa.String(120), init=False, nullable=True, default=None
    )
    lease_until: Mapped[datetime.datetime | None] = mapped_column(
        TimeZoneDateTime, init=False, nullable=True, default=None
    )
    next_attempt_at: Mapped[datetime.datetime | None] = mapped_column(
        TimeZoneDateTime, init=False, nullable=True, default=None
    )
    last_error_kind: Mapped[str | None] = mapped_column(
        sa.String(120), init=False, nullable=True, default=None
    )
    last_error_summary: Mapped[str | None] = mapped_column(
        sa.Text, init=False, nullable=True, default=None
    )
    model_file_count: Mapped[int] = mapped_column(
        sa.Integer, init=False, nullable=False, server_default="0"
    )
    artifact_count: Mapped[int] = mapped_column(
        sa.Integer, init=False, nullable=False, server_default="0"
    )
    exchange_file_count: Mapped[int] = mapped_column(
        sa.Integer, init=False, nullable=False, server_default="0"
    )
    worktree_count: Mapped[int] = mapped_column(
        sa.Integer, init=False, nullable=False, server_default="0"
    )
    started_at: Mapped[datetime.datetime | None] = mapped_column(
        TimeZoneDateTime, init=False, nullable=True, default=None
    )
    last_attempt_at: Mapped[datetime.datetime | None] = mapped_column(
        TimeZoneDateTime, init=False, nullable=True, default=None
    )
    cancelled_at: Mapped[datetime.datetime | None] = mapped_column(
        TimeZoneDateTime, init=False, nullable=True, default=None
    )
    completed_at: Mapped[datetime.datetime | None] = mapped_column(
        TimeZoneDateTime, init=False, nullable=True, default=None
    )
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

    __table_args__ = (IX_STATUS_ELIGIBLE_AT, IX_LEASE_UNTIL, UQ_ROOT_SESSION_ID)
