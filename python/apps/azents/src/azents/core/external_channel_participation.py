"""Pure participation contracts and detached navigation/lock scopes."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal, NamedTuple

from azents.core.enums import (
    ExternalChannelConversationScopeKind,
    ExternalChannelProvider,
    ExternalChannelResourceType,
)
from azents.core.external_channel_conversation_data import (
    ExternalChannelConversationScope,
)
from azents.core.external_channel_ingestion import ExternalChannelIngestionOutcome
from azents.core.external_channel_participation_state import (
    ExternalChannelSetupSourceProjection,
)
from azents.core.external_channel_provider_effect import ProviderEffectPlan
from azents.repos.external_channel.data import (
    ExternalChannelAgentRoute,
    ExternalChannelBinding,
    ExternalChannelParticipationSetting,
    ExternalChannelResource,
    ExternalChannelSetupClaim,
)


class ExternalChannelParticipationError(ValueError):
    """A participation mutation is stale, unauthorized, or unavailable."""


@dataclass(frozen=True)
class ExternalChannelLocationSelection:
    """Committed location selection and its independent replay result."""

    status: Literal["selected", "already_selected", "pending_recovery"]
    setting: ExternalChannelParticipationSetting
    claim: ExternalChannelSetupClaim
    replay_outcome: ExternalChannelIngestionOutcome | None


@dataclass(frozen=True)
class ExternalChannelParticipationSessionNavigation:
    """Exact connected Session navigation authority."""

    workspace_handle: str
    agent_id: str
    session_id: str


@dataclass(frozen=True)
class ExternalChannelParticipationSettings:
    """Authorized canonical setup, parent, or connected-thread settings."""

    target: Literal["setup", "parent", "thread"]
    agent_name: str
    session_navigation: ExternalChannelParticipationSessionNavigation | None
    setting: ExternalChannelParticipationSetting | None
    claim: ExternalChannelSetupClaim | None
    resource: ExternalChannelResource | None
    binding: ExternalChannelBinding | None


class _AuthorizedSettingsActor(NamedTuple):
    """Validated route and its owning Agent display name."""

    route: ExternalChannelAgentRoute
    agent_name: str
    workspace_handle: str


def _session_navigation(
    *, actor: _AuthorizedSettingsActor, binding: ExternalChannelBinding | None
) -> ExternalChannelParticipationSessionNavigation | None:
    """Project exact Session navigation only for the authorized route."""
    if binding is None or binding.route_id != actor.route.id:
        return None
    return ExternalChannelParticipationSessionNavigation(
        workspace_handle=actor.workspace_handle,
        agent_id=actor.route.require_active_agent_id(),
        session_id=binding.agent_session_id,
    )


def _discord_delivery_channel_id(
    provider_thread_resource_key: str, *, guild_id: str | None
) -> str | None:
    """Extract one Discord delivery channel from its canonical interaction key."""
    if guild_id is None:
        return None
    prefix = f"discord:{guild_id}:"
    if not provider_thread_resource_key.startswith(prefix):
        return None
    delivery_channel_id = provider_thread_resource_key.removeprefix(prefix)
    if not delivery_channel_id or ":" in delivery_channel_id:
        return None
    return delivery_channel_id


@dataclass(frozen=True)
class _ParticipationThreadLabels:
    """Consumed retained-label decisions for signed participation controls."""

    discord: bool
    guild_id: str | None
    slack_thread_key: str | None
    discord_thread_key: str | None

    @classmethod
    def decode(cls, value: Mapping[str, object] | None) -> "_ParticipationThreadLabels":
        """Preserve unknown labels and legacy fallback before string validation."""
        labels = value or {}
        guild = labels.get("guild_id")
        slack_thread = labels.get("thread_ts")
        # A truthy malformed delivery coordinate blocks the historical fallback;
        # null, empty and other falsy values permit the retained thread ID.
        discord_thread = labels.get("delivery_channel_id") or labels.get("thread_id")
        return cls(
            discord=labels.get("provider") == ExternalChannelProvider.DISCORD.value,
            guild_id=guild if isinstance(guild, str) else None,
            slack_thread_key=(
                slack_thread if isinstance(slack_thread, str) and slack_thread else None
            ),
            discord_thread_key=(
                discord_thread
                if isinstance(discord_thread, str) and discord_thread
                else None
            ),
        )


def _thread_resource_matches(
    *,
    connection_provider: ExternalChannelProvider,
    connection_id: str,
    provider_tenant_id: str | None,
    provider_thread_resource_key: str,
    resource: ExternalChannelResource,
) -> bool:
    """Validate one signed Binding's Resource against its interaction scope."""
    if (
        resource.connection_id != connection_id
        or resource.resource_type is not ExternalChannelResourceType.THREAD
    ):
        return False
    if connection_provider is ExternalChannelProvider.SLACK:
        return resource.provider_resource_key == provider_thread_resource_key
    if connection_provider is not ExternalChannelProvider.DISCORD:
        return False
    delivery_channel_id = _discord_delivery_channel_id(
        provider_thread_resource_key, guild_id=provider_tenant_id
    )
    labels = _ParticipationThreadLabels.decode(resource.labels)
    return (
        delivery_channel_id is not None
        and labels.discord
        and labels.guild_id == provider_tenant_id
        and labels.discord_thread_key == delivery_channel_id
    )


def _thread_conversation_scope(
    *,
    connection_id: str,
    connection_provider: ExternalChannelProvider,
    provider_parent_channel_id: str,
    resource: ExternalChannelResource,
) -> ExternalChannelConversationScope:
    """Build the canonical provider thread identity used by ingestion locks."""
    labels = _ParticipationThreadLabels.decode(resource.labels)
    if connection_provider is ExternalChannelProvider.SLACK:
        provider_channel_id = provider_parent_channel_id
        provider_thread_key = labels.slack_thread_key
    elif connection_provider is ExternalChannelProvider.DISCORD:
        provider_thread_key = labels.discord_thread_key
        provider_channel_id = provider_thread_key
    else:
        provider_channel_id = None
        provider_thread_key = None
    if not provider_channel_id or not provider_thread_key:
        raise ExternalChannelParticipationError(
            "External Channel thread settings are unavailable."
        )
    return ExternalChannelConversationScope(
        connection_id=connection_id,
        kind=ExternalChannelConversationScopeKind.THREAD,
        provider_channel_id=provider_channel_id,
        provider_thread_key=provider_thread_key,
    )


@dataclass(frozen=True)
class ExternalChannelParticipationSettingsMutation:
    """Committed settings state and independent provider cleanup intents."""

    settings: ExternalChannelParticipationSettings
    cleanup_plans: tuple[ProviderEffectPlan, ...]


@dataclass(frozen=True)
class _CommittedLocation:
    """Setting and claim committed before independent replay begins."""

    setting: ExternalChannelParticipationSetting
    claim: ExternalChannelSetupClaim
    created: bool


def _parent_resource_labels(
    source: ExternalChannelSetupSourceProjection,
) -> dict[str, object]:
    """Build explicit provider labels for a selected parent Resource."""
    if source.provider.value == "slack":
        return {
            "provider": "slack",
            "provider_event_type": source.provider_event_type,
            "tenant_id": source.provider_tenant_id,
            "channel_id": source.provider_parent_channel_id,
            "conversation_scope": ExternalChannelResourceType.PARENT_CHANNEL.value,
        }
    return {
        "provider": "discord",
        "provider_event_type": source.provider_event_type,
        "guild_id": source.provider_tenant_id,
        "parent_channel_id": source.provider_parent_channel_id,
        "source_channel_id": source.provider_parent_channel_id,
        "conversation_scope": ExternalChannelResourceType.PARENT_CHANNEL.value,
    }
