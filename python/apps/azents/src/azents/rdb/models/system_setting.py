"""Instance System Settings persistence models."""

import datetime
import enum
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ENUM, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from azents.core.system_setting import (
    SystemDataMigrationOutcome,
    SystemSettingAuditEventType,
    SystemSettingAuditSource,
    SystemSettingHealthStatus,
    SystemSettingSection,
    SystemSettingValidationStatus,
)
from azents.rdb.models.base import RDBModel
from azents.rdb.types.datetime import TimeZoneDateTime


def _enum_values(enum_cls: type[enum.StrEnum]) -> list[str]:
    """Return StrEnum values stored in PostgreSQL."""
    return [value.value for value in enum_cls]


system_setting_section_enum = ENUM(
    SystemSettingSection,
    name="system_setting_section",
    create_type=False,
    values_callable=_enum_values,
)
system_setting_validation_status_enum = ENUM(
    SystemSettingValidationStatus,
    name="system_setting_validation_status",
    create_type=False,
    values_callable=_enum_values,
)
system_setting_health_status_enum = ENUM(
    SystemSettingHealthStatus,
    name="system_setting_health_status",
    create_type=False,
    values_callable=_enum_values,
)
system_setting_audit_event_type_enum = ENUM(
    SystemSettingAuditEventType,
    name="system_setting_audit_event_type",
    create_type=False,
    values_callable=_enum_values,
)
system_setting_audit_source_enum = ENUM(
    SystemSettingAuditSource,
    name="system_setting_audit_source",
    create_type=False,
    values_callable=_enum_values,
)
system_data_migration_outcome_enum = ENUM(
    SystemDataMigrationOutcome,
    name="system_data_migration_outcome",
    create_type=False,
    values_callable=_enum_values,
)


class RDBSystemSetting(RDBModel):
    """Current Admin-managed base value for one Section."""

    __tablename__ = "system_settings"

    section: Mapped[SystemSettingSection] = mapped_column(
        system_setting_section_enum,
        primary_key=True,
    )
    schema_version: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    version: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    encrypted_secrets: Mapped[str | None] = mapped_column(
        sa.Text,
        nullable=True,
        default=None,
    )
    secret_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default_factory=dict,
    )
    validation_status: Mapped[SystemSettingValidationStatus | None] = mapped_column(
        system_setting_validation_status_enum,
        nullable=True,
        default=None,
    )
    validated_generation: Mapped[str | None] = mapped_column(
        sa.String(64),
        nullable=True,
        default=None,
    )
    validation_metadata: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB,
        nullable=True,
        default=None,
    )
    validated_at: Mapped[datetime.datetime | None] = mapped_column(
        TimeZoneDateTime,
        nullable=True,
        default=None,
    )
    updated_by_user_id: Mapped[str | None] = mapped_column(
        sa.String(32),
        sa.ForeignKey("users.id", ondelete="SET NULL"),
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

    IX_UPDATED_BY_USER_ID = sa.Index(
        "ix_system_settings_updated_by_user_id",
        "updated_by_user_id",
    )

    __table_args__ = (IX_UPDATED_BY_USER_ID,)


class RDBSystemSettingCandidate(RDBModel):
    """Single pending candidate for one Section."""

    __tablename__ = "system_setting_candidates"

    id: Mapped[str] = mapped_column(sa.String(32), primary_key=True)
    section: Mapped[SystemSettingSection] = mapped_column(
        system_setting_section_enum,
        nullable=False,
    )
    schema_version: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    base_version: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    validation_status: Mapped[SystemSettingValidationStatus] = mapped_column(
        system_setting_validation_status_enum,
        nullable=False,
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime,
        nullable=False,
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime,
        nullable=False,
    )
    expires_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime,
        nullable=False,
    )
    encrypted_secrets: Mapped[str | None] = mapped_column(
        sa.Text,
        nullable=True,
        default=None,
    )
    secret_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default_factory=dict,
    )
    validated_generation: Mapped[str | None] = mapped_column(
        sa.String(64),
        nullable=True,
        default=None,
    )
    validation_code: Mapped[str | None] = mapped_column(
        sa.String(120),
        nullable=True,
        default=None,
    )
    validation_message: Mapped[str | None] = mapped_column(
        sa.Text,
        nullable=True,
        default=None,
    )
    action_hint: Mapped[str | None] = mapped_column(
        sa.Text,
        nullable=True,
        default=None,
    )
    validation_metadata: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB,
        nullable=True,
        default=None,
    )
    impact: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB,
        nullable=True,
        default=None,
    )
    created_by_user_id: Mapped[str | None] = mapped_column(
        sa.String(32),
        sa.ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        default=None,
    )

    UQ_SECTION = sa.UniqueConstraint(
        "section",
        name="uq_system_setting_candidates_section",
    )
    IX_CREATED_BY_USER_ID = sa.Index(
        "ix_system_setting_candidates_created_by_user_id",
        "created_by_user_id",
    )
    IX_EXPIRES_AT = sa.Index(
        "ix_system_setting_candidates_expires_at",
        "expires_at",
    )

    __table_args__ = (UQ_SECTION, IX_CREATED_BY_USER_ID, IX_EXPIRES_AT)


class RDBSystemSettingHealth(RDBModel):
    """Latest explicit health result for one effective Section generation."""

    __tablename__ = "system_setting_health"

    section: Mapped[SystemSettingSection] = mapped_column(
        system_setting_section_enum,
        primary_key=True,
    )
    effective_generation: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    status: Mapped[SystemSettingHealthStatus] = mapped_column(
        system_setting_health_status_enum,
        nullable=False,
    )
    checked_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime,
        nullable=False,
    )
    code: Mapped[str | None] = mapped_column(
        sa.String(120),
        nullable=True,
        default=None,
    )
    message: Mapped[str | None] = mapped_column(
        sa.Text,
        nullable=True,
        default=None,
    )
    action_hint: Mapped[str | None] = mapped_column(
        sa.Text,
        nullable=True,
        default=None,
    )
    result_metadata: Mapped[dict[str, Any] | None] = mapped_column(
        "metadata",
        JSONB,
        nullable=True,
        default=None,
    )
    checked_by_user_id: Mapped[str | None] = mapped_column(
        sa.String(32),
        sa.ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        default=None,
    )

    IX_CHECKED_BY_USER_ID = sa.Index(
        "ix_system_setting_health_checked_by_user_id",
        "checked_by_user_id",
    )

    __table_args__ = (IX_CHECKED_BY_USER_ID,)


class RDBSystemSettingAuditEvent(RDBModel):
    """Append-only metadata event for System Settings changes."""

    __tablename__ = "system_setting_audit_events"

    id: Mapped[str] = mapped_column(sa.String(32), primary_key=True)
    section: Mapped[SystemSettingSection] = mapped_column(
        system_setting_section_enum,
        nullable=False,
    )
    event_type: Mapped[SystemSettingAuditEventType] = mapped_column(
        system_setting_audit_event_type_enum,
        nullable=False,
    )
    source: Mapped[SystemSettingAuditSource] = mapped_column(
        system_setting_audit_source_enum,
        nullable=False,
    )
    changed_fields: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    secret_actions: Mapped[dict[str, str]] = mapped_column(JSONB, nullable=False)
    impact_confirmed: Mapped[bool] = mapped_column(sa.Boolean, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime,
        nullable=False,
    )
    previous_version: Mapped[int | None] = mapped_column(
        sa.Integer,
        nullable=True,
        default=None,
    )
    new_version: Mapped[int | None] = mapped_column(
        sa.Integer,
        nullable=True,
        default=None,
    )
    actor_user_id: Mapped[str | None] = mapped_column(
        sa.String(32),
        sa.ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        default=None,
    )
    validation_status: Mapped[SystemSettingValidationStatus | None] = mapped_column(
        system_setting_validation_status_enum,
        nullable=True,
        default=None,
    )
    candidate_id: Mapped[str | None] = mapped_column(
        sa.String(32),
        nullable=True,
        default=None,
    )
    confirmation_action: Mapped[str | None] = mapped_column(
        sa.String(120),
        nullable=True,
        default=None,
    )
    event_metadata: Mapped[dict[str, Any] | None] = mapped_column(
        "metadata",
        JSONB,
        nullable=True,
        default=None,
    )

    IX_SECTION_CREATED_AT = sa.Index(
        "ix_system_setting_audit_events_section_created_at",
        "section",
        sa.desc("created_at"),
    )
    IX_ACTOR_USER_ID = sa.Index(
        "ix_system_setting_audit_events_actor_user_id",
        "actor_user_id",
    )

    __table_args__ = (IX_SECTION_CREATED_AT, IX_ACTOR_USER_ID)


class RDBSystemDataMigration(RDBModel):
    """Completion marker for an application data migration."""

    __tablename__ = "system_data_migrations"

    name: Mapped[str] = mapped_column(sa.String(160), primary_key=True)
    outcome: Mapped[SystemDataMigrationOutcome] = mapped_column(
        system_data_migration_outcome_enum,
        nullable=False,
    )
    migration_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
    )
    completed_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime,
        nullable=False,
    )
