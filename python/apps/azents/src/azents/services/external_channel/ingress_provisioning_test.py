"""Conversation-bound External Channel ingress provisioning tests."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import cast
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
    ExternalChannelMailboxIngestionStore,
)


def _session_manager() -> SessionManager[AsyncSession]:
    @asynccontextmanager
    async def manager() -> AsyncIterator[AsyncSession]:
        yield cast(AsyncSession, object())

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
    repository: MagicMock,
    work_repository: MagicMock | None = None,
    credentials_codec: MagicMock | None = None,
    discord_client: MagicMock | None = None,
    mailbox_store: MagicMock | None = None,
) -> ExternalChannelIngressProvisioningService:
    repository.get_connected_binding_by_resource = AsyncMock(return_value=None)
    conversation_provisioning = ExternalChannelConversationProvisioningService(
        session_manager=_session_manager(),
        repository=cast(ExternalChannelRepository, repository),
        work_repository=cast(
            ExternalChannelWorkRepository,
            work_repository or MagicMock(),
        ),
        credentials_codec=cast(
            ExternalChannelCredentialsCodec,
            credentials_codec or MagicMock(),
        ),
        discord_client=cast(
            DiscordDeliveryClient,
            discord_client or MagicMock(),
        ),
    )
    return ExternalChannelIngressProvisioningService(
        session_manager=_session_manager(),
        repository=cast(ExternalChannelRepository, repository),
        conversation_provisioning=conversation_provisioning,
        mailbox_store=cast(
            ExternalChannelMailboxIngestionStore,
            mailbox_store or MagicMock(),
        ),
    )


async def test_prepare_discord_thread_has_no_db_transition() -> None:
    """Discord provider mutation finishes before any ready-transition DB write."""
    repository = MagicMock()
    repository.get_resource = AsyncMock(return_value=_resource())
    repository.get_connection_configuration = AsyncMock(
        return_value=ExternalChannelConnectionConfiguration.model_construct(
            provider=ExternalChannelProvider.DISCORD,
            encrypted_credentials="ciphertext",
        )
    )
    codec = MagicMock()
    codec.decrypt.return_value = DiscordConnectionCredentials(bot_token="secret")
    discord = MagicMock()
    discord.ensure_thread = AsyncMock(
        return_value=DiscordDeliveryResult(
            status="delivered",
            provider_message_key="discord-thread:400",
            error_kind=None,
            error_summary=None,
            created_thread_name="Azents thread",
        )
    )
    work_repository = MagicMock()
    work_repository.record_discord_delivery_channel = AsyncMock()
    mailbox_store = MagicMock()
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
    repository = MagicMock()
    repository.get_resource = AsyncMock(return_value=_resource())
    repository.get_connection_configuration = AsyncMock(
        return_value=ExternalChannelConnectionConfiguration.model_construct(
            provider=ExternalChannelProvider.DISCORD,
            encrypted_credentials="ciphertext",
        )
    )
    codec = MagicMock()
    codec.decrypt.side_effect = InvalidToken
    service = _service(repository=repository, credentials_codec=codec)

    with pytest.raises(ExternalChannelIngressProvisioningError) as error:
        await service.prepare(owner=_owner())

    assert error.value.category == "credentials_invalid"
    assert error.value.retryable is False


async def test_prepare_classifies_non_utf8_encrypted_credentials() -> None:
    """A decryptable non-UTF-8 payload is a bounded credential failure."""
    repository = MagicMock()
    repository.get_resource = AsyncMock(return_value=_resource())
    repository.get_connection_configuration = AsyncMock(
        return_value=ExternalChannelConnectionConfiguration.model_construct(
            provider=ExternalChannelProvider.DISCORD,
            encrypted_credentials="ciphertext",
        )
    )
    codec = MagicMock()
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


async def test_complete_uses_caller_transaction() -> None:
    """The ready transition uses one caller-owned transaction for every DB effect."""
    transaction = cast(AsyncSession, object())
    repository = MagicMock()
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
    work_repository = MagicMock()
    work_repository.record_discord_delivery_channel = AsyncMock(return_value="400")
    binding = ExternalChannelBinding.model_construct(
        id="binding-1",
        resource_id="resource-1",
        route_id="route-1",
        agent_session_id="session-1",
        response_mode=ExternalChannelResponseMode.ALL_MESSAGES,
        disconnected_at=None,
    )
    mailbox_store = MagicMock()
    mailbox_store.create_configured_binding = AsyncMock(return_value=binding)
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
    )

    assert completed is binding
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
    )


async def test_complete_rejects_changed_participation_generation() -> None:
    """A stale configured target terminalizes before Binding or Session creation."""
    transaction = cast(AsyncSession, object())
    repository = MagicMock()
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
    mailbox_store = MagicMock()
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
        )

    assert error.value.category == "ownership_stale"
    assert error.value.retryable is False
    mailbox_store.create_configured_binding.assert_not_awaited()
