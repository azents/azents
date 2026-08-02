"""Process-local External Channel provider effect contracts."""

import hashlib
from dataclasses import dataclass, field
from typing import Any, Literal

from azents.core.enums import (
    ExternalChannelAppMode,
    ExternalChannelDeliveryOperation,
    ExternalChannelProvider,
)

_PROVIDER_OPERATION_KEY_MAX_LENGTH = 25

type ProviderMutationStatus = Literal["delivered", "failed", "unknown"]
type ProviderEffectStatus = Literal[
    "delivered",
    "failed",
    "unknown",
    "not_attempted",
]


@dataclass(frozen=True)
class ProviderOperationKey:
    """Bounded duplicate-fence key scoped to one live provider operation."""

    value: str = field(repr=False)

    def __post_init__(self) -> None:
        if not self.value or len(self.value) > _PROVIDER_OPERATION_KEY_MAX_LENGTH:
            raise ValueError("Provider operation key must be non-empty and bounded.")

    @classmethod
    def from_seed(cls, seed: str) -> "ProviderOperationKey":
        """Derive one opaque bounded key without retaining the source identity."""
        if not seed:
            raise ValueError("Provider operation key seed must be non-empty.")
        value = hashlib.sha256(seed.encode()).hexdigest()[
            :_PROVIDER_OPERATION_KEY_MAX_LENGTH
        ]
        return cls(value=value)


@dataclass(frozen=True)
class ProviderTarget:
    """Live provider target without durable attempt identity or status."""

    operation: ExternalChannelDeliveryOperation
    binding_id: str | None
    resource_id: str | None
    connection_id: str
    provider: ExternalChannelProvider
    app_mode: ExternalChannelAppMode
    encrypted_credentials: str | None = field(repr=False)
    provider_tenant_id: str | None
    capabilities: dict[str, Any] | None = field(repr=False)
    workspace_handle: str | None
    agent_id: str | None
    agent_session_id: str | None
    agent_name: str | None
    agent_avatar: dict[str, Any] | None = field(repr=False)
    request_payload: dict[str, Any] = field(repr=False)


@dataclass(frozen=True)
class ProviderEffectPlan:
    """One process-local provider call prepared for immediate execution."""

    target: ProviderTarget
    operation_key: ProviderOperationKey


@dataclass(frozen=True)
class ProviderMutationOutcome:
    """Sanitized internal provider result with current projection identity."""

    status: ProviderMutationStatus
    provider_message_key: str | None = field(repr=False)
    error_kind: str | None
    error_summary: str | None


@dataclass(frozen=True)
class ProviderEffectOutcome:
    """Identifier-free result for one ordered direct effect."""

    operation: ExternalChannelDeliveryOperation
    part: int
    status: ProviderEffectStatus
    reason: str | None
    detail: str | None
