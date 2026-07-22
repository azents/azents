"""Runtime Provider control persistence data contracts."""

import datetime
from dataclasses import dataclass

from azents.core.enums import (
    RuntimeProviderConnectionStatus,
    RuntimeProviderCredentialState,
    RuntimeProviderEnrollmentGrantState,
)


@dataclass(frozen=True)
class RuntimeProviderEnrollmentGrant:
    """Persisted one-time enrollment grant projection."""

    id: str
    provider_id: str
    verifier: str
    state: RuntimeProviderEnrollmentGrantState
    expires_at: datetime.datetime
    issued_by_user_id: str | None
    issued_by_source_id: str | None
    consumed_at: datetime.datetime | None
    consumed_credential_id: str | None
    revoked_at: datetime.datetime | None
    revoked_by_user_id: str | None
    created_at: datetime.datetime


@dataclass(frozen=True)
class RuntimeProviderEnrollmentGrantCreate:
    """Complete values for issuing one enrollment grant."""

    provider_id: str
    verifier: str
    expires_at: datetime.datetime
    issued_by_user_id: str | None
    issued_by_source_id: str | None


@dataclass(frozen=True)
class RuntimeProviderCredential:
    """Persisted verifier-backed credential projection."""

    id: str
    provider_id: str
    verifier: str
    state: RuntimeProviderCredentialState
    expires_at: datetime.datetime | None
    issued_grant_id: str
    last_used_at: datetime.datetime | None
    revoked_at: datetime.datetime | None
    revoked_by_user_id: str | None
    created_at: datetime.datetime


@dataclass(frozen=True)
class RuntimeProviderCredentialCreate:
    """Complete values for issuing one Provider credential."""

    provider_id: str
    verifier: str
    expires_at: datetime.datetime | None
    issued_grant_id: str


@dataclass(frozen=True)
class RuntimeProviderConnection:
    """Persisted authenticated Provider Control connection projection."""

    id: str
    provider_id: str
    credential_id: str
    connection_id: str
    generation: int
    status: RuntimeProviderConnectionStatus
    reported_provider_type: str
    reported_protocol_version: str
    connected_at: datetime.datetime
    last_heartbeat_at: datetime.datetime
    disconnected_at: datetime.datetime | None
    created_at: datetime.datetime


@dataclass(frozen=True)
class RuntimeProviderConnectionCreate:
    """Complete values for persisting one authenticated connection."""

    provider_id: str
    credential_id: str
    connection_id: str
    generation: int
    reported_provider_type: str
    reported_protocol_version: str
    connected_at: datetime.datetime
