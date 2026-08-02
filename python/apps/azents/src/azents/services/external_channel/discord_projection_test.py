"""Discord initial-title projection proof predicate tests."""

import asyncio
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
    ExternalChannelDiscordThreadTitleStatus,
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
    DiscordThreadTitleResult,
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


def _title_result(name: str) -> DiscordThreadTitleResult:
    """Build one exact complete direct thread-channel title observation."""
    return DiscordThreadTitleResult(
        status="present",
        observed_thread=DiscordObservedThread(
            channel_id="thread-001",
            guild_id="guild-001",
            parent_channel_id="parent-001",
            root_message_id="root-001",
            owner_id="bot-001",
            name=name,
            created_at=datetime.datetime(2026, 8, 2, 1, tzinfo=datetime.UTC),
        ),
        error_kind=None,
        error_summary=None,
    )


def _title_projection() -> ExternalChannelDiscordThreadTitleProjection:
    """Build one currently claimed title projection for reconciliation tests."""
    return ExternalChannelDiscordThreadTitleProjection.model_construct(
        id="projection-001",
        resource_id="resource-001",
        binding_id="binding-001",
        agent_session_id="session-001",
        session_title_candidate_id="candidate-001",
        provisioning_protocol_version=(
            SUPPORTED_DISCORD_THREAD_TITLE_PROVISIONING_PROTOCOL_VERSION
        ),
        requested_provisional_title="Stored provisional title",
        admission_connection_id="connection-001",
        admission_guild_id="guild-001",
        admission_parent_channel_id="parent-001",
        admission_root_message_id="root-001",
        admission_trigger_provider_message_key="discord:guild-001:root-001",
        thread_channel_id="thread-001",
        expected_provisional_title="Stored provisional title",
        desired_title="Generated final title",
        title_generation_event_id="event-001",
        title_attempt_count=1,
        title_claimed_at=datetime.datetime(2026, 8, 2, 1, tzinfo=datetime.UTC),
        title_status=ExternalChannelDiscordThreadTitleStatus.ATTEMPTING,
    )


def _title_service(
    discord_client: MagicMock,
) -> DiscordProjectionReconciliationService:
    """Construct a projection reconciler with test-owned title collaborators."""
    return DiscordProjectionReconciliationService(
        session_manager=cast(SessionManager[AsyncSession], MagicMock()),
        title_repository=cast(ExternalChannelTitleRepository, MagicMock()),
        authority_loader=cast(DiscordProjectionAuthorityLoader, MagicMock()),
        discord_client=cast(DiscordDeliveryClient, discord_client),
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
async def test_title_reconciliation_settles_already_desired_name_without_patch() -> (
    None
):
    """A title GET recognizing the desired name never sends another PATCH."""
    projection = _title_projection()
    discord_client = MagicMock(spec=DiscordDeliveryClient)
    discord_client.read_thread_channel = AsyncMock(
        return_value=_title_result("Generated final title")
    )
    discord_client.patch_thread_name = AsyncMock()
    service = _title_service(discord_client)
    service._load_title_authority = AsyncMock(  # pyright: ignore[reportPrivateUsage]
        return_value=SimpleNamespace(
            bot_token="token-001",
            bot_user_id="bot-001",
            delivery_channel_id="thread-001",
        )
    )
    service._settle_title_applied = AsyncMock(  # pyright: ignore[reportPrivateUsage]
        return_value="applied"
    )

    outcome = await service._reconcile_title(  # pyright: ignore[reportPrivateUsage]
        projection,
        now=datetime.datetime(2026, 8, 2, 1, tzinfo=datetime.UTC),
    )

    assert outcome == "applied"
    discord_client.patch_thread_name.assert_not_awaited()


@pytest.mark.asyncio
async def test_title_reconciliation_relinquishes_changed_target_before_get() -> None:
    """A target changed after claim makes no title provider call."""
    projection = _title_projection()
    discord_client = MagicMock(spec=DiscordDeliveryClient)
    discord_client.read_thread_channel = AsyncMock()
    discord_client.patch_thread_name = AsyncMock()
    service = _title_service(discord_client)
    service._load_title_authority = AsyncMock(  # pyright: ignore[reportPrivateUsage]
        return_value=SimpleNamespace(
            bot_token="token-001",
            bot_user_id="bot-001",
            delivery_channel_id="other-thread",
        )
    )
    relinquished = AsyncMock(return_value="relinquished")
    service._settle_title_relinquished = relinquished  # pyright: ignore[reportPrivateUsage]

    outcome = await service._reconcile_title(  # pyright: ignore[reportPrivateUsage]
        projection,
        now=datetime.datetime(2026, 8, 2, 1, tzinfo=datetime.UTC),
    )

    assert outcome == "relinquished"
    discord_client.read_thread_channel.assert_not_awaited()
    discord_client.patch_thread_name.assert_not_awaited()
    assert relinquished.await_args is not None
    assert relinquished.await_args.kwargs["reason"] == "delivery_channel_conflict"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("candidate_status", "consumed_event_id"),
    [
        (ExternalChannelSessionTitleCandidateStatus.PENDING, None),
        (ExternalChannelSessionTitleCandidateStatus.CONSUMED, "event-other"),
    ],
)
async def test_title_authority_rejects_candidate_without_exact_consumed_event(
    candidate_status: ExternalChannelSessionTitleCandidateStatus,
    consumed_event_id: str | None,
) -> None:
    """Pending or wrong-event candidates make no final-title provider call."""
    projection = _title_projection()
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
            labels={"delivery_channel_id": "thread-001"},
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
            admission_provisional_title="Stored provisional title",
            status=candidate_status,
            consumed_event_id=consumed_event_id,
        )
    )
    loader = DiscordProjectionAuthorityLoader(
        external_channel_repository=external_repository,
        agent_repository=MagicMock(),
        agent_session_repository=MagicMock(),
        title_repository=title_repository,
        credentials_codec=MagicMock(),
    )
    session = MagicMock()
    scope = MagicMock()
    scope.__aenter__ = AsyncMock(return_value=session)
    scope.__aexit__ = AsyncMock(return_value=None)
    discord_client = MagicMock(spec=DiscordDeliveryClient)
    discord_client.read_thread_channel = AsyncMock()
    discord_client.patch_thread_name = AsyncMock()
    service = DiscordProjectionReconciliationService(
        session_manager=cast(
            SessionManager[AsyncSession], MagicMock(return_value=scope)
        ),
        title_repository=cast(ExternalChannelTitleRepository, title_repository),
        authority_loader=loader,
        discord_client=cast(DiscordDeliveryClient, discord_client),
    )
    service._fail_title = AsyncMock(  # pyright: ignore[reportPrivateUsage]
        return_value="failed"
    )

    outcome = await service._reconcile_title(  # pyright: ignore[reportPrivateUsage]
        projection,
        now=datetime.datetime(2026, 8, 2, 1, tzinfo=datetime.UTC),
    )

    assert outcome == "failed"
    external_repository.get_agent_route.assert_not_called()
    discord_client.read_thread_channel.assert_not_awaited()
    discord_client.patch_thread_name.assert_not_awaited()


@pytest.mark.asyncio
async def test_title_reconciliation_relinquishes_takeover_without_patch() -> None:
    """A human or provider name change preserves the observed provider name."""
    projection = _title_projection()
    discord_client = MagicMock(spec=DiscordDeliveryClient)
    discord_client.read_thread_channel = AsyncMock(
        return_value=_title_result("Human renamed thread")
    )
    discord_client.patch_thread_name = AsyncMock()
    service = _title_service(discord_client)
    service._load_title_authority = AsyncMock(  # pyright: ignore[reportPrivateUsage]
        return_value=SimpleNamespace(
            bot_token="token-001",
            bot_user_id="bot-001",
            delivery_channel_id="thread-001",
        )
    )
    relinquished = AsyncMock(return_value="relinquished")
    service._settle_title_relinquished = relinquished  # pyright: ignore[reportPrivateUsage]

    outcome = await service._reconcile_title(  # pyright: ignore[reportPrivateUsage]
        projection,
        now=datetime.datetime(2026, 8, 2, 1, tzinfo=datetime.UTC),
    )

    assert outcome == "relinquished"
    discord_client.patch_thread_name.assert_not_awaited()
    assert relinquished.await_args is not None
    assert relinquished.await_args.kwargs["reason"] == "provider_thread_name_taken_over"


@pytest.mark.asyncio
async def test_title_reconciliation_patches_only_exact_provisional_name() -> None:
    """One adjacent authority reload fences the only allowed final-title PATCH."""
    projection = _title_projection()
    discord_client = MagicMock(spec=DiscordDeliveryClient)
    discord_client.read_thread_channel = AsyncMock(
        return_value=_title_result("Stored provisional title")
    )
    discord_client.patch_thread_name = AsyncMock(
        return_value=_title_result("Generated final title")
    )
    service = _title_service(discord_client)
    service._load_title_authority = AsyncMock(  # pyright: ignore[reportPrivateUsage]
        return_value=SimpleNamespace(
            bot_token="token-001",
            bot_user_id="bot-001",
            delivery_channel_id="thread-001",
        )
    )
    service._settle_title_applied = AsyncMock(  # pyright: ignore[reportPrivateUsage]
        return_value="applied"
    )

    outcome = await service._reconcile_title(  # pyright: ignore[reportPrivateUsage]
        projection,
        now=datetime.datetime(2026, 8, 2, 1, tzinfo=datetime.UTC),
    )

    assert outcome == "applied"
    assert service._load_title_authority.await_count == 2  # pyright: ignore[reportPrivateUsage]
    discord_client.patch_thread_name.assert_awaited_once_with(
        bot_token="token-001",
        guild_id="guild-001",
        parent_channel_id="parent-001",
        root_message_id="root-001",
        thread_channel_id="thread-001",
        name="Generated final title",
    )


@pytest.mark.asyncio
async def test_title_reconciliation_relinquishes_target_changed_before_patch() -> None:
    """A canonical target race after GET prevents the title PATCH."""
    projection = _title_projection()
    discord_client = MagicMock(spec=DiscordDeliveryClient)
    discord_client.read_thread_channel = AsyncMock(
        return_value=_title_result("Stored provisional title")
    )
    discord_client.patch_thread_name = AsyncMock()
    service = _title_service(discord_client)
    service._load_title_authority = AsyncMock(  # pyright: ignore[reportPrivateUsage]
        side_effect=[
            SimpleNamespace(
                bot_token="token-001",
                bot_user_id="bot-001",
                delivery_channel_id="thread-001",
            ),
            SimpleNamespace(
                bot_token="token-001",
                bot_user_id="bot-001",
                delivery_channel_id="other-thread",
            ),
        ]
    )
    relinquished = AsyncMock(return_value="relinquished")
    service._settle_title_relinquished = relinquished  # pyright: ignore[reportPrivateUsage]

    outcome = await service._reconcile_title(  # pyright: ignore[reportPrivateUsage]
        projection,
        now=datetime.datetime(2026, 8, 2, 1, tzinfo=datetime.UTC),
    )

    assert outcome == "relinquished"
    discord_client.read_thread_channel.assert_awaited_once()
    discord_client.patch_thread_name.assert_not_awaited()
    assert relinquished.await_args is not None
    assert relinquished.await_args.kwargs["reason"] == "delivery_channel_conflict"


@pytest.mark.asyncio
async def test_title_reconciliation_recovers_ambiguous_patch_with_get() -> None:
    """A possibly committed PATCH always observes the thread before a retry."""
    projection = _title_projection()
    unknown = DiscordThreadTitleResult(
        status="unknown",
        observed_thread=None,
        error_kind="transport_unknown",
        error_summary="Discord title mutation transport outcome was unknown.",
    )
    discord_client = MagicMock(spec=DiscordDeliveryClient)
    discord_client.read_thread_channel = AsyncMock(
        side_effect=[
            _title_result("Stored provisional title"),
            _title_result("Generated final title"),
        ]
    )
    discord_client.patch_thread_name = AsyncMock(return_value=unknown)
    service = _title_service(discord_client)
    service._load_title_authority = AsyncMock(  # pyright: ignore[reportPrivateUsage]
        return_value=SimpleNamespace(
            bot_token="token-001",
            bot_user_id="bot-001",
            delivery_channel_id="thread-001",
        )
    )
    service._settle_title_applied = AsyncMock(  # pyright: ignore[reportPrivateUsage]
        return_value="applied"
    )

    outcome = await service._reconcile_title(  # pyright: ignore[reportPrivateUsage]
        projection,
        now=datetime.datetime(2026, 8, 2, 1, tzinfo=datetime.UTC),
    )

    assert outcome == "applied"
    assert discord_client.read_thread_channel.await_count == 2


@pytest.mark.asyncio
async def test_title_reconciliation_reraises_cancellation_without_settlement() -> None:
    """Cancellation leaves the durable claim for stale GET-first recovery."""
    projection = _title_projection()
    discord_client = MagicMock(spec=DiscordDeliveryClient)
    discord_client.read_thread_channel = AsyncMock(side_effect=asyncio.CancelledError)
    service = _title_service(discord_client)
    service._load_title_authority = AsyncMock(  # pyright: ignore[reportPrivateUsage]
        return_value=SimpleNamespace(
            bot_token="token-001",
            bot_user_id="bot-001",
            delivery_channel_id="thread-001",
        )
    )
    service._retry_title = AsyncMock()  # pyright: ignore[reportPrivateUsage]
    service._fail_title = AsyncMock()  # pyright: ignore[reportPrivateUsage]
    service._settle_title_applied = AsyncMock()  # pyright: ignore[reportPrivateUsage]
    service._settle_title_relinquished = AsyncMock()  # pyright: ignore[reportPrivateUsage]

    with pytest.raises(asyncio.CancelledError):
        await service._reconcile_title(  # pyright: ignore[reportPrivateUsage]
            projection,
            now=datetime.datetime(2026, 8, 2, 1, tzinfo=datetime.UTC),
        )

    service._retry_title.assert_not_awaited()  # pyright: ignore[reportPrivateUsage]
    service._fail_title.assert_not_awaited()  # pyright: ignore[reportPrivateUsage]
    service._settle_title_applied.assert_not_awaited()  # pyright: ignore[reportPrivateUsage]
    service._settle_title_relinquished.assert_not_awaited()  # pyright: ignore[reportPrivateUsage]


@pytest.mark.asyncio
async def test_title_drain_claims_one_bounded_batch_before_reconciliation() -> None:
    """Claimed final-title rows are committed before any provider operation."""
    projection = _title_projection()
    session = MagicMock()
    session.commit = AsyncMock()
    scope = MagicMock()
    scope.__aenter__ = AsyncMock(return_value=session)
    scope.__aexit__ = AsyncMock(return_value=None)
    session_manager = MagicMock(return_value=scope)
    title_repository = MagicMock()
    title_repository.claim_due_titles = AsyncMock(return_value=(projection,))
    service = DiscordProjectionReconciliationService(
        session_manager=cast(SessionManager[AsyncSession], session_manager),
        title_repository=cast(ExternalChannelTitleRepository, title_repository),
        authority_loader=cast(DiscordProjectionAuthorityLoader, MagicMock()),
        discord_client=cast(DiscordDeliveryClient, MagicMock()),
        limit=2,
    )
    service._reconcile_title = AsyncMock(  # pyright: ignore[reportPrivateUsage]
        return_value="applied"
    )
    now = datetime.datetime(2026, 8, 2, 1, tzinfo=datetime.UTC)

    result = await service.drain_titles_once(now=now)

    assert result.claimed == 1
    assert result.applied == 1
    title_repository.claim_due_titles.assert_awaited_once_with(
        session,
        now=now,
        stale_before=now - datetime.timedelta(minutes=2),
        limit=2,
    )
    session.commit.assert_awaited_once()


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
