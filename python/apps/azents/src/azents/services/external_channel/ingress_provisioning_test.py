"""Conversation-bound External Channel ingress provisioning tests."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from cryptography.fernet import InvalidToken
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    ExternalChannelConversationLocation,
    ExternalChannelProvider,
    ExternalChannelResourceStatus,
    ExternalChannelResourceType,
    ExternalChannelResponseMode,
)
from azents.rdb.session import SessionManager
from azents.repos.external_channel.data import (
    ExternalChannelAgentRoute,
    ExternalChannelBinding,
    ExternalChannelConnectionConfiguration,
    ExternalChannelParticipationSetting,
    ExternalChannelResource,
)
from azents.repos.external_channel.ingress_queue_data import ExternalChannelIngressOwner
from azents.repos.external_channel.repository import ExternalChannelRepository
from azents.repos.external_channel.work import ExternalChannelWorkRepository
from azents.services.external_channel.conversation_provisioning import (
    ExternalChannelConversationProvisioningService,
)
from azents.services.external_channel.credentials import ExternalChannelCredentialsCodec
from azents.services.external_channel.data import DiscordConnectionCredentials
from azents.services.external_channel.discord_delivery import (
    DiscordDeliveryClient,
    DiscordDeliveryResult,
)
from azents.services.external_channel.ingress_provisioning import (
    ExternalChannelIngressProviderPreparation,
    ExternalChannelIngressProvisioningError,
    ExternalChannelIngressProvisioningService,
)
from azents.services.external_channel.mailbox_ingestion_store import (
    ExternalChannelConfiguredBindingResult,
    ExternalChannelMailboxIngestionStore,
)
from azents.testing.external_channel import make_provider_effect_plan


def _session_manager() -> SessionManager[AsyncSession]:
    @asynccontextmanager
    async def manager() -> AsyncIterator[AsyncSession]:
        session: AsyncSession = MagicMock(spec=AsyncSession)
        yield session

    return manager


def _owner() -> ExternalChannelIngressOwner:
    return ExternalChannelIngressOwner.model_construct(
        id="owner-1",
        connection_id="connection-1",
        target_resource_id="resource-1",
        route_id="route-1",
        participation_setting_id="setting-1",
        participation_settings_generation=3,
        response_mode=ExternalChannelResponseMode.ALL_MESSAGES,
        binding_id=None,
        session_id=None,
    )


def _resource(*, delivery_channel_id: str | None = None) -> ExternalChannelResource:
    labels: dict[str, object] = {
        "provider": "discord",
        "guild_id": "100",
        "parent_channel_id": "200",
        "root_message_id": "300",
    }
    if delivery_channel_id is not None:
        labels["delivery_channel_id"] = delivery_channel_id
    return ExternalChannelResource.model_construct(
        id="resource-1",
        connection_id="connection-1",
        resource_type=ExternalChannelResourceType.THREAD,
        provider_resource_key="discord:guild:100:conversation:300",
        labels=labels,
        status=ExternalChannelResourceStatus.ACTIVE,
    )


def _service(
    *,
    repository: ExternalChannelRepository,
    work_repository: ExternalChannelWorkRepository | None = None,
    credentials_codec: ExternalChannelCredentialsCodec | None = None,
    discord_client: DiscordDeliveryClient | None = None,
    mailbox_store: ExternalChannelMailboxIngestionStore | None = None,
) -> ExternalChannelIngressProvisioningService:
    repository.get_connected_binding_by_resource = AsyncMock(return_value=None)
    conversation_provisioning = ExternalChannelConversationProvisioningService(
        session_manager=_session_manager(),
        repository=repository,
        work_repository=work_repository
        or MagicMock(spec=ExternalChannelWorkRepository),
        credentials_codec=credentials_codec
        or MagicMock(spec=ExternalChannelCredentialsCodec),
        discord_client=discord_client or MagicMock(spec=DiscordDeliveryClient),
    )
    return ExternalChannelIngressProvisioningService(
        session_manager=_session_manager(),
        repository=repository,
        conversation_provisioning=conversation_provisioning,
        mailbox_store=mailbox_store
        or MagicMock(spec=ExternalChannelMailboxIngestionStore),
    )


async def test_prepare_discord_thread_has_no_db_transition() -> None:
    """Discord provider mutation finishes before any ready-transition DB write."""
    repository = MagicMock(spec=ExternalChannelRepository)
    repository.get_resource = AsyncMock(return_value=_resource())
    repository.get_connection_configuration = AsyncMock(
        return_value=ExternalChannelConnectionConfiguration.model_construct(
            provider=ExternalChannelProvider.DISCORD,
            encrypted_credentials="ciphertext",
            provider_config={
                "provider": "discord",
                "target_guild_id": "100",
                "thread_auto_archive_duration_minutes": 1440,
            },
        )
    )
    codec = MagicMock(spec=ExternalChannelCredentialsCodec)
    codec.decrypt.return_value = DiscordConnectionCredentials(bot_token="secret")
    discord = MagicMock(spec=DiscordDeliveryClient)
    discord.ensure_thread = AsyncMock(
        return_value=DiscordDeliveryResult(
            status="delivered",
            provider_message_key="discord-thread:400",
            error_kind=None,
            error_summary=None,
            created_thread_name="Azents thread",
        )
    )
    work_repository = MagicMock(spec=ExternalChannelRepository)
    work_repository.record_discord_delivery_channel = AsyncMock()
    mailbox_store = MagicMock(spec=ExternalChannelMailboxIngestionStore)
    mailbox_store.create_configured_binding = AsyncMock()
    service = _service(
        repository=repository,
        work_repository=work_repository,
        credentials_codec=codec,
        discord_client=discord,
        mailbox_store=mailbox_store,
    )

    prepared = await service.prepare(owner=_owner())

    assert prepared == ExternalChannelIngressProviderPreparation(
        target_resource_id="resource-1",
        delivery_channel_id="400",
        initial_thread_title="Azents thread",
    )
    discord.ensure_thread.assert_awaited_once()
    work_repository.record_discord_delivery_channel.assert_not_awaited()
    mailbox_store.create_configured_binding.assert_not_awaited()


async def test_prepare_classifies_invalid_encrypted_credentials() -> None:
    """Malformed persisted credentials enter bounded terminal owner cleanup."""
    repository = MagicMock(spec=ExternalChannelRepository)
    repository.get_resource = AsyncMock(return_value=_resource())
    repository.get_connection_configuration = AsyncMock(
        return_value=ExternalChannelConnectionConfiguration.model_construct(
            provider=ExternalChannelProvider.DISCORD,
            encrypted_credentials="ciphertext",
            provider_config={
                "provider": "discord",
                "target_guild_id": "100",
                "thread_auto_archive_duration_minutes": 1440,
            },
        )
    )
    codec = MagicMock(spec=ExternalChannelCredentialsCodec)
    codec.decrypt.side_effect = InvalidToken
    service = _service(repository=repository, credentials_codec=codec)

    with pytest.raises(ExternalChannelIngressProvisioningError) as error:
        await service.prepare(owner=_owner())

    assert error.value.category == "credentials_invalid"
    assert error.value.retryable is False


async def test_prepare_classifies_non_utf8_encrypted_credentials() -> None:
    """A decryptable non-UTF-8 payload is a bounded credential failure."""
    repository = MagicMock(spec=ExternalChannelRepository)
    repository.get_resource = AsyncMock(return_value=_resource())
    repository.get_connection_configuration = AsyncMock(
        return_value=ExternalChannelConnectionConfiguration.model_construct(
            provider=ExternalChannelProvider.DISCORD,
            encrypted_credentials="ciphertext",
            provider_config={
                "provider": "discord",
                "target_guild_id": "100",
                "thread_auto_archive_duration_minutes": 1440,
            },
        )
    )
    codec = MagicMock(spec=ExternalChannelCredentialsCodec)
    codec.decrypt.side_effect = UnicodeDecodeError(
        "utf-8",
        b"\xff",
        0,
        1,
        "invalid start byte",
    )
    service = _service(repository=repository, credentials_codec=codec)

    with pytest.raises(ExternalChannelIngressProvisioningError) as error:
        await service.prepare(owner=_owner())

    assert error.value.category == "credentials_invalid"
    assert error.value.retryable is False


@pytest.mark.parametrize(
    ("initial_provider", "initial_invocation", "tracker_visibility"),
    [
        (ExternalChannelProvider.DISCORD, False, "hidden"),
        (ExternalChannelProvider.DISCORD, True, "visible"),
        (ExternalChannelProvider.SLACK, False, "hidden"),
        (ExternalChannelProvider.SLACK, True, "visible"),
    ],
)
async def test_complete_uses_caller_transaction(
    initial_provider: ExternalChannelProvider,
    initial_invocation: bool,
    tracker_visibility: str,
) -> None:
    """The ready transition uses one caller-owned transaction for every DB effect."""
    transaction: AsyncSession = MagicMock(spec=AsyncSession)
    repository = MagicMock(spec=ExternalChannelRepository)
    repository.lock_connection_for_routing = AsyncMock(
        return_value=SimpleNamespace(id="connection-1")
    )
    repository.lock_resource = AsyncMock(return_value=_resource())
    repository.get_routable_route_by_id = AsyncMock(
        return_value=ExternalChannelAgentRoute.model_construct(
            id="route-1",
            connection_id="connection-1",
            agent_id="agent-1",
        )
    )
    repository.lock_active_participation_setting = AsyncMock(
        return_value=ExternalChannelParticipationSetting.model_construct(
            id="setting-1",
            connection_id="connection-1",
            provider_parent_channel_id="200",
            route_id="route-1",
            location=ExternalChannelConversationLocation.THREADS,
            response_mode=ExternalChannelResponseMode.ALL_MESSAGES,
            settings_generation=3,
        )
    )
    work_repository = MagicMock(spec=ExternalChannelRepository)
    work_repository.record_discord_delivery_channel = AsyncMock(return_value="400")
    binding = ExternalChannelBinding.model_construct(
        id="binding-1",
        resource_id="resource-1",
        route_id="route-1",
        agent_session_id="session-1",
        response_mode=ExternalChannelResponseMode.ALL_MESSAGES,
        disconnected_at=None,
    )
    presence_plan = make_provider_effect_plan("joined-presence")
    progress_plan = make_provider_effect_plan("initial-progress")
    configured = ExternalChannelConfiguredBindingResult(
        binding=binding,
        session_created=True,
        control_plans=(presence_plan, progress_plan),
    )
    mailbox_store = MagicMock(spec=ExternalChannelMailboxIngestionStore)
    mailbox_store.create_configured_binding = AsyncMock(return_value=configured)
    service = _service(
        repository=repository,
        work_repository=work_repository,
        mailbox_store=mailbox_store,
    )

    completed = await service.complete(
        transaction,
        owner=_owner(),
        preparation=ExternalChannelIngressProviderPreparation(
            target_resource_id="resource-1",
            delivery_channel_id="400",
            initial_thread_title="Azents thread",
        ),
        initial_provider=initial_provider,
        initial_invocation=initial_invocation,
    )

    assert completed is configured
    work_repository.record_discord_delivery_channel.assert_awaited_once_with(
        transaction,
        resource_id="resource-1",
        delivery_channel_id="400",
        initial_thread_title="Azents thread",
    )
    mailbox_store.create_configured_binding.assert_awaited_once_with(
        transaction,
        resource_id="resource-1",
        route_id="route-1",
        response_mode=ExternalChannelResponseMode.ALL_MESSAGES,
        tracker_visibility=tracker_visibility,
    )


async def test_complete_rejects_changed_participation_generation() -> None:
    """A stale configured target terminalizes before Binding or Session creation."""
    transaction: AsyncSession = MagicMock(spec=AsyncSession)
    repository = MagicMock(spec=ExternalChannelRepository)
    repository.lock_connection_for_routing = AsyncMock(
        return_value=SimpleNamespace(id="connection-1")
    )
    repository.lock_resource = AsyncMock(return_value=_resource())
    repository.get_routable_route_by_id = AsyncMock(
        return_value=ExternalChannelAgentRoute.model_construct(
            id="route-1",
            connection_id="connection-1",
            agent_id="agent-1",
        )
    )
    repository.lock_active_participation_setting = AsyncMock(
        return_value=ExternalChannelParticipationSetting.model_construct(
            id="setting-1",
            connection_id="connection-1",
            provider_parent_channel_id="200",
            route_id="route-1",
            location=ExternalChannelConversationLocation.THREADS,
            response_mode=ExternalChannelResponseMode.ALL_MESSAGES,
            settings_generation=4,
        )
    )
    mailbox_store = MagicMock(spec=ExternalChannelMailboxIngestionStore)
    mailbox_store.create_configured_binding = AsyncMock()
    service = _service(repository=repository, mailbox_store=mailbox_store)

    with pytest.raises(ExternalChannelIngressProvisioningError) as error:
        await service.complete(
            transaction,
            owner=_owner(),
            preparation=ExternalChannelIngressProviderPreparation(
                target_resource_id="resource-1",
                delivery_channel_id=None,
                initial_thread_title=None,
            ),
            initial_provider=ExternalChannelProvider.DISCORD,
            initial_invocation=True,
        )

    assert error.value.category == "ownership_stale"
    assert error.value.retryable is False
    mailbox_store.create_configured_binding.assert_not_awaited()
