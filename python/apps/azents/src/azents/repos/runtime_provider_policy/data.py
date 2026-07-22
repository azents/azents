"""Runtime Provider policy persistence data contracts."""

import datetime
from dataclasses import dataclass
from typing import Any

from azents.core.enums import (
    RuntimePolicySnapshotApplicationState,
    RuntimeProviderConfigRevisionState,
    RuntimeProviderConfigValidationStatus,
    RuntimeProviderContractStatus,
)


@dataclass(frozen=True)
class RuntimeProviderContractRevision:
    """Immutable persisted Provider capability contract revision."""

    id: str
    provider_id: str
    digest: str
    implementation_version: str
    protocol_version: str
    contract: dict[str, Any]
    compatibility: dict[str, Any]
    status: RuntimeProviderContractStatus
    validation_code: str | None
    validation_message: str | None
    accepted_by_user_id: str | None
    accepted_at: datetime.datetime | None
    rejected_by_user_id: str | None
    rejected_at: datetime.datetime | None
    created_at: datetime.datetime


@dataclass(frozen=True)
class RuntimeProviderContractRevisionCreate:
    """Complete values for storing a new immutable contract proposal."""

    provider_id: str
    digest: str
    implementation_version: str
    protocol_version: str
    contract: dict[str, Any]
    compatibility: dict[str, Any]
    status: RuntimeProviderContractStatus
    validation_code: str | None
    validation_message: str | None


@dataclass(frozen=True)
class RuntimeProviderConfigRevision:
    """Immutable persisted Provider product configuration revision."""

    id: str
    provider_id: str
    revision: int
    base_revision_id: str | None
    contract_revision_id: str
    config: dict[str, Any]
    encrypted_secrets: str | None
    secret_metadata: dict[str, Any]
    state: RuntimeProviderConfigRevisionState
    validation_status: RuntimeProviderConfigValidationStatus
    validation_request_id: str | None
    validation_code: str | None
    validation_message: str | None
    validation_metadata: dict[str, Any] | None
    impact: dict[str, Any] | None
    created_by_user_id: str | None
    activated_by_user_id: str | None
    activated_at: datetime.datetime | None
    created_at: datetime.datetime
    updated_at: datetime.datetime


@dataclass(frozen=True)
class RuntimeProviderConfigRevisionCreate:
    """Complete values for storing a Provider configuration candidate."""

    provider_id: str
    base_revision_id: str | None
    contract_revision_id: str
    config: dict[str, Any]
    encrypted_secrets: str | None
    secret_metadata: dict[str, Any]
    created_by_user_id: str | None
    validation_request_id: str | None


@dataclass(frozen=True)
class AgentRuntimeProviderOverride:
    """Versioned Agent-scoped Provider override document."""

    agent_id: str
    provider_id: str
    contract_revision_id: str
    version: int
    config: dict[str, Any]
    encrypted_secrets: str | None
    secret_metadata: dict[str, Any]
    validation_status: RuntimeProviderConfigValidationStatus
    updated_by_user_id: str | None
    created_at: datetime.datetime
    updated_at: datetime.datetime


@dataclass(frozen=True)
class RuntimePolicySnapshot:
    """Immutable effective Provider policy attached to a logical Runtime."""

    id: str
    runtime_id: str
    provider_id: str
    contract_revision_id: str
    config_revision_id: str | None
    override_provider_id: str | None
    override_version: int | None
    resolved_config: dict[str, Any]
    encrypted_secrets: str | None
    secret_metadata: dict[str, Any]
    source_trace: dict[str, Any]
    digest: str
    target_desired_generation: int
    application_state: RuntimePolicySnapshotApplicationState
    provider_acknowledged_at: datetime.datetime | None
    runtime_observed_at: datetime.datetime | None
    created_at: datetime.datetime


@dataclass(frozen=True)
class RuntimePolicySnapshotCreate:
    """Complete values for an immutable Runtime policy snapshot."""

    runtime_id: str
    provider_id: str
    contract_revision_id: str
    config_revision_id: str | None
    override_provider_id: str | None
    override_version: int | None
    resolved_config: dict[str, Any]
    encrypted_secrets: str | None
    secret_metadata: dict[str, Any]
    source_trace: dict[str, Any]
    digest: str
    target_desired_generation: int
    application_state: RuntimePolicySnapshotApplicationState
