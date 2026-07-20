"""Platform GitHub App System Settings service data."""

import datetime
import enum
from dataclasses import dataclass
from typing import Any

from azents.core.system_setting import (
    SystemSettingFieldSource,
    SystemSettingHealthStatus,
    SystemSettingValidationStatus,
)
from azents.repos.system_setting.data import StoredSystemSettingAuditEvent


class PlatformGitHubAppEffectiveStatus(enum.StrEnum):
    """Redacted effective configuration status."""

    NOT_CONFIGURED = "not_configured"
    INCOMPLETE = "incomplete"
    INVALID = "invalid"
    READY = "ready"
    UNAVAILABLE = "unavailable"
    RECONNECT_REQUIRED = "reconnect_required"


@dataclass(frozen=True)
class PlatformGitHubAppFieldState:
    """Redacted current field state."""

    name: str
    secret: bool
    value: str | None
    configured: bool
    source: SystemSettingFieldSource
    environment_variable: str
    fallback_configured: bool
    fallback_last_changed_at: datetime.datetime | None


@dataclass(frozen=True)
class PlatformGitHubAppCandidateState:
    """Redacted pending candidate state."""

    id: str
    base_version: int
    validation_status: SystemSettingValidationStatus
    validation_code: str | None
    validation_message: str | None
    action_hint: str | None
    impact: dict[str, Any] | None
    created_at: datetime.datetime
    updated_at: datetime.datetime
    expires_at: datetime.datetime


@dataclass(frozen=True)
class PlatformGitHubAppHealthState:
    """Redacted current-effective health state."""

    status: SystemSettingHealthStatus
    code: str | None
    message: str | None
    action_hint: str | None
    metadata: dict[str, Any] | None
    checked_at: datetime.datetime


@dataclass(frozen=True)
class PlatformGitHubAppBindingState:
    """Redacted resources that require reconnect for the effective App."""

    affected_user_count: int
    affected_installation_count: int
    affected_toolkit_count: int
    affected_agent_count: int

    @property
    def reconnect_required(self) -> bool:
        """Return whether any persisted resource has an incompatible identity."""
        return self.affected_installation_count > 0 or self.affected_toolkit_count > 0


@dataclass(frozen=True)
class PlatformGitHubAppDetail:
    """Redacted Admin detail projection."""

    section: str
    schema_version: int
    admin_version: int
    effective_status: PlatformGitHubAppEffectiveStatus
    fields: tuple[PlatformGitHubAppFieldState, ...]
    candidate: PlatformGitHubAppCandidateState | None
    health: PlatformGitHubAppHealthState | None
    binding_impact: PlatformGitHubAppBindingState | None
    activation_validation_status: SystemSettingValidationStatus | None
    app_slug: str | None


@dataclass(frozen=True)
class PlatformGitHubAppInventoryItem:
    """Generic System Settings inventory item."""

    section: str
    display_name: str
    effective_status: PlatformGitHubAppEffectiveStatus
    admin_version: int
    environment_managed_field_count: int
    candidate_status: SystemSettingValidationStatus | None


@dataclass(frozen=True)
class PlatformGitHubAppAuditPage:
    """Metadata-only audit page."""

    items: list[StoredSystemSettingAuditEvent]
    total: int
