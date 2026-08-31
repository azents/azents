"""Channel Work and direct provider-effect repository records."""

from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict

from azents.core.enums import (
    ExternalChannelProvider,
    ExternalChannelWorkStatus,
)
from azents.core.external_channel_progress import (
    ExternalChannelWorkTask as ChannelWorkTask,
)
from azents.services.external_channel.provider_effect import (
    ProviderEffectOutcome,
    ProviderEffectPlan,
)


class _Record(BaseModel):
    """Immutable repository data base."""

    model_config = ConfigDict(frozen=True)


class ChannelWorkSnapshot(_Record):
    """Bounded model-visible state for one active External Channel binding."""

    binding_id: str
    provider: ExternalChannelProvider
    resource_label: str
    title: str | None
    tasks: list[ChannelWorkTask]
    awaiting_input: bool


@dataclass(frozen=True)
class ChannelActionEffectPlan:
    """One ordered process-local effect owned by a canonical Work transition."""

    provider: ProviderEffectPlan
    part: int
    work_cycle_id: str
    expected_desired_progress_revision: int | None


@dataclass(frozen=True)
class ChannelActionTransition:
    """Canonical Work transition and its process-local direct effects."""

    binding_id: str
    work_id: str
    work_status: ExternalChannelWorkStatus
    state_revision: int
    effects: tuple[ChannelActionEffectPlan, ...]


@dataclass(frozen=True)
class AwaitingInputSettlement:
    """Final canonical awaiting settlement for one input request."""

    established: bool
    state_revision: int


@dataclass(frozen=True)
class ChannelActionResult:
    """Canonical Work result with ordered identifier-free provider outcomes."""

    binding_id: str
    work_status: ExternalChannelWorkStatus
    state_revision: int
    awaiting_input: bool
    outcomes: tuple[ProviderEffectOutcome, ...]


class ExternalChannelFileAccessTarget(_Record):
    """Active provider connection selected by one binding-scoped file locator."""

    binding_id: str
    connection_id: str
    resource_id: str
    provider: ExternalChannelProvider
    encrypted_credentials: str | None
    provider_tenant_id: str | None
    capabilities: dict[str, Any] | None
    resource_labels: dict[str, Any] | None
