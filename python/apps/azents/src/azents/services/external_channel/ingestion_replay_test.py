"""Tests for content-free selector and access ingestion replay."""

import datetime
from contextlib import AbstractAsyncContextManager
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, Mock

from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    ExternalChannelAccessRequestStatus,
    ExternalChannelAppMode,
    ExternalChannelConnectionStatus,
    ExternalChannelConversationScopeKind,
    ExternalChannelIngressProfile,
    ExternalChannelInteractionStatus,
    ExternalChannelPrincipalAuthorType,
    ExternalChannelProvider,
    ExternalChannelResourceStatus,
    ExternalChannelTransport,
)
from azents.services.external_channel.conversation import (
    ExternalChannelOperationDeadline,
)
from azents.services.external_channel.data import DiscordConnectionCredentials
from azents.services.external_channel.discord_delivery import DiscordDeliveryResult
from azents.services.external_channel.ingestion import (
    ExternalChannelIngestionOperation,
    ExternalChannelIngestionOutcome,
    ExternalChannelIngestionOutcomeKind,
    ExternalChannelIngestionReason,
    ExternalChannelIngressAuthorityKind,
)
from azents.services.external_channel.ingestion_replay import (
    ExternalChannelIngestionReplayService,
)


class _SessionContext(AbstractAsyncContextManager[AsyncSession]):
    async def __aenter__(self) -> AsyncSession:
        return cast(AsyncSession, SimpleNamespace(commit=AsyncMock()))

    async def __aexit__(self, *args: object) -> None:
        return None


class _SessionManager:
    def __call__(self) -> AbstractAsyncContextManager[AsyncSession]:
        return _SessionContext()


def _service(
    *,
    repository: object,
    ingestion: object,
    work_repository: object | None = None,
    credentials_codec: object | None = None,
    discord_client: object | None = None,
) -> ExternalChannelIngestionReplayService:
    return ExternalChannelIngestionReplayService(
        session_manager=cast(Any, _SessionManager()),
        repository=cast(Any, repository),
        work_repository=cast(
            Any,
            work_repository
            or SimpleNamespace(record_discord_delivery_channel=AsyncMock()),
        ),
        credentials_codec=cast(
            Any,
            credentials_codec or SimpleNamespace(decrypt=Mock()),
        ),
        discord_client=cast(
            Any,
            discord_client or SimpleNamespace(ensure_thread=AsyncMock()),
        ),
        ingestion_service=cast(Any, ingestion),
    )


async def test_access_allow_rebuilds_slack_replay_without_content() -> None:
    request = SimpleNamespace(
        id="access-1",
        status=ExternalChannelAccessRequestStatus.ALLOWED,
        connection_id="connection-1",
        conversation_position_id="position-1",
        resource_id="resource-1",
        trigger_provider_message_key="slack:tenant-1:channel-1:2.000000",
        principal_id="principal-1",
        route_id="route-1",
        range_start_position="00000000000000000001",
        trigger_position="00000000000000000002",
    )
    repository = SimpleNamespace(
        get_access_request=AsyncMock(return_value=request),
        get_connection_configuration=AsyncMock(
            return_value=SimpleNamespace(
                id="connection-1",
                provider=ExternalChannelProvider.SLACK,
                provider_tenant_id="tenant-1",
                ingress_profile=ExternalChannelIngressProfile.SLACK_SOCKET,
                configuration_generation=4,
                status=ExternalChannelConnectionStatus.ACTIVE,
                transport=ExternalChannelTransport.SOCKET,
                app_mode=ExternalChannelAppMode.SINGLE,
            )
        ),
        get_conversation_position=AsyncMock(
            return_value=SimpleNamespace(
                id="position-1",
                connection_id="connection-1",
                scope_kind=ExternalChannelConversationScopeKind.PARENT_CHANNEL,
                provider_channel_id="channel-1",
                provider_thread_key=None,
                read_through_position="00000000000000000009",
            )
        ),
        get_resource=AsyncMock(
            return_value=SimpleNamespace(
                id="resource-1",
                connection_id="connection-1",
                provider_resource_key="slack:tenant-1:channel-1:2.000000",
                labels={"thread_ts": "2.000000"},
                status=ExternalChannelResourceStatus.ACTIVE,
            )
        ),
        get_principal=AsyncMock(
            return_value=SimpleNamespace(
                id="principal-1",
                provider=ExternalChannelProvider.SLACK,
                provider_tenant_id="tenant-1",
                provider_user_id="participant-1",
                author_type=ExternalChannelPrincipalAuthorType.HUMAN,
            )
        ),
        get_agent_route=AsyncMock(
            return_value=SimpleNamespace(
                id="route-1",
                connection_id="connection-1",
            )
        ),
    )
    expected = ExternalChannelIngestionOutcome(
        kind=ExternalChannelIngestionOutcomeKind.ACCEPTED,
        reason=ExternalChannelIngestionReason.ACCEPTED,
        mailbox_item_id="batch-1",
        control_delivery_attempt_id=None,
        connection_id=None,
    )
    ingestion = SimpleNamespace(ingest=AsyncMock(return_value=expected))
    service = _service(repository=repository, ingestion=ingestion)

    outcome = await service.replay_access_allow(
        access_request_id="access-1",
        deadline=ExternalChannelOperationDeadline(
            datetime.datetime.now(datetime.UTC) + datetime.timedelta(seconds=30)
        ),
    )

    assert outcome is expected
    replay = ingestion.ingest.await_args.args[0]
    assert replay.operation is ExternalChannelIngestionOperation.ACCESS_ALLOW
    assert replay.authority.kind is ExternalChannelIngressAuthorityKind.DURABLE_REPLAY
    assert replay.authority.lease_owner is None
    assert replay.locator.trigger_provider_message_id == "2.000000"
    assert replay.locator.delivery_thread_key == "2.000000"
    assert replay.locator.provider_user_id == "participant-1"
    assert replay.replay_boundary.principal_id == "principal-1"
    assert replay.replay_boundary.range_start_position == "00000000000000000001"
    assert "participant-1" not in repr(replay)
    assert "channel-1" not in repr(replay)


async def test_access_allow_rebuilds_discord_replay_from_legacy_thread_label() -> None:
    """Discord replay accepts the canonical thread label retained before cutover."""
    request = SimpleNamespace(
        id="access-1",
        status=ExternalChannelAccessRequestStatus.ALLOWED,
        connection_id="connection-1",
        conversation_position_id="position-1",
        resource_id="resource-1",
        trigger_provider_message_key="discord:guild-1:message-2",
        principal_id="principal-1",
        route_id="route-1",
        range_start_position=None,
        trigger_position="00000000000000000002",
    )
    repository = SimpleNamespace(
        get_access_request=AsyncMock(return_value=request),
        get_connection_configuration=AsyncMock(
            return_value=SimpleNamespace(
                id="connection-1",
                provider=ExternalChannelProvider.DISCORD,
                provider_tenant_id="guild-1",
                ingress_profile=(ExternalChannelIngressProfile.DISCORD_GATEWAY_HTTP),
                configuration_generation=4,
                status=ExternalChannelConnectionStatus.ACTIVE,
                transport=ExternalChannelTransport.HTTP,
                app_mode=ExternalChannelAppMode.SINGLE,
            )
        ),
        get_conversation_position=AsyncMock(
            return_value=SimpleNamespace(
                id="position-1",
                connection_id="connection-1",
                scope_kind=ExternalChannelConversationScopeKind.PARENT_CHANNEL,
                provider_channel_id="channel-1",
                provider_thread_key=None,
                read_through_position="00000000000000000009",
            )
        ),
        get_resource=AsyncMock(
            return_value=SimpleNamespace(
                id="resource-1",
                connection_id="connection-1",
                provider_resource_key="discord:guild-1:message-2",
                labels={"thread_id": "thread-2"},
                status=ExternalChannelResourceStatus.ACTIVE,
            )
        ),
        get_principal=AsyncMock(
            return_value=SimpleNamespace(
                id="principal-1",
                provider=ExternalChannelProvider.DISCORD,
                provider_tenant_id="guild-1",
                provider_user_id="participant-1",
                author_type=ExternalChannelPrincipalAuthorType.HUMAN,
            )
        ),
        get_agent_route=AsyncMock(
            return_value=SimpleNamespace(
                id="route-1",
                connection_id="connection-1",
            )
        ),
    )
    ingestion = SimpleNamespace(
        ingest=AsyncMock(
            return_value=ExternalChannelIngestionOutcome(
                kind=ExternalChannelIngestionOutcomeKind.ACCEPTED,
                reason=ExternalChannelIngestionReason.ACCEPTED,
                mailbox_item_id=None,
                control_delivery_attempt_id=None,
                connection_id=None,
            )
        )
    )
    service = _service(repository=repository, ingestion=ingestion)

    await service.replay_access_allow(
        access_request_id="access-1",
        deadline=ExternalChannelOperationDeadline(
            datetime.datetime.now(datetime.UTC) + datetime.timedelta(seconds=30)
        ),
    )

    replay = ingestion.ingest.await_args.args[0]
    assert replay.locator.trigger_provider_message_id == "message-2"
    assert replay.locator.delivery_thread_key == "thread-2"
    assert replay.authority.kind is ExternalChannelIngressAuthorityKind.DURABLE_REPLAY


async def test_access_allow_provisions_unresolved_discord_root_before_ingestion() -> (
    None
):
    """Discord parent replay persists a usable thread before mailbox acceptance."""
    guild_id = "200000000000000001"
    channel_id = "400000000000000001"
    message_id = "500000000000000001"
    thread_id = "700000000000000001"
    request = SimpleNamespace(
        id="access-1",
        status=ExternalChannelAccessRequestStatus.ALLOWED,
        connection_id="connection-1",
        conversation_position_id="position-1",
        resource_id="resource-1",
        trigger_provider_message_key=f"discord:{guild_id}:{message_id}",
        principal_id="principal-1",
        route_id="route-1",
        range_start_position=None,
        trigger_position="00000000000000000002",
    )
    locked_connection = SimpleNamespace(
        id="connection-1",
        provider=ExternalChannelProvider.DISCORD,
        status=ExternalChannelConnectionStatus.ACTIVE,
        provider_tenant_id=guild_id,
        configuration_generation=4,
        capabilities={"post_messages": True},
    )
    locked_resource = SimpleNamespace(
        id="resource-1",
        connection_id="connection-1",
        provider_resource_key=f"discord:{guild_id}:{message_id}",
        labels={
            "thread_id": message_id,
            "root_message_id": message_id,
            "parent_channel_id": channel_id,
        },
        status=ExternalChannelResourceStatus.ACTIVE,
    )
    repository = SimpleNamespace(
        lock_connection_for_routing=AsyncMock(return_value=locked_connection),
        lock_resource=AsyncMock(return_value=locked_resource),
        get_access_request=AsyncMock(return_value=request),
        get_connection_configuration=AsyncMock(
            return_value=SimpleNamespace(
                id="connection-1",
                provider=ExternalChannelProvider.DISCORD,
                provider_tenant_id=guild_id,
                ingress_profile=ExternalChannelIngressProfile.DISCORD_GATEWAY_HTTP,
                configuration_generation=4,
                status=ExternalChannelConnectionStatus.ACTIVE,
                transport=ExternalChannelTransport.HTTP,
                app_mode=ExternalChannelAppMode.MULTI,
                encrypted_credentials="encrypted",
                capabilities={"post_messages": True},
            )
        ),
        get_conversation_position=AsyncMock(
            return_value=SimpleNamespace(
                id="position-1",
                connection_id="connection-1",
                scope_kind=ExternalChannelConversationScopeKind.PARENT_CHANNEL,
                provider_channel_id=channel_id,
                provider_thread_key=None,
                read_through_position=None,
            )
        ),
        get_resource=AsyncMock(
            return_value=SimpleNamespace(
                id="resource-1",
                connection_id="connection-1",
                provider_resource_key=f"discord:{guild_id}:{message_id}",
                labels={
                    "thread_id": message_id,
                    "root_message_id": message_id,
                    "parent_channel_id": channel_id,
                },
                status=ExternalChannelResourceStatus.ACTIVE,
            )
        ),
        get_principal=AsyncMock(
            return_value=SimpleNamespace(
                id="principal-1",
                provider=ExternalChannelProvider.DISCORD,
                provider_tenant_id=guild_id,
                provider_user_id="participant-1",
                author_type=ExternalChannelPrincipalAuthorType.HUMAN,
            )
        ),
        get_agent_route=AsyncMock(
            return_value=SimpleNamespace(
                id="route-1",
                connection_id="connection-1",
            )
        ),
    )
    ingestion = SimpleNamespace(
        ingest=AsyncMock(
            return_value=ExternalChannelIngestionOutcome(
                kind=ExternalChannelIngestionOutcomeKind.ACCEPTED,
                reason=ExternalChannelIngestionReason.ACCEPTED,
                mailbox_item_id=None,
                control_delivery_attempt_id=None,
                connection_id=None,
            )
        )
    )
    work_repository = SimpleNamespace(
        record_discord_delivery_channel=AsyncMock(return_value=thread_id)
    )
    credentials_codec = SimpleNamespace(
        decrypt=Mock(
            return_value=DiscordConnectionCredentials(bot_token="private-bot-token")
        )
    )
    discord_client = SimpleNamespace(
        ensure_thread=AsyncMock(
            return_value=DiscordDeliveryResult(
                status="delivered",
                provider_message_key=f"discord-thread:{thread_id}",
                error_kind=None,
                error_summary=None,
            )
        )
    )
    service = _service(
        repository=repository,
        ingestion=ingestion,
        work_repository=work_repository,
        credentials_codec=credentials_codec,
        discord_client=discord_client,
    )

    outcome = await service.replay_access_allow(
        access_request_id="access-1",
        deadline=ExternalChannelOperationDeadline(
            datetime.datetime.now(datetime.UTC) + datetime.timedelta(seconds=30)
        ),
    )

    replay = ingestion.ingest.await_args.args[0]
    assert outcome.kind is ExternalChannelIngestionOutcomeKind.ACCEPTED
    assert replay.locator.delivery_thread_key == thread_id
    discord_client.ensure_thread.assert_awaited_once_with(
        bot_token="private-bot-token",
        parent_channel_id=channel_id,
        root_message_id=message_id,
    )
    record_call = work_repository.record_discord_delivery_channel.await_args
    assert record_call is not None
    assert record_call.kwargs == {
        "resource_id": "resource-1",
        "delivery_channel_id": thread_id,
    }
    assert "private-bot-token" not in repr(replay)


async def test_access_allow_stops_after_discord_connection_authority_loss() -> None:
    """A stale replay cannot provision or accept after routing authority is lost."""
    repository = SimpleNamespace(
        lock_connection_for_routing=AsyncMock(
            return_value=SimpleNamespace(
                id="connection-1",
                provider=ExternalChannelProvider.DISCORD,
                status=ExternalChannelConnectionStatus.RECONNECT_REQUIRED,
                provider_tenant_id="200",
                configuration_generation=4,
                capabilities={"post_messages": True},
            )
        ),
        lock_resource=AsyncMock(
            return_value=SimpleNamespace(
                id="resource-1",
                connection_id="connection-1",
                provider_resource_key="discord:200:500",
                labels={
                    "thread_id": "500",
                    "root_message_id": "500",
                    "parent_channel_id": "400",
                },
                status=ExternalChannelResourceStatus.ACTIVE,
            )
        ),
        get_access_request=AsyncMock(
            return_value=SimpleNamespace(
                id="access-1",
                status=ExternalChannelAccessRequestStatus.ALLOWED,
                connection_id="connection-1",
                conversation_position_id="position-1",
                resource_id="resource-1",
                trigger_provider_message_key="discord:200:500",
                principal_id="principal-1",
                route_id="route-1",
                range_start_position=None,
                trigger_position="00000000000000000500",
            )
        ),
        get_connection_configuration=AsyncMock(
            return_value=SimpleNamespace(
                id="connection-1",
                provider=ExternalChannelProvider.DISCORD,
                provider_tenant_id="200",
                ingress_profile=ExternalChannelIngressProfile.DISCORD_GATEWAY_HTTP,
                configuration_generation=4,
                status=ExternalChannelConnectionStatus.ACTIVE,
                transport=ExternalChannelTransport.HTTP,
                app_mode=ExternalChannelAppMode.MULTI,
                encrypted_credentials="encrypted",
                capabilities={"post_messages": True},
            )
        ),
        get_conversation_position=AsyncMock(
            return_value=SimpleNamespace(
                id="position-1",
                connection_id="connection-1",
                scope_kind=ExternalChannelConversationScopeKind.PARENT_CHANNEL,
                provider_channel_id="400",
                provider_thread_key=None,
                read_through_position=None,
            )
        ),
        get_resource=AsyncMock(
            return_value=SimpleNamespace(
                id="resource-1",
                connection_id="connection-1",
                provider_resource_key="discord:200:500",
                labels={
                    "thread_id": "500",
                    "root_message_id": "500",
                    "parent_channel_id": "400",
                },
                status=ExternalChannelResourceStatus.ACTIVE,
            )
        ),
        get_principal=AsyncMock(
            return_value=SimpleNamespace(
                id="principal-1",
                provider=ExternalChannelProvider.DISCORD,
                provider_tenant_id="200",
                provider_user_id="participant-1",
                author_type=ExternalChannelPrincipalAuthorType.HUMAN,
            )
        ),
        get_agent_route=AsyncMock(
            return_value=SimpleNamespace(
                id="route-1",
                connection_id="connection-1",
            )
        ),
    )
    ingestion = SimpleNamespace(ingest=AsyncMock())
    work_repository = SimpleNamespace(record_discord_delivery_channel=AsyncMock())
    discord_client = SimpleNamespace(ensure_thread=AsyncMock())
    service = _service(
        repository=repository,
        ingestion=ingestion,
        work_repository=work_repository,
        credentials_codec=SimpleNamespace(
            decrypt=Mock(
                return_value=DiscordConnectionCredentials(bot_token="private-bot-token")
            )
        ),
        discord_client=discord_client,
    )

    outcome = await service.replay_access_allow(
        access_request_id="access-1",
        deadline=ExternalChannelOperationDeadline(
            datetime.datetime.now(datetime.UTC) + datetime.timedelta(seconds=30)
        ),
    )

    assert outcome.kind is ExternalChannelIngestionOutcomeKind.RETRYABLE_FAILURE
    discord_client.ensure_thread.assert_not_awaited()
    ingestion.ingest.assert_not_awaited()
    work_repository.record_discord_delivery_channel.assert_not_awaited()


async def test_selector_replay_keeps_actor_separate_from_source_author() -> None:
    repository = SimpleNamespace(
        lock_interaction=AsyncMock(
            return_value=SimpleNamespace(
                id="interaction-1",
                principal_id="principal-actor",
                status=ExternalChannelInteractionStatus.COMPLETED,
                projection={
                    "agent_selector": {
                        "connection_id": "connection-1",
                        "resource_id": "resource-1",
                        "principal_id": "principal-actor",
                        "conversation_position_id": "position-1",
                        "trigger_provider_message_key": (
                            "slack:tenant-1:channel-1:2.000000"
                        ),
                        "range_start_position": None,
                        "trigger_position": "00000000000000000002",
                        "selected_route_id": "route-1",
                    }
                },
            )
        ),
        get_connection_configuration=AsyncMock(
            return_value=SimpleNamespace(
                id="connection-1",
                provider=ExternalChannelProvider.SLACK,
                provider_tenant_id="tenant-1",
                ingress_profile=ExternalChannelIngressProfile.SLACK_HTTP,
                configuration_generation=4,
                status=ExternalChannelConnectionStatus.ACTIVE,
                transport=ExternalChannelTransport.HTTP,
                app_mode=ExternalChannelAppMode.MULTI,
            )
        ),
        get_conversation_position=AsyncMock(
            return_value=SimpleNamespace(
                id="position-1",
                connection_id="connection-1",
                scope_kind=ExternalChannelConversationScopeKind.PARENT_CHANNEL,
                provider_channel_id="channel-1",
                provider_thread_key=None,
                read_through_position=None,
            )
        ),
        get_resource=AsyncMock(
            return_value=SimpleNamespace(
                id="resource-1",
                connection_id="connection-1",
                provider_resource_key="slack:tenant-1:channel-1:2.000000",
                labels={"thread_ts": "2.000000"},
                status=ExternalChannelResourceStatus.ACTIVE,
            )
        ),
        get_principal=AsyncMock(
            return_value=SimpleNamespace(
                id="principal-actor",
                provider=ExternalChannelProvider.SLACK,
                provider_tenant_id="tenant-1",
                provider_user_id="selector-actor",
                author_type=ExternalChannelPrincipalAuthorType.HUMAN,
            )
        ),
        get_agent_route=AsyncMock(
            return_value=SimpleNamespace(
                id="route-1",
                connection_id="connection-1",
            )
        ),
    )
    expected = ExternalChannelIngestionOutcome(
        kind=ExternalChannelIngestionOutcomeKind.ACCEPTED,
        reason=ExternalChannelIngestionReason.ACCEPTED,
        mailbox_item_id="mailbox-1",
        control_delivery_attempt_id=None,
        connection_id=None,
    )
    ingestion = SimpleNamespace(ingest=AsyncMock(return_value=expected))
    service = _service(repository=repository, ingestion=ingestion)

    outcome = await service.replay_selected_interaction(
        selector_interaction_id="interaction-1",
        principal_id="principal-actor",
        deadline=ExternalChannelOperationDeadline(
            datetime.datetime.now(datetime.UTC) + datetime.timedelta(seconds=30)
        ),
    )

    assert outcome is expected
    replay = ingestion.ingest.await_args.args[0]
    assert replay.operation is ExternalChannelIngestionOperation.SELECTOR_CONTINUATION
    assert replay.locator.provider_user_id is None
    assert replay.replay_boundary.principal_id == "principal-actor"
    assert "selector-actor" not in repr(replay)
