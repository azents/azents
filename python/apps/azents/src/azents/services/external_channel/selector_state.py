"""Typed selector state retained by a provider interaction."""

import hashlib
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from azents.repos.external_channel.data import ExternalChannelInteraction

_SELECTOR_STATE_KEY = "agent_selector"


class ExternalChannelSelectorState(BaseModel):
    """Content-free provider-history boundary for one Agent selection."""

    model_config = ConfigDict(frozen=True)

    connection_id: str = Field(min_length=1)
    resource_id: str = Field(min_length=1)
    principal_id: str = Field(min_length=1)
    conversation_position_id: str = Field(min_length=1)
    trigger_provider_message_key: str = Field(min_length=1)
    range_start_position: str | None
    trigger_position: str = Field(min_length=1)
    selected_route_id: str | None


def selector_state_from_interaction(
    interaction: ExternalChannelInteraction,
) -> ExternalChannelSelectorState:
    """Read one typed selector state from bounded interaction metadata."""
    value = interaction.projection.get(_SELECTOR_STATE_KEY)
    if not isinstance(value, dict):
        raise ValueError("External Channel selector state is unavailable.")
    return ExternalChannelSelectorState.model_validate(value)


def projection_with_selector_state(
    projection: dict[str, Any],
    state: ExternalChannelSelectorState,
) -> dict[str, Any]:
    """Return bounded interaction metadata with one selector state."""
    return {**projection, _SELECTOR_STATE_KEY: state.model_dump(mode="json")}


def selector_provider_interaction_key(
    *,
    connection_id: str,
    trigger_provider_message_key: str,
) -> str:
    """Build a bounded deterministic identity for a message-opened selector."""
    digest = hashlib.sha256(
        f"{connection_id}\0{trigger_provider_message_key}".encode()
    ).hexdigest()
    return f"agent-selector:{digest}"
