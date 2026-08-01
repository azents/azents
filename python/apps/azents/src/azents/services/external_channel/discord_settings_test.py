"""Discord-native conversation settings service tests."""

import datetime
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.config import Config
from azents.core.enums import (
    ExternalChannelConversationLocation,
    ExternalChannelInteractionStatus,
    ExternalChannelParticipationSettingStatus,
    ExternalChannelResourceStatus,
    ExternalChannelResourceType,
    ExternalChannelResponseMode,
    ExternalChannelSetupClaimStatus,
    ExternalChannelTransport,
)
from azents.rdb.session import SessionManager
from azents.repos.external_channel.data import (
    ExternalChannelBinding,
    ExternalChannelInteraction,
    ExternalChannelParticipationSetting,
    ExternalChannelResource,
    ExternalChannelSetupClaim,
)
from azents.repos.external_channel.repository import ExternalChannelRepository
from azents.services.external_channel.discord_settings import (
    DiscordSettingsContext,
    DiscordSettingsResponseService,
    _origin_matches,  # pyright: ignore[reportPrivateUsage]
)
from azents.services.external_channel.discord_settings_scope import (
    DiscordSettingsScope,
    discord_binding_version,
)
from azents.services.external_channel.participation import (
    ExternalChannelParticipationService,
    ExternalChannelParticipationSettings,
    ExternalChannelParticipationSettingsMutation,
)

_NOW = datetime.datetime(2026, 8, 1, tzinfo=datetime.UTC)
_CONTEXT = DiscordSettingsContext(
    connection_id="connection-1",
    guild_id="guild-1",
    provider_parent_channel_id="channel-1",
    provider_thread_resource_key=None,
    principal_id="principal-1",
)


@asynccontextmanager
async def _session_manager() -> AsyncGenerator[AsyncSession, None]:
    yield cast(AsyncSession, object())


def _origin(
    *,
    connection_id: str = "connection-1",
    principal_id: str = "principal-1",
    status: ExternalChannelInteractionStatus = (
        ExternalChannelInteractionStatus.ACCEPTED
    ),
    guild_id: str = "guild-1",
    parent_channel_id: str = "channel-1",
    thread_resource_key: str | None = None,
) -> ExternalChannelInteraction:
    return ExternalChannelInteraction.model_construct(
        id="interaction-1",
        connection_id=connection_id,
        transport=ExternalChannelTransport.HTTP,
        provider_interaction_key="provider-interaction-1",
        principal_id=principal_id,
        projection={
            "guild_id": guild_id,
            "provider_parent_channel_id": parent_channel_id,
            **(
                {}
                if thread_resource_key is None
                else {"provider_thread_resource_key": thread_resource_key}
            ),
        },
        status=status,
    )


def _setting(
    *,
    location: ExternalChannelConversationLocation = (
        ExternalChannelConversationLocation.CHANNEL
    ),
    response_mode: ExternalChannelResponseMode = (
        ExternalChannelResponseMode.MENTION_ONLY
    ),
    generation: int = 1,
) -> ExternalChannelParticipationSetting:
    return ExternalChannelParticipationSetting.model_construct(
        id="setting-1",
        connection_id="connection-1",
        provider_parent_channel_id="channel-1",
        route_id="route-1",
        location=location,
        response_mode=response_mode,
        settings_generation=generation,
        status=ExternalChannelParticipationSettingStatus.ACTIVE,
    )


def _claim() -> ExternalChannelSetupClaim:
    return ExternalChannelSetupClaim.model_construct(
        id="claim-1",
        connection_id="connection-1",
        provider_parent_channel_id="channel-1",
        route_id="route-1",
        claim_generation=2,
        source_revision=4,
        status=ExternalChannelSetupClaimStatus.PENDING_LOCATION,
    )


def _resource() -> ExternalChannelResource:
    return ExternalChannelResource.model_construct(
        id="resource-1",
        connection_id="connection-1",
        resource_type=ExternalChannelResourceType.THREAD,
        provider_resource_key="discord:guild-1:thread-1",
        status=ExternalChannelResourceStatus.ACTIVE,
    )


def _binding(
    *,
    response_mode: ExternalChannelResponseMode = (
        ExternalChannelResponseMode.MENTION_ONLY
    ),
) -> ExternalChannelBinding:
    return ExternalChannelBinding.model_construct(
        id="binding-1",
        resource_id="resource-1",
        route_id="route-1",
        agent_session_id="session-1",
        response_mode=response_mode,
        connected_at=_NOW,
        disconnected_at=None,
        updated_at=_NOW,
    )


def _service(
    *,
    origin: ExternalChannelInteraction,
    participation: object,
) -> tuple[DiscordSettingsResponseService, AsyncMock]:
    repository = AsyncMock(spec=ExternalChannelRepository)
    repository.lock_interaction.return_value = origin
    service = DiscordSettingsResponseService(
        session_manager=cast(SessionManager[AsyncSession], _session_manager),
        repository=cast(ExternalChannelRepository, repository),
        participation_service=cast(ExternalChannelParticipationService, participation),
        config=cast(
            Config,
            SimpleNamespace(
                auth=SimpleNamespace(jwt=SimpleNamespace(secret_key="settings-secret"))
            ),
        ),
    )
    return service, repository


@pytest.mark.parametrize(
    ("origin", "context"),
    [
        (_origin(connection_id="connection-2"), _CONTEXT),
        (_origin(principal_id="principal-2"), _CONTEXT),
        (
            _origin(status=ExternalChannelInteractionStatus.REJECTED),
            _CONTEXT,
        ),
        (_origin(guild_id="guild-2"), _CONTEXT),
        (_origin(parent_channel_id="channel-2"), _CONTEXT),
        (
            _origin(thread_resource_key="discord:guild-1:thread-2"),
            _CONTEXT,
        ),
    ],
)
def test_settings_origin_fails_closed_across_authenticated_scope(
    origin: ExternalChannelInteraction,
    context: DiscordSettingsContext,
) -> None:
    """Connection, actor, status, Guild, parent, and thread must all match."""
    assert _origin_matches(origin=origin, context=context) is False


def test_settings_origin_accepts_one_exact_authenticated_scope() -> None:
    """An accepted interaction in the same authenticated scope remains current."""
    assert _origin_matches(origin=_origin(), context=_CONTEXT) is True


@pytest.mark.asyncio
async def test_setup_control_passes_exact_claim_fences_to_canonical_selection() -> None:
    """A setup control commits only its current claim generation and source revision."""
    claim = _claim()
    setup = ExternalChannelParticipationSettings(
        target="setup",
        agent_name="Agent One",
        setting=None,
        claim=claim,
        resource=None,
        binding=None,
    )
    committed = ExternalChannelParticipationSettings(
        target="parent",
        agent_name="Agent One",
        setting=_setting(),
        claim=None,
        resource=None,
        binding=None,
    )
    participation = SimpleNamespace(
        resolve_settings=AsyncMock(side_effect=[setup, committed]),
        select_location=AsyncMock(),
    )
    service, _ = _service(origin=_origin(), participation=participation)

    response = await service.component_response(
        scope=DiscordSettingsScope(
            action="setup_channel",
            origin_interaction_id="interaction-1",
            setup_claim_id="claim-1",
            claim_generation=2,
            source_revision=4,
            setting_id=None,
            settings_generation=None,
            binding_id=None,
            binding_version=None,
        ),
        context=_CONTEXT,
        now=_NOW,
    )

    call = participation.select_location.await_args.kwargs
    assert call["setup_claim_id"] == "claim-1"
    assert call["expected_claim_generation"] == 2
    assert call["expected_source_revision"] == 4
    assert call["location"] is ExternalChannelConversationLocation.CHANNEL
    assert call["configured_by_principal_id"] == "principal-1"
    assert response.response["type"] == 7


@pytest.mark.asyncio
async def test_parent_control_preserves_every_cleanup_delivery() -> None:
    """A parent location mutation returns all committed disconnect cleanup intents."""
    current = ExternalChannelParticipationSettings(
        target="parent",
        agent_name="Agent One",
        setting=_setting(),
        claim=None,
        resource=None,
        binding=None,
    )
    updated = ExternalChannelParticipationSettings(
        target="parent",
        agent_name="Agent One",
        setting=_setting(location=ExternalChannelConversationLocation.THREADS),
        claim=None,
        resource=None,
        binding=None,
    )
    participation = SimpleNamespace(
        resolve_settings=AsyncMock(return_value=current),
        mutate_parent_settings=AsyncMock(
            return_value=ExternalChannelParticipationSettingsMutation(
                settings=updated,
                cleanup_delivery_ids=("presence-delete-1", "progress-delete-1"),
            )
        ),
    )
    service, _ = _service(origin=_origin(), participation=participation)

    response = await service.component_response(
        scope=DiscordSettingsScope(
            action="parent_threads",
            origin_interaction_id="interaction-1",
            setup_claim_id=None,
            claim_generation=None,
            source_revision=None,
            setting_id="setting-1",
            settings_generation=1,
            binding_id=None,
            binding_version=None,
        ),
        context=_CONTEXT,
        now=_NOW,
    )

    call = participation.mutate_parent_settings.await_args.kwargs
    assert call["location"] is ExternalChannelConversationLocation.THREADS
    assert call["response_mode"] is ExternalChannelResponseMode.MENTION_ONLY
    assert response.cleanup_delivery_ids == (
        "presence-delete-1",
        "progress-delete-1",
    )


@pytest.mark.asyncio
async def test_thread_control_mutates_only_the_exact_connected_binding() -> None:
    """A thread control passes its exact Resource, Binding, and revision fence."""
    context = DiscordSettingsContext(
        connection_id="connection-1",
        guild_id="guild-1",
        provider_parent_channel_id="channel-1",
        provider_thread_resource_key="discord:guild-1:thread-1",
        principal_id="principal-1",
    )
    binding = _binding()
    current = ExternalChannelParticipationSettings(
        target="thread",
        agent_name="Agent One",
        setting=None,
        claim=None,
        resource=_resource(),
        binding=binding,
    )
    updated = ExternalChannelParticipationSettings(
        target="thread",
        agent_name="Agent One",
        setting=None,
        claim=None,
        resource=_resource(),
        binding=_binding(response_mode=ExternalChannelResponseMode.ALL_MESSAGES),
    )
    participation = SimpleNamespace(
        resolve_settings=AsyncMock(return_value=current),
        mutate_thread_settings=AsyncMock(
            return_value=ExternalChannelParticipationSettingsMutation(
                settings=updated,
                cleanup_delivery_ids=(),
            )
        ),
    )
    service, _ = _service(
        origin=_origin(thread_resource_key="discord:guild-1:thread-1"),
        participation=participation,
    )

    response = await service.component_response(
        scope=DiscordSettingsScope(
            action="thread_all_messages",
            origin_interaction_id="interaction-1",
            setup_claim_id=None,
            claim_generation=None,
            source_revision=None,
            setting_id=None,
            settings_generation=None,
            binding_id="binding-1",
            binding_version=discord_binding_version(_NOW),
        ),
        context=context,
        now=_NOW,
    )

    call = participation.mutate_thread_settings.await_args.kwargs
    assert call["resource_id"] == "resource-1"
    assert call["binding_id"] == "binding-1"
    assert call["expected_binding_updated_at"] == _NOW
    assert call["response_mode"] is ExternalChannelResponseMode.ALL_MESSAGES
    assert response.response["type"] == 7


@pytest.mark.asyncio
async def test_stale_parent_generation_returns_notice_without_mutation() -> None:
    """A stale signed setting generation cannot mutate the current parent setting."""
    current = ExternalChannelParticipationSettings(
        target="parent",
        agent_name="Agent One",
        setting=_setting(generation=2),
        claim=None,
        resource=None,
        binding=None,
    )
    participation = SimpleNamespace(
        resolve_settings=AsyncMock(return_value=current),
        mutate_parent_settings=AsyncMock(),
    )
    service, _ = _service(origin=_origin(), participation=participation)

    response = await service.component_response(
        scope=DiscordSettingsScope(
            action="parent_all_messages",
            origin_interaction_id="interaction-1",
            setup_claim_id=None,
            claim_generation=None,
            source_revision=None,
            setting_id="setting-1",
            settings_generation=1,
            binding_id=None,
            binding_version=None,
        ),
        context=_CONTEXT,
        now=_NOW,
    )

    assert response.response["type"] == 4
    assert "changed before submission" in str(response.response)
    participation.mutate_parent_settings.assert_not_awaited()
