"""Pure selector contracts and current durable-state validation."""

import datetime
from dataclasses import dataclass
from typing import Literal

from azents.core.enums import ExternalChannelInteractionStatus
from azents.core.external_channel_selector_state import (
    ExternalChannelSelectorState,
    selector_state_from_interaction,
)
from azents.repos.external_channel.data import (
    ExternalChannelBinding,
    ExternalChannelInteraction,
)


class ExternalChannelSelectorError(ValueError):
    """A selector request does not match current durable routing state."""


@dataclass(frozen=True)
class ExternalChannelSelectorCandidate:
    """One current visible Agent candidate."""

    route_id: str
    agent_name: str
    access: Literal["available", "access_required"]


@dataclass(frozen=True)
class ExternalChannelSelectorCatalog:
    """A bounded deterministic page from the current Multi App catalog."""

    candidates: tuple[ExternalChannelSelectorCandidate, ...]
    next_offset: int | None


@dataclass(frozen=True)
class ExternalChannelSelectorSelection:
    """One immutable selection result or its existing binding winner."""

    status: Literal[
        "selected",
        "already_selected",
        "already_bound",
        "setup_pending_location",
        "expired",
    ]
    selector_interaction: ExternalChannelInteraction
    binding: ExternalChannelBinding | None


def selector_state(
    interaction: ExternalChannelInteraction | None,
    *,
    principal_id: str,
    now: datetime.datetime | None,
) -> ExternalChannelSelectorState:
    if (
        interaction is None
        or interaction.principal_id != principal_id
        or interaction.status
        in {
            ExternalChannelInteractionStatus.EXPIRED,
            ExternalChannelInteractionStatus.REJECTED,
            ExternalChannelInteractionStatus.FAILED,
        }
        or (now is not None and interaction.expires_at <= now)
    ):
        raise ExternalChannelSelectorError("Selector interaction is unavailable.")
    state = selector_state_from_interaction(interaction)
    if state.principal_id != principal_id:
        raise ExternalChannelSelectorError("Selector principal is unavailable.")
    return state
