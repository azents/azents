"""System Settings service data models."""

from dataclasses import dataclass
from typing import Any

from azents.core.system_setting import (
    ResolvedSystemSetting,
    SystemDataMigrationOutcome,
    SystemSettingHealthStatus,
    SystemSettingSecretAction,
    SystemSettingSection,
    SystemSettingValidationStatus,
)
from azents.repos.system_setting.data import (
    StoredSystemSetting,
    StoredSystemSettingCandidate,
    StoredSystemSettingHealth,
)


@dataclass(frozen=True)
class SystemSettingMutation:
    """Internal complete Section mutation request."""

    section: SystemSettingSection
    expected_version: int
    config_patch: dict[str, Any]
    secret_actions: dict[str, SystemSettingSecretAction]
    actor_user_id: str | None


@dataclass(frozen=True)
class SystemSettingActivated:
    """Directly activated current Section result."""

    current: StoredSystemSetting
    resolved: ResolvedSystemSetting


@dataclass(frozen=True)
class SystemSettingCandidatePending:
    """Candidate stored for external validation."""

    candidate: StoredSystemSettingCandidate
    resolved: ResolvedSystemSetting


SystemSettingMutationResult = SystemSettingActivated | SystemSettingCandidatePending


@dataclass(frozen=True)
class SystemSettingCandidateValidationSnapshot:
    """Current and candidate effective payloads prepared for validation."""

    candidate: StoredSystemSettingCandidate
    current_resolved: ResolvedSystemSetting
    candidate_resolved: ResolvedSystemSetting


@dataclass(frozen=True)
class SystemSettingCandidateValidationResult:
    """Sanitized external validation and confirmation requirement."""

    status: SystemSettingValidationStatus
    code: str | None
    message: str | None
    action_hint: str | None
    metadata: dict[str, Any] | None
    impact: dict[str, Any] | None
    confirmation_required: bool


@dataclass(frozen=True)
class SystemSettingState:
    """Current internal Section state for a redacted domain projection."""

    current: StoredSystemSetting | None
    candidate: StoredSystemSettingCandidate | None
    resolved: ResolvedSystemSetting
    health: StoredSystemSettingHealth | None


@dataclass(frozen=True)
class SystemSettingHealthResult:
    """Sanitized explicit health result to persist."""

    status: SystemSettingHealthStatus
    code: str | None
    message: str | None
    action_hint: str | None
    metadata: dict[str, Any] | None


@dataclass(frozen=True)
class CurrentSystemSettingHealth:
    """Health state matched to the currently resolved generation."""

    resolved: ResolvedSystemSetting
    health: StoredSystemSettingHealth | None


@dataclass(frozen=True)
class SystemDataMigrationResult:
    """Completed application migration result."""

    outcome: SystemDataMigrationOutcome
    metadata: dict[str, Any]
