"""Runtime Provider authentication binding persistence contracts."""

import datetime
from dataclasses import dataclass
from typing import Any

from azents.core.enums import (
    RuntimeProviderAuthMethod,
    RuntimeProviderBindingAuditEventType,
    RuntimeProviderBindingOwner,
    RuntimeProviderBindingState,
)


@dataclass(frozen=True)
class RuntimeProviderAuthBinding:
    """Persisted Provider authentication binding projection."""

    id: str
    provider_id: str
    auth_method: RuntimeProviderAuthMethod
    subject: str
    state: RuntimeProviderBindingState
    owner: RuntimeProviderBindingOwner
    bootstrap_declaration_id: str | None
    config: dict[str, Any] | None
    admin_version: int
    last_authenticated_at: datetime.datetime | None
    last_connected_at: datetime.datetime | None
    revoked_at: datetime.datetime | None
    revoked_by_user_id: str | None
    revocation_reason: str | None
    created_at: datetime.datetime
    updated_at: datetime.datetime


@dataclass(frozen=True)
class RuntimeProviderAuthBindingCreate:
    """Values required to create a Provider authentication binding."""

    provider_id: str
    auth_method: RuntimeProviderAuthMethod
    subject: str
    owner: RuntimeProviderBindingOwner
    bootstrap_declaration_id: str | None
    config: dict[str, Any] | None


@dataclass(frozen=True)
class RuntimeProviderAuthBindingRevoke:
    """Values required to revoke a binding with optimistic concurrency."""

    binding_id: str
    expected_admin_version: int
    revoked_at: datetime.datetime
    revoked_by_user_id: str | None
    reason: str | None


@dataclass(frozen=True)
class RuntimeProviderAuthBindingAuditEvent:
    """Persisted metadata-only authentication binding audit event."""

    id: str
    binding_id: str
    event_type: RuntimeProviderBindingAuditEventType
    actor_user_id: str | None
    previous_admin_version: int | None
    new_admin_version: int | None
    metadata: dict[str, Any] | None
    created_at: datetime.datetime


@dataclass(frozen=True)
class RuntimeProviderAuthBindingAuditEventCreate:
    """Values required to append a binding audit event."""

    binding_id: str
    event_type: RuntimeProviderBindingAuditEventType
    actor_user_id: str | None
    previous_admin_version: int | None
    new_admin_version: int | None
    metadata: dict[str, Any] | None
    created_at: datetime.datetime
