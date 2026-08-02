"""Discord initial-title projection proof predicate tests."""

import datetime
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    AgentSessionStatus,
    ExternalChannelAppMode,
    ExternalChannelConnectionStatus,
    ExternalChannelDiscordThreadObservationStatus,
    ExternalChannelProvider,
    ExternalChannelResourceStatus,
    ExternalChannelRouteCatalogStatus,
    ExternalChannelSessionTitleCandidateStatus,
)
from azents.rdb.session import SessionManager
from azents.repos.external_channel.data import (
    ExternalChannelDiscordThreadTitleProjection,
)
from azents.repos.external_channel.title import (
    SUPPORTED_DISCORD_THREAD_TITLE_PROVISIONING_PROTOCOL_VERSION,
    ExternalChannelTitleRepository,
)
from azents.services.external_channel.conversation import DiscordObservedThread
from azents.services.external_channel.data import DiscordConnectionCredentials
from azents.services.external_channel.discord_delivery import (
    DiscordDeliveryClient,
    DiscordThreadProvisioningResult,
)
from azents.services.external_channel.discord_projection import (
    DiscordProjectionAuthorityLoader,
    DiscordProjectionReconciliationService,
    adoption_created_after_admission,
)


def _result(created_at: datetime.datetime) -> DiscordThreadProvisioningResult:
    """Build complete current provider metadata for adoption proof tests."""
    return DiscordThreadProvisioningResult(
        status="present",
        thread_channel_id="thread-001",
        observed_thread=DiscordObservedThread(
            channel_id="thread-001",
            guild_id="guild-001",
            parent_channel_id="parent-001",
            root_message_id="root-001",
            owner_id="bot-001",
            name="Stored provisional title",
            created_at=created_at,
        ),
        error_kind=None,
        error_summary=None,
    )


def test_adoption_rejects_thread_created_before_admission_absence() -> None:
    """Adoption cannot use a thread that predates the durable absence observation."""
    observed_at = datetime.datetime(2026, 8, 2, 1, tzinfo=datetime.UTC)
    projection = ExternalChannelDiscordThreadTitleProjection.model_construct(
        admission_observed_at=observed_at
    )

    assert not adoption_created_after_admission(
        projection,
        result=_result(observed_at - datetime.timedelta(seconds=1)),
    )
    assert adoption_created_after_admission(
        projection,
        result=_result(observed_at),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "admission_status",
    [
        ExternalChannelDiscordThreadObservationStatus.UNKNOWN,
        ExternalChannelDiscordThreadObservationStatus.THREAD_PRESENT,
    ],
)
async def test_prior_preflight_recovers_present_thread_directly_without_second_post(
    admission_status: ExternalChannelDiscordThreadObservationStatus,
) -> None:
    """A later GET reconciles a preflight-fenced ambiguous create as DIRECT."""
    now = datetime.datetime(2026, 8, 2, 1, tzinfo=datetime.UTC)
    projection = ExternalChannelDiscordThreadTitleProjection.model_construct(
        provisioning_protocol_version=(
            SUPPORTED_DISCORD_THREAD_TITLE_PROVISIONING_PROTOCOL_VERSION
        ),
        preflight_absent_at=now - datetime.timedelta(seconds=1),
        admission_observation_status=admission_status,
        admission_guild_id="guild-001",
        admission_parent_channel_id="parent-001",
        admission_root_message_id="root-001",
    )
    discord_client = MagicMock(spec=DiscordDeliveryClient)
    discord_client.read_root_thread = AsyncMock(return_value=_result(now))
    discord_client.create_root_thread = AsyncMock()
    service = DiscordProjectionReconciliationService(
        session_manager=cast(SessionManager[AsyncSession], MagicMock()),
        title_repository=cast(ExternalChannelTitleRepository, MagicMock()),
        authority_loader=cast(DiscordProjectionAuthorityLoader, MagicMock()),
        discord_client=cast(DiscordDeliveryClient, discord_client),
    )
    service._load_authority = AsyncMock(  # pyright: ignore[reportPrivateUsage]
        return_value=SimpleNamespace(bot_token="token-001")
    )
    settle_existing = AsyncMock(return_value="ready")
    service._settle_existing = settle_existing  # pyright: ignore[reportPrivateUsage]

    outcome = await service._reconcile(  # pyright: ignore[reportPrivateUsage]
        projection,
        now=now,
    )

    assert outcome == "ready"
    discord_client.read_root_thread.assert_awaited_once()
    discord_client.create_root_thread.assert_not_awaited()
    assert settle_existing.await_args is not None
    assert settle_existing.await_args.kwargs["direct"] is True


@pytest.mark.asyncio
async def test_authority_loader_rejects_unsupported_protocol_without_lookups() -> None:
    """A Worker never claims authority over a newer projection protocol."""
    external_repository = MagicMock()
    loader = DiscordProjectionAuthorityLoader(
        external_channel_repository=external_repository,
        agent_repository=MagicMock(),
        agent_session_repository=MagicMock(),
        title_repository=MagicMock(),
        credentials_codec=MagicMock(),
    )
    projection = ExternalChannelDiscordThreadTitleProjection.model_construct(
        provisioning_protocol_version=(
            SUPPORTED_DISCORD_THREAD_TITLE_PROVISIONING_PROTOCOL_VERSION + 1
        )
    )

    authority = await loader.load(
        cast(AsyncSession, MagicMock()),
        projection=projection,
    )

    assert authority is None
    external_repository.get_connection_configuration.assert_not_called()


@pytest.mark.asyncio
async def test_authority_loader_rejects_relinquished_candidate_before_provider_io() -> (
    None
):
    """Candidate terminality revokes provision authority even when binding remains."""
    external_repository = MagicMock()
    external_repository.get_connection_configuration = AsyncMock(
        return_value=SimpleNamespace(
            id="connection-001",
            provider=ExternalChannelProvider.DISCORD,
            status=ExternalChannelConnectionStatus.ACTIVE,
            disconnected_at=None,
            provider_tenant_id="guild-001",
            provider_bot_user_id="bot-001",
            encrypted_credentials="ciphertext",
            app_mode=ExternalChannelAppMode.SINGLE,
        )
    )
    external_repository.get_resource = AsyncMock(
        return_value=SimpleNamespace(
            id="resource-001",
            connection_id="connection-001",
            status=ExternalChannelResourceStatus.ACTIVE,
            labels=None,
        )
    )
    external_repository.get_binding = AsyncMock(
        return_value=SimpleNamespace(
            resource_id="resource-001",
            agent_session_id="session-001",
            disconnected_at=None,
            route_id="route-001",
        )
    )
    title_repository = MagicMock()
    title_repository.get_candidate_by_identity = AsyncMock(
        return_value=SimpleNamespace(
            id="candidate-001",
            admission_provisional_title="Stored title",
            status=ExternalChannelSessionTitleCandidateStatus.RELINQUISHED,
        )
    )
    loader = DiscordProjectionAuthorityLoader(
        external_channel_repository=external_repository,
        agent_repository=MagicMock(),
        agent_session_repository=MagicMock(),
        title_repository=title_repository,
        credentials_codec=MagicMock(),
    )
    projection = ExternalChannelDiscordThreadTitleProjection.model_construct(
        provisioning_protocol_version=(
            SUPPORTED_DISCORD_THREAD_TITLE_PROVISIONING_PROTOCOL_VERSION
        ),
        admission_connection_id="connection-001",
        admission_guild_id="guild-001",
        resource_id="resource-001",
        binding_id="binding-001",
        agent_session_id="session-001",
        session_title_candidate_id="candidate-001",
        requested_provisional_title="Stored title",
        admission_trigger_provider_message_key="discord:guild-001:root-001",
    )

    authority = await loader.load(
        cast(AsyncSession, MagicMock()),
        projection=projection,
    )

    assert authority is None
    external_repository.get_agent_route.assert_not_called()


@pytest.mark.asyncio
async def test_authority_loader_rejects_stopping_session_before_provider_io() -> None:
    """A stop request revokes authority before any Discord read or mutation."""
    external_repository = MagicMock()
    external_repository.get_connection_configuration = AsyncMock(
        return_value=SimpleNamespace(
            id="connection-001",
            provider=ExternalChannelProvider.DISCORD,
            status=ExternalChannelConnectionStatus.ACTIVE,
            disconnected_at=None,
            provider_tenant_id="guild-001",
            provider_bot_user_id="bot-001",
            encrypted_credentials="ciphertext",
            app_mode=ExternalChannelAppMode.SINGLE,
        )
    )
    external_repository.get_resource = AsyncMock(
        return_value=SimpleNamespace(
            id="resource-001",
            connection_id="connection-001",
            status=ExternalChannelResourceStatus.ACTIVE,
            labels=None,
        )
    )
    external_repository.get_binding = AsyncMock(
        return_value=SimpleNamespace(
            resource_id="resource-001",
            agent_session_id="session-001",
            disconnected_at=None,
            route_id="route-001",
        )
    )
    external_repository.get_agent_route = AsyncMock(
        return_value=SimpleNamespace(
            connection_id="connection-001",
            agent_id="agent-001",
            connection_app_mode=ExternalChannelAppMode.SINGLE,
            catalog_status=ExternalChannelRouteCatalogStatus.AVAILABLE,
        )
    )
    agent_session_repository = MagicMock()
    agent_session_repository.get_by_id = AsyncMock(
        return_value=SimpleNamespace(
            agent_id="agent-001",
            status=AgentSessionStatus.ACTIVE,
            stop_requested_at=datetime.datetime(2026, 8, 2, tzinfo=datetime.UTC),
            ended_at=None,
        )
    )
    title_repository = MagicMock()
    title_repository.get_candidate_by_identity = AsyncMock(
        return_value=SimpleNamespace(
            id="candidate-001",
            admission_provisional_title="Stored title",
            status=ExternalChannelSessionTitleCandidateStatus.PENDING,
        )
    )
    agent_repository = MagicMock()
    loader = DiscordProjectionAuthorityLoader(
        external_channel_repository=external_repository,
        agent_repository=agent_repository,
        agent_session_repository=agent_session_repository,
        title_repository=title_repository,
        credentials_codec=MagicMock(
            decrypt=MagicMock(
                return_value=DiscordConnectionCredentials(bot_token="discord-secret")
            )
        ),
    )
    projection = ExternalChannelDiscordThreadTitleProjection.model_construct(
        provisioning_protocol_version=(
            SUPPORTED_DISCORD_THREAD_TITLE_PROVISIONING_PROTOCOL_VERSION
        ),
        admission_connection_id="connection-001",
        admission_guild_id="guild-001",
        resource_id="resource-001",
        binding_id="binding-001",
        agent_session_id="session-001",
        session_title_candidate_id="candidate-001",
        requested_provisional_title="Stored title",
        admission_trigger_provider_message_key="discord:guild-001:root-001",
    )

    authority = await loader.load(
        cast(AsyncSession, MagicMock()),
        projection=projection,
    )

    assert authority is None
    agent_repository.get_by_id.assert_not_called()
