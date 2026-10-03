"""Pure durable External Channel access decision outcomes and errors."""

from dataclasses import dataclass

from azents.core.external_channel_provider_effect import ProviderEffectPlan
from azents.repos.external_channel.data import (
    ExternalChannelAccessGrant,
    ExternalChannelAccessRequest,
    ExternalChannelBinding,
    ExternalChannelBlock,
)


class ExternalChannelAccessDecisionError(ValueError):
    """An access decision cannot be applied to the current domain state."""


class ExternalChannelAccessRequestNotFound(LookupError):
    """The access request does not exist."""


@dataclass(frozen=True)
class ExternalChannelSetupContinuation:
    """Provider-neutral location setup state after an Allow decision."""

    setup_claim_id: str
    claim_generation: int
    source_revision: int
    route_id: str


@dataclass(frozen=True)
class ExternalChannelAllowedAccess:
    """Durable result of an idempotent Allow decision."""

    request: ExternalChannelAccessRequest
    binding: ExternalChannelBinding | None
    grant: ExternalChannelAccessGrant
    control_delete_plan: ProviderEffectPlan | None
    setup_continuation: ExternalChannelSetupContinuation | None


@dataclass(frozen=True)
class ExternalChannelResolvedAccess:
    """Durable result of an idempotent Deny or Block decision."""

    request: ExternalChannelAccessRequest
    control_delete_plan: ProviderEffectPlan | None


@dataclass(frozen=True)
class ExternalChannelRevokedAccess:
    """Durable access-policy revocation result."""

    grant: ExternalChannelAccessGrant


@dataclass(frozen=True)
class ExternalChannelRemovedBlock:
    """Durable block-removal result."""

    block: ExternalChannelBlock
