"""System Settings repository data models."""

import datetime
from dataclasses import dataclass
from typing import Any

from azents.core.system_setting import (
    SystemDataMigrationOutcome,
    SystemSettingAuditEventType,
    SystemSettingAuditSource,
    SystemSettingHealthStatus,
    SystemSettingSection,
    SystemSettingValidationStatus,
)


@dataclass(frozen=True)
class StoredSystemSetting:
    """Current stored Admin-managed Section base."""

    section: SystemSettingSection
    schema_version: int
    version: int
    config: dict[str, Any]
    encrypted_secrets: str | None
    secret_metadata: dict[str, Any]
    validation_status: SystemSettingValidationStatus | None
    validated_generation: str | None
    validation_metadata: dict[str, Any] | None
    validated_at: datetime.datetime | None
    updated_by_user_id: str | None
    created_at: datetime.datetime
    updated_at: datetime.datetime


@dataclass(frozen=True)
class StoredSystemSettingCandidate:
    """Stored pending Section candidate."""

    id: str
    section: SystemSettingSection
    schema_version: int
    base_version: int
    config: dict[str, Any]
    encrypted_secrets: str | None
    secret_metadata: dict[str, Any]
    validation_status: SystemSettingValidationStatus
    validated_generation: str | None
    validation_code: str | None
    validation_message: str | None
    action_hint: str | None
    validation_metadata: dict[str, Any] | None
    impact: dict[str, Any] | None
    created_by_user_id: str | None
    created_at: datetime.datetime
    updated_at: datetime.datetime
    expires_at: datetime.datetime


@dataclass(frozen=True)
class SystemSettingCandidateCreate:
    """Complete values for replacing one Section candidate."""

    id: str
    section: SystemSettingSection
    schema_version: int
    base_version: int
    config: dict[str, Any]
    encrypted_secrets: str | None
    secret_metadata: dict[str, Any]
    validation_status: SystemSettingValidationStatus
    created_by_user_id: str | None
    created_at: datetime.datetime
    updated_at: datetime.datetime
    expires_at: datetime.datetime


@dataclass(frozen=True)
class SystemSettingCurrentWrite:
    """Complete values for replacing current Section state."""

    section: SystemSettingSection
    schema_version: int
    version: int
    config: dict[str, Any]
    encrypted_secrets: str | None
    secret_metadata: dict[str, Any]
    validation_status: SystemSettingValidationStatus | None
    validated_generation: str | None
    validation_metadata: dict[str, Any] | None
    validated_at: datetime.datetime | None
    updated_by_user_id: str | None


@dataclass(frozen=True)
class StoredSystemSettingHealth:
    """Stored explicit health result."""

    section: SystemSettingSection
    effective_generation: str
    status: SystemSettingHealthStatus
    code: str | None
    message: str | None
    action_hint: str | None
    metadata: dict[str, Any] | None
    checked_by_user_id: str | None
    checked_at: datetime.datetime


@dataclass(frozen=True)
class SystemSettingHealthWrite:
    """Complete latest health result values."""

    section: SystemSettingSection
    effective_generation: str
    status: SystemSettingHealthStatus
    code: str | None
    message: str | None
    action_hint: str | None
    metadata: dict[str, Any] | None
    checked_by_user_id: str | None
    checked_at: datetime.datetime


@dataclass(frozen=True)
class StoredSystemSettingAuditEvent:
    """Stored metadata-only audit event."""

    id: str
    section: SystemSettingSection
    event_type: SystemSettingAuditEventType
    source: SystemSettingAuditSource
    previous_version: int | None
    new_version: int | None
    actor_user_id: str | None
    changed_fields: list[str]
    secret_actions: dict[str, str]
    validation_status: SystemSettingValidationStatus | None
    candidate_id: str | None
    impact_confirmed: bool
    confirmation_action: str | None
    metadata: dict[str, Any] | None
    created_at: datetime.datetime


@dataclass(frozen=True)
class SystemSettingAuditEventCreate:
    """Metadata-only audit event values."""

    section: SystemSettingSection
    event_type: SystemSettingAuditEventType
    source: SystemSettingAuditSource
    previous_version: int | None
    new_version: int | None
    actor_user_id: str | None
    changed_fields: list[str]
    secret_actions: dict[str, str]
    validation_status: SystemSettingValidationStatus | None
    candidate_id: str | None
    impact_confirmed: bool
    confirmation_action: str | None
    metadata: dict[str, Any] | None
    created_at: datetime.datetime


@dataclass(frozen=True)
class SystemSettingAuditEventList:
    """Paginated audit event page."""

    items: list[StoredSystemSettingAuditEvent]
    total: int


@dataclass(frozen=True)
class StoredSystemDataMigration:
    """Stored application data-migration marker."""

    name: str
    outcome: SystemDataMigrationOutcome
    metadata: dict[str, Any]
    completed_at: datetime.datetime
