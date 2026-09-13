"""Provider OAuth System Settings projections."""

import datetime
import enum
from dataclasses import dataclass

from azents.core.system_setting import (
    SystemSettingFieldSource,
    SystemSettingHealthStatus,
)


class ExternalAccountOAuthEffectiveStatus(enum.StrEnum):
    """Redacted provider OAuth configuration status."""

    NOT_CONFIGURED = "not_configured"
    INCOMPLETE = "incomplete"
    INVALID = "invalid"
    READY = "ready"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class ExternalAccountOAuthFieldState:
    """One redacted provider OAuth field."""

    name: str
    secret: bool
    value: str | None
    configured: bool
    source: SystemSettingFieldSource
    fallback_configured: bool
    fallback_last_changed_at: datetime.datetime | None


@dataclass(frozen=True)
class ExternalAccountOAuthHealthState:
    """Current provider OAuth health projection."""

    status: SystemSettingHealthStatus
    code: str | None
    message: str | None
    action_hint: str | None
    checked_at: datetime.datetime


@dataclass(frozen=True)
class ExternalAccountOAuthDetail:
    """Redacted provider OAuth System Settings detail."""

    section: str
    provider: str
    schema_version: int
    admin_version: int
    effective_status: ExternalAccountOAuthEffectiveStatus
    callback_url: str | None
    fields: tuple[ExternalAccountOAuthFieldState, ...]
    health: ExternalAccountOAuthHealthState | None
