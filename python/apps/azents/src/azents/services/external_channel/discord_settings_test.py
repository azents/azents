"""Discord-native conversation settings service tests."""

import datetime
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import NamedTuple
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.config import Config
from azents.core.enums import (
    ExternalChannelConversationLocation,
    ExternalChannelInteractionStatus,
    ExternalChannelParticipationSettingStatus,
    ExternalChannelProvider,
    ExternalChannelResourceStatus,
    ExternalChannelResourceType,
    ExternalChannelResponseMode,
    ExternalChannelSetupClaimStatus,
    ExternalChannelTransport,
)
from azents.core.external_account_link import (
    ExternalAccountLinkState,
    ExternalAccountLinkView,
    ExternalAccountNativeLinkState,
    ExternalAccountOriginCreated,
)
from azents.core.external_model_settings import (
    ExternalModelRejected,
    ExternalModelSettingsRejectionCode,
)
from azents.repos.external_channel.data import (
    ExternalChannelBinding,
    ExternalChannelInteraction,
    ExternalChannelParticipationSetting,
    ExternalChannelResource,
    ExternalChannelSetupClaim,
)
from azents.repos.external_channel.repository import ExternalChannelRepository
from azents.services.external_account_link import ExternalAccountLinkService
from azents.services.external_channel.discord_settings import (
    DiscordSettingsContext,
    DiscordSettingsResponseService,
    _origin_matches,
)
from azents.services.external_channel.discord_settings_scope import (
    DiscordAccountLinkScope,
    DiscordModelSettingsScope,
    DiscordSettingsScope,
    discord_binding_version,
    parse_discord_settings_custom_id,
)
from azents.services.external_channel.model_settings import ExternalModelSettingsService
from azents.services.external_channel.participation import (
    ExternalChannelParticipationError,
    ExternalChannelParticipationService,
    ExternalChannelParticipationSessionNavigation,
    ExternalChannelParticipationSettings,
    ExternalChannelParticipationSettingsMutation,
)
from azents.testing.external_channel import make_provider_effect_plan

_NOW = datetime.datetime(2026, 8, 1, tzinfo=datetime.UTC)
_THREAD_INTERACTION_ID = "01a03c28f6137b60b35e68ba50ce5319"
_THREAD_BINDING_ID = "01a03bfcc50a7891a94d3328bdbd88bf"


class _DiscordSettingsServiceFixture(NamedTuple):
    """Service and repository used by Discord settings tests."""

    service: DiscordSettingsResponseService
    repository: AsyncMock
    account_link_service: AsyncMock
    model_settings_service: AsyncMock


def _object_dict(value: object) -> dict[str, object]:
    assert isinstance(value, dict)
    return value


def _object_dict_list(value: object) -> list[dict[str, object]]:
    assert isinstance(value, list)
    return [_object_dict(item) for item in value]


_CONTEXT = DiscordSettingsContext(
    connection_id="connection-1",
    connection_configuration_generation=2,
    guild_id="guild-1",
    guild_display_name="Guild One",
    provider_parent_channel_id="channel-1",
    provider_thread_id=None,
    provider_thread_resource_key=None,
    principal_id="principal-1",
    provider_user_id="user-1",
    provider_display_name="Discord User",
    provider_interaction_id="provider-interaction-1",
)


@asynccontextmanager
async def _session_manager() -> AsyncGenerator[AsyncSession, None]:
    yield MagicMock(spec=AsyncSession)


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


def _session_navigation() -> ExternalChannelParticipationSessionNavigation:
    return ExternalChannelParticipationSessionNavigation(
        workspace_handle="workspace",
        agent_id="agent-1",
        session_id="session-1",
    )


def _service(
    *,
    origin: ExternalChannelInteraction,
    participation: object,
) -> _DiscordSettingsServiceFixture:
    repository = AsyncMock(spec=ExternalChannelRepository)
    repository.lock_interaction.return_value = origin
    config = MagicMock(spec=Config)
    config.auth = SimpleNamespace(jwt=SimpleNamespace(secret_key="settings-secret"))
    config.web_url = "https://azents.example"
    account_link_service = AsyncMock(spec=ExternalAccountLinkService)
    account_link_service.get_native_link_state.return_value = (
        ExternalAccountNativeLinkState(
            link=None,
            management_path="/account/external-accounts",
        )
    )
    model_settings_service = AsyncMock(spec=ExternalModelSettingsService)
    service = DiscordSettingsResponseService(
        session_manager=_session_manager,
        repository=repository,
        participation_service=MagicMock(
            spec=ExternalChannelParticipationService,
            wraps=participation,
        ),
        account_link_service=account_link_service,
        model_settings_service=model_settings_service,
        config=config,
    )
    return _DiscordSettingsServiceFixture(
        service=service,
        repository=repository,
        account_link_service=account_link_service,
        model_settings_service=model_settings_service,
    )


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
async def test_denied_conversation_renders_only_generic_link_surface() -> None:
    """Keep actor-private linking available without conversation disclosure."""
    participation = SimpleNamespace(
        resolve_settings=AsyncMock(
            side_effect=ExternalChannelParticipationError(
                "Secret Agent route and Session are denied."
            )
        )
    )
    service = _service(origin=_origin(), participation=participation).service

    response = await service.initial_response(
        origin_interaction_id="interaction-1",
        context=_CONTEXT,
        now=_NOW,
    )

    data = _object_dict(response.response["data"])
    assert response.response["type"] == 4
    assert data["flags"] == 64
    assert "Conversation settings are unavailable" in str(data["content"])
    assert "Secret Agent" not in str(data)
    rows = _object_dict_list(data["components"])
    button = _object_dict_list(rows[0]["components"])[0]
    assert button["label"] == "Connect Azents account · optional"


@pytest.mark.asyncio
async def test_denied_shared_binding_open_returns_generic_own_link_surface() -> None:
    """Keep the public source unchanged and put personal recovery in a new ephemeral."""
    public_message = {
        "content": "Shared conversation presence",
        "components": ["public-settings-button"],
    }
    original_public_message = {
        "content": "Shared conversation presence",
        "components": ["public-settings-button"],
    }
    participation = SimpleNamespace(
        resolve_settings=AsyncMock(
            side_effect=ExternalChannelParticipationError(
                "Secret Agent route and Session are denied."
            )
        )
    )
    service = _service(origin=_origin(), participation=participation).service

    response = await service.component_response(
        interaction_id="denied-component-interaction-1",
        scope=DiscordSettingsScope(
            action="open_binding",
            origin_interaction_id="binding-1",
            setup_claim_id=None,
            claim_generation=None,
            source_revision=None,
            setting_id=None,
            settings_generation=None,
            binding_id=None,
            binding_version=None,
        ),
        selected_value=None,
        context=_CONTEXT,
        now=_NOW,
    )

    data = _object_dict(response.response["data"])
    assert response.response["type"] == 4
    assert response.response["type"] != 7
    assert data["flags"] == 64
    assert "Conversation settings are unavailable" in str(data["content"])
    assert "Secret Agent" not in str(data)
    assert "Connect Azents account · optional" in str(data["components"])
    assert public_message == original_public_message
    assert "Connect Azents account" not in str(public_message)


@pytest.mark.asyncio
async def test_account_link_start_uses_exact_verified_discord_actor() -> None:
    """Create native origin only after the signed original interaction matches."""
    fixture = _service(
        origin=_origin(),
        participation=SimpleNamespace(resolve_settings=AsyncMock()),
    )
    fixture.account_link_service.create_origin.return_value = (
        ExternalAccountOriginCreated(
            origin_id="account-origin-1",
            expires_at=_NOW + datetime.timedelta(minutes=10),
            web_path="/external-channel/link/account-origin-1",
            management_path="/account/external-accounts",
        )
    )

    response = await fixture.service.account_link_response(
        scope=DiscordAccountLinkScope(
            action="start",
            origin_interaction_id="interaction-1",
            origin_id=None,
        ),
        code=None,
        context=_CONTEXT,
        now=_NOW,
    )

    assert response.response["type"] == 7
    actor = fixture.account_link_service.create_origin.await_args.kwargs["actor"]
    assert actor.connection_id == "connection-1"
    assert actor.connection_configuration_generation == 2
    assert actor.provider_tenant_id == "guild-1"
    assert actor.provider_tenant_display_label == "Guild One"
    assert actor.provider_user_id == "user-1"
    assert actor.provider_display_label == "Discord User"
    assert actor.provider_interaction_id == "provider-interaction-1"
    assert actor.provider_channel_id == "channel-1"
    assert actor.provider_thread_id is None


@pytest.mark.asyncio
async def test_model_apply_passes_displayed_selection_fingerprint_once() -> None:
    """Fence Apply to the exact draft selection shown by the clicked screen."""
    fixture = _service(
        origin=_origin(),
        participation=SimpleNamespace(resolve_settings=AsyncMock()),
    )
    fixture.model_settings_service.apply_draft.return_value = ExternalModelRejected(
        code=ExternalModelSettingsRejectionCode.TARGET_UNAVAILABLE
    )

    response = await fixture.service.model_response(
        scope=DiscordModelSettingsScope(
            action="apply",
            draft_id=_THREAD_BINDING_ID,
            offset=0,
            selection_fingerprint="0123456789abcdef",
        ),
        selected_values=(),
        context=_CONTEXT,
        now=_NOW,
    )

    assert response.response["type"] == 7
    call = fixture.model_settings_service.apply_draft.await_args.kwargs
    assert call["expected_selection_fingerprint"] == "0123456789abcdef"
    assert call["apply_interaction_key"] == "provider-interaction-1"
    fixture.model_settings_service.apply_draft.assert_awaited_once()


@pytest.mark.asyncio
async def test_inactive_link_omits_model_editor_and_keeps_management() -> None:
    """Do not present link-dependent editing after Workspace participation loss."""
    current = ExternalChannelParticipationSettings(
        target="parent",
        agent_name="Agent One",
        session_navigation=_session_navigation(),
        setting=_setting(),
        claim=None,
        resource=None,
        binding=_binding(),
    )
    fixture = _service(
        origin=_origin(),
        participation=SimpleNamespace(resolve_settings=AsyncMock(return_value=current)),
    )
    fixture.account_link_service.get_native_link_state.return_value = (
        ExternalAccountNativeLinkState(
            link=ExternalAccountLinkView(
                id="link-1",
                workspace_id="workspace-1",
                workspace_name="Workspace One",
                workspace_handle="workspace-one",
                user_id="user-1",
                provider=ExternalChannelProvider.DISCORD,
                identity_scope="global",
                provider_user_id="user-1",
                provider_tenant_display_label="Guild One",
                provider_display_label="Discord User",
                linked_at=_NOW,
                state=ExternalAccountLinkState.INACTIVE,
            ),
            management_path="/account/external-accounts",
        )
    )

    response = await fixture.service.initial_response(
        origin_interaction_id="interaction-1",
        context=_CONTEXT,
        now=_NOW,
    )

    data = _object_dict(response.response["data"])
    assert "Linked, but inactive" in str(data["content"])
    assert "Manage linked account" in str(data["components"])
    assert "ms1:" not in str(data["components"])
    fixture.model_settings_service.open_editor.assert_not_awaited()


@pytest.mark.asyncio
async def test_parent_settings_render_current_selects_without_session() -> None:
    """A parent without one exact Binding omits only Session navigation."""
    current = ExternalChannelParticipationSettings(
        target="parent",
        agent_name="Agent One",
        session_navigation=None,
        setting=_setting(
            location=ExternalChannelConversationLocation.THREADS,
            response_mode=ExternalChannelResponseMode.ALL_MESSAGES,
        ),
        claim=None,
        resource=None,
        binding=None,
    )
    participation = SimpleNamespace(resolve_settings=AsyncMock(return_value=current))
    service = _service(origin=_origin(), participation=participation).service

    response = await service.initial_response(
        origin_interaction_id="interaction-1",
        context=_CONTEXT,
        now=_NOW,
    )

    assert response.response["type"] == 4
    data = _object_dict(response.response["data"])
    assert data["flags"] == 64
    rows = _object_dict_list(data["components"])
    assert len(rows) == 3
    account_button = _object_dict_list(rows[2]["components"])[0]
    assert account_button["label"] == "Connect Azents account · optional"
    assert str(account_button["custom_id"]).startswith("al1:s:")
    location_select = _object_dict_list(rows[0]["components"])[0]
    response_select = _object_dict_list(rows[1]["components"])[0]
    assert _object_dict_list(location_select["options"]) == [
        {"label": "This channel", "value": "channel", "default": False},
        {"label": "Threads", "value": "threads", "default": True},
    ]
    assert _object_dict_list(response_select["options"]) == [
        {"label": "When mentioned", "value": "mention_only", "default": False},
        {"label": "Every message", "value": "all_messages", "default": True},
    ]


@pytest.mark.asyncio
async def test_setup_settings_retain_location_buttons() -> None:
    """First-time setup remains a deferred two-button decision."""
    current = ExternalChannelParticipationSettings(
        target="setup",
        agent_name="Agent One",
        session_navigation=None,
        setting=None,
        claim=_claim(),
        resource=None,
        binding=None,
    )
    participation = SimpleNamespace(resolve_settings=AsyncMock(return_value=current))
    service = _service(origin=_origin(), participation=participation).service

    response = await service.initial_response(
        origin_interaction_id="interaction-1",
        context=_CONTEXT,
        now=_NOW,
    )

    data = _object_dict(response.response["data"])
    rows = _object_dict_list(data["components"])
    buttons = _object_dict_list(rows[0]["components"])
    assert [(button["type"], button["label"]) for button in buttons] == [
        (2, "Answer in this channel"),
        (2, "Answer in threads"),
    ]


@pytest.mark.asyncio
async def test_setup_control_passes_exact_claim_fences_to_canonical_selection() -> None:
    """A setup control commits only its current claim generation and source revision."""
    claim = _claim()
    setup = ExternalChannelParticipationSettings(
        target="setup",
        agent_name="Agent One",
        session_navigation=None,
        setting=None,
        claim=claim,
        resource=None,
        binding=None,
    )
    committed = ExternalChannelParticipationSettings(
        target="parent",
        agent_name="Agent One",
        session_navigation=None,
        setting=_setting(),
        claim=None,
        resource=None,
        binding=None,
    )
    participation = SimpleNamespace(
        resolve_settings=AsyncMock(side_effect=[setup, committed]),
        select_location=AsyncMock(),
    )
    service = _service(origin=_origin(), participation=participation).service

    response = await service.component_response(
        interaction_id="component-interaction-1",
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
        selected_value=None,
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
    presence_plan = make_provider_effect_plan("presence-delete")
    progress_plan = make_provider_effect_plan("progress-delete")
    current = ExternalChannelParticipationSettings(
        target="parent",
        agent_name="Agent One",
        session_navigation=None,
        setting=_setting(),
        claim=None,
        resource=None,
        binding=None,
    )
    updated = ExternalChannelParticipationSettings(
        target="parent",
        agent_name="Agent One",
        session_navigation=None,
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
                cleanup_plans=(presence_plan, progress_plan),
            )
        ),
    )
    service = _service(origin=_origin(), participation=participation).service

    response = await service.component_response(
        interaction_id="component-interaction-1",
        scope=DiscordSettingsScope(
            action="parent_location",
            origin_interaction_id="interaction-1",
            setup_claim_id=None,
            claim_generation=None,
            source_revision=None,
            setting_id="setting-1",
            settings_generation=1,
            binding_id=None,
            binding_version=None,
        ),
        selected_value="threads",
        context=_CONTEXT,
        now=_NOW,
    )

    call = participation.mutate_parent_settings.await_args.kwargs
    assert call["location"] is ExternalChannelConversationLocation.THREADS
    assert call["response_mode"] is ExternalChannelResponseMode.MENTION_ONLY
    assert response.cleanup_plans == (presence_plan, progress_plan)


@pytest.mark.asyncio
async def test_thread_control_mutates_only_the_exact_connected_binding() -> None:
    """A thread control passes its exact Resource, Binding, and revision fence."""
    context = DiscordSettingsContext(
        connection_id="connection-1",
        connection_configuration_generation=2,
        guild_id="guild-1",
        guild_display_name="Guild One",
        provider_parent_channel_id="channel-1",
        provider_thread_id="thread-1",
        provider_thread_resource_key="discord:guild-1:thread-1",
        principal_id="principal-1",
        provider_user_id="user-1",
        provider_display_name="Discord User",
        provider_interaction_id="provider-interaction-1",
    )
    binding = _binding().model_copy(update={"id": _THREAD_BINDING_ID})
    current = ExternalChannelParticipationSettings(
        target="thread",
        agent_name="Agent One",
        session_navigation=_session_navigation(),
        setting=None,
        claim=None,
        resource=_resource(),
        binding=binding,
    )
    updated = ExternalChannelParticipationSettings(
        target="thread",
        agent_name="Agent One",
        session_navigation=_session_navigation(),
        setting=None,
        claim=None,
        resource=_resource(),
        binding=_binding(
            response_mode=ExternalChannelResponseMode.ALL_MESSAGES
        ).model_copy(update={"id": _THREAD_BINDING_ID}),
    )
    participation = SimpleNamespace(
        resolve_settings=AsyncMock(return_value=current),
        mutate_thread_settings=AsyncMock(
            return_value=ExternalChannelParticipationSettingsMutation(
                settings=updated,
                cleanup_plans=(),
            )
        ),
    )
    service = _service(
        origin=_origin(thread_resource_key="discord:guild-1:thread-1"),
        participation=participation,
    ).service

    response = await service.component_response(
        interaction_id="component-interaction-1",
        scope=DiscordSettingsScope(
            action="thread_response_mode",
            origin_interaction_id=_THREAD_INTERACTION_ID,
            setup_claim_id=None,
            claim_generation=None,
            source_revision=None,
            setting_id=None,
            settings_generation=None,
            binding_id=_THREAD_BINDING_ID,
            binding_version=discord_binding_version(_NOW),
        ),
        selected_value="all_messages",
        context=context,
        now=_NOW,
    )

    call = participation.mutate_thread_settings.await_args.kwargs
    assert call["resource_id"] == "resource-1"
    assert call["binding_id"] == _THREAD_BINDING_ID
    assert call["expected_binding_updated_at"] == _NOW
    assert call["response_mode"] is ExternalChannelResponseMode.ALL_MESSAGES
    assert response.response["type"] == 7


@pytest.mark.asyncio
async def test_stale_parent_generation_returns_notice_without_mutation() -> None:
    """A stale signed setting generation cannot mutate the current parent setting."""
    current = ExternalChannelParticipationSettings(
        target="parent",
        agent_name="Agent One",
        session_navigation=None,
        setting=_setting(generation=2),
        claim=None,
        resource=None,
        binding=None,
    )
    participation = SimpleNamespace(
        resolve_settings=AsyncMock(return_value=current),
        mutate_parent_settings=AsyncMock(),
    )
    service = _service(origin=_origin(), participation=participation).service

    response = await service.component_response(
        interaction_id="component-interaction-1",
        scope=DiscordSettingsScope(
            action="parent_response_mode",
            origin_interaction_id="interaction-1",
            setup_claim_id=None,
            claim_generation=None,
            source_revision=None,
            setting_id="setting-1",
            settings_generation=1,
            binding_id=None,
            binding_version=None,
        ),
        selected_value="all_messages",
        context=_CONTEXT,
        now=_NOW,
    )

    assert response.response["type"] == 4
    assert _object_dict(response.response["data"])["flags"] == 64
    assert "Conversation settings are unavailable" in str(response.response)
    participation.mutate_parent_settings.assert_not_awaited()


@pytest.mark.asyncio
async def test_invalid_select_value_returns_notice_without_mutation() -> None:
    """A signed scope cannot authorize a value outside its closed Select options."""
    current = ExternalChannelParticipationSettings(
        target="parent",
        agent_name="Agent One",
        session_navigation=None,
        setting=_setting(),
        claim=None,
        resource=None,
        binding=None,
    )
    participation = SimpleNamespace(
        resolve_settings=AsyncMock(return_value=current),
        mutate_parent_settings=AsyncMock(),
    )
    service = _service(origin=_origin(), participation=participation).service

    response = await service.component_response(
        interaction_id="component-interaction-1",
        scope=DiscordSettingsScope(
            action="parent_location",
            origin_interaction_id="interaction-1",
            setup_claim_id=None,
            claim_generation=None,
            source_revision=None,
            setting_id="setting-1",
            settings_generation=1,
            binding_id=None,
            binding_version=None,
        ),
        selected_value="unknown",
        context=_CONTEXT,
        now=_NOW,
    )

    assert response.response["type"] == 4
    assert _object_dict(response.response["data"])["flags"] == 64
    assert "Conversation settings are unavailable" in str(response.response)
    participation.mutate_parent_settings.assert_not_awaited()


@pytest.mark.asyncio
async def test_binding_open_rebinds_follow_up_controls_to_component_interaction() -> (
    None
):
    """A joined-presence control signs mutations with its admitted component."""
    current = ExternalChannelParticipationSettings(
        target="parent",
        agent_name="Agent One",
        session_navigation=_session_navigation(),
        setting=_setting(),
        claim=None,
        resource=None,
        binding=_binding(),
    )
    updated = ExternalChannelParticipationSettings(
        target="parent",
        agent_name="Agent One",
        session_navigation=_session_navigation(),
        setting=_setting(response_mode=ExternalChannelResponseMode.ALL_MESSAGES),
        claim=None,
        resource=None,
        binding=_binding(response_mode=ExternalChannelResponseMode.ALL_MESSAGES),
    )
    participation = SimpleNamespace(
        resolve_settings=AsyncMock(return_value=current),
        mutate_parent_settings=AsyncMock(
            return_value=ExternalChannelParticipationSettingsMutation(
                settings=updated,
                cleanup_plans=(),
            )
        ),
    )
    fixture = _service(origin=_origin(), participation=participation)
    service = fixture.service
    repository = fixture.repository

    opened = await service.component_response(
        interaction_id="component-interaction-1",
        scope=DiscordSettingsScope(
            action="open_binding",
            origin_interaction_id="binding-1",
            setup_claim_id=None,
            claim_generation=None,
            source_revision=None,
            setting_id=None,
            settings_generation=None,
            binding_id=None,
            binding_version=None,
        ),
        selected_value=None,
        context=_CONTEXT,
        now=_NOW,
    )

    data = _object_dict(opened.response["data"])
    rows = _object_dict_list(data["components"])
    assert len(rows) == 4
    location_select = _object_dict_list(rows[0]["components"])[0]
    response_select = _object_dict_list(rows[1]["components"])[0]
    navigation_button = _object_dict_list(rows[2]["components"])[0]
    assert location_select["placeholder"] == "Where to respond"
    assert _object_dict_list(location_select["options"]) == [
        {"label": "This channel", "value": "channel", "default": True},
        {"label": "Threads", "value": "threads", "default": False},
    ]
    response_custom_id = response_select["custom_id"]
    assert response_select["type"] == 3
    assert response_select["placeholder"] == "When to respond"
    assert navigation_button == {
        "type": 2,
        "style": 5,
        "label": "View session",
        "url": "https://azents.example/w/workspace/agents/agent-1/sessions/session-1",
    }
    assert isinstance(response_custom_id, str)
    mutation_scope = parse_discord_settings_custom_id(
        custom_id=response_custom_id,
        secret="settings-secret",
    )
    assert mutation_scope.action == "parent_response_mode"
    assert mutation_scope.origin_interaction_id == "component-interaction-1"

    saved = await service.component_response(
        interaction_id="mutation-interaction-1",
        scope=mutation_scope,
        selected_value="all_messages",
        context=_CONTEXT,
        now=_NOW,
    )

    assert saved.response["type"] == 7
    saved_data = _object_dict(saved.response["data"])
    assert "flags" not in saved_data
    saved_rows = _object_dict_list(saved_data["components"])
    saved_response_select = _object_dict_list(saved_rows[1]["components"])[0]
    assert _object_dict_list(saved_response_select["options"]) == [
        {"label": "When mentioned", "value": "mention_only", "default": False},
        {"label": "Every message", "value": "all_messages", "default": True},
    ]
    assert _object_dict_list(saved_rows[2]["components"])[0] == navigation_button
    assert repository.lock_interaction.await_args.kwargs["interaction_id"] == (
        "component-interaction-1"
    )
    participation.mutate_parent_settings.assert_awaited_once()


@pytest.mark.asyncio
async def test_binding_open_renders_bounded_thread_controls() -> None:
    """A connected thread renders signed controls within Discord's ID limit."""
    context = DiscordSettingsContext(
        connection_id="connection-1",
        connection_configuration_generation=2,
        guild_id="guild-1",
        guild_display_name="Guild One",
        provider_parent_channel_id="channel-1",
        provider_thread_id="thread-1",
        provider_thread_resource_key="discord:guild-1:thread-1",
        principal_id="principal-1",
        provider_user_id="user-1",
        provider_display_name="Discord User",
        provider_interaction_id="provider-interaction-1",
    )
    binding = _binding().model_copy(update={"id": _THREAD_BINDING_ID})
    current = ExternalChannelParticipationSettings(
        target="thread",
        agent_name="Agent One",
        session_navigation=_session_navigation(),
        setting=None,
        claim=None,
        resource=_resource(),
        binding=binding,
    )
    participation = SimpleNamespace(resolve_settings=AsyncMock(return_value=current))
    service = _service(origin=_origin(), participation=participation).service

    opened = await service.component_response(
        interaction_id=_THREAD_INTERACTION_ID,
        scope=DiscordSettingsScope(
            action="open_binding",
            origin_interaction_id=_THREAD_BINDING_ID,
            setup_claim_id=None,
            claim_generation=None,
            source_revision=None,
            setting_id=None,
            settings_generation=None,
            binding_id=None,
            binding_version=None,
        ),
        selected_value=None,
        context=context,
        now=_NOW,
    )

    data = _object_dict(opened.response["data"])
    rows = _object_dict_list(data["components"])
    assert len(rows) == 3
    response_select = _object_dict_list(rows[0]["components"])[0]
    custom_id = response_select["custom_id"]
    assert response_select["type"] == 3
    assert response_select["placeholder"] == "When to respond"
    assert isinstance(custom_id, str)
    scope = parse_discord_settings_custom_id(
        custom_id=custom_id,
        secret="settings-secret",
    )
    assert len(custom_id) == 90
    assert scope.action == "thread_response_mode"
    assert scope.origin_interaction_id == _THREAD_INTERACTION_ID
    assert scope.binding_id == _THREAD_BINDING_ID
    assert _object_dict_list(rows[1]["components"])[0] == {
        "type": 2,
        "style": 5,
        "label": "View session",
        "url": "https://azents.example/w/workspace/agents/agent-1/sessions/session-1",
    }
