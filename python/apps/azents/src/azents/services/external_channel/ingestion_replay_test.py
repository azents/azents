"""Tests for content-free selector and access ingestion replay."""

import datetime
from contextlib import AbstractAsyncContextManager
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest
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
from azents.services.external_channel.ingestion import (
    ExternalChannelIngestionOperation,
    ExternalChannelIngestionOutcome,
    ExternalChannelIngestionOutcomeKind,
    ExternalChannelIngestionReason,
    ExternalChannelIngressAuthorityKind,
)
from azents.services.external_channel.ingestion_replay import (
    ExternalChannelIngestionReplayService,
    ExternalChannelIngestionReplayUnavailable,
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
) -> ExternalChannelIngestionReplayService:
    return ExternalChannelIngestionReplayService(
        session_manager=cast(Any, _SessionManager()),
        repository=cast(Any, repository),
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
        initial_title_eligible=True,
        deadline=ExternalChannelOperationDeadline(
            datetime.datetime.now(datetime.UTC) + datetime.timedelta(seconds=30)
        ),
    )

    assert outcome is expected
    replay = ingestion.ingest.await_args.args[0]
    assert replay.operation is ExternalChannelIngestionOperation.ACCESS_ALLOW
    assert replay.initial_title_eligible
    assert replay.authority.kind is ExternalChannelIngressAuthorityKind.DURABLE_REPLAY
    assert replay.authority.lease_owner is None
    assert replay.locator.trigger_provider_message_id == "2.000000"
    assert replay.locator.delivery_thread_key == "2.000000"
    assert replay.locator.provider_event_type == "unknown"
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
                labels={
                    "provider_event_type": "discord_message_create",
                    "thread_id": "thread-2",
                },
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
        initial_title_eligible=False,
        deadline=ExternalChannelOperationDeadline(
            datetime.datetime.now(datetime.UTC) + datetime.timedelta(seconds=30)
        ),
    )

    replay = ingestion.ingest.await_args.args[0]
    assert replay.locator.trigger_provider_message_id == "message-2"
    assert replay.locator.delivery_thread_key == "thread-2"
    assert replay.authority.kind is ExternalChannelIngressAuthorityKind.DURABLE_REPLAY


async def test_access_allow_retains_unresolved_discord_root_for_durable_ingestion() -> (
    None
):
    """Discord parent replay delegates thread provisioning to durable ingestion."""
    guild_id = "200000000000000001"
    channel_id = "400000000000000001"
    message_id = "500000000000000001"
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
    repository = SimpleNamespace(
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
                    "provider_event_type": "discord_message_create",
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
    service = _service(repository=repository, ingestion=ingestion)

    outcome = await service.replay_access_allow(
        access_request_id="access-1",
        initial_title_eligible=False,
        deadline=ExternalChannelOperationDeadline(
            datetime.datetime.now(datetime.UTC) + datetime.timedelta(seconds=30)
        ),
    )

    replay = ingestion.ingest.await_args.args[0]
    assert outcome.kind is ExternalChannelIngestionOutcomeKind.ACCEPTED
    assert replay.locator.delivery_thread_key == message_id
    assert replay.locator.provider_parent_channel_id == channel_id
    assert replay.locator.trigger_provider_message_id == message_id


@pytest.mark.parametrize(
    ("connection_status", "replay_available"),
    [
        (ExternalChannelConnectionStatus.RECONNECT_REQUIRED, True),
        (ExternalChannelConnectionStatus.CONFIGURING, False),
        (ExternalChannelConnectionStatus.DISCONNECTING, False),
        (ExternalChannelConnectionStatus.DISCONNECTED, False),
    ],
)
async def test_access_allow_replay_uses_durable_connection_authority(
    connection_status: ExternalChannelConnectionStatus,
    replay_available: bool,
) -> None:
    """Durable replay ignores transient ingress health but rejects terminal owners."""
    repository = SimpleNamespace(
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
                status=connection_status,
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
                    "provider_event_type": "discord_message_create",
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
    expected = ExternalChannelIngestionOutcome(
        kind=ExternalChannelIngestionOutcomeKind.ACCEPTED,
        reason=ExternalChannelIngestionReason.ACCEPTED,
        mailbox_item_id="mailbox-1",
        control_delivery_attempt_id=None,
        connection_id=None,
    )
    ingestion = SimpleNamespace(ingest=AsyncMock(return_value=expected))
    service = _service(repository=repository, ingestion=ingestion)

    if replay_available:
        outcome = await service.replay_access_allow(
            access_request_id="access-1",
            initial_title_eligible=False,
            deadline=ExternalChannelOperationDeadline(
                datetime.datetime.now(datetime.UTC) + datetime.timedelta(seconds=30)
            ),
        )
        assert outcome is expected
        ingestion.ingest.assert_awaited_once()
    else:
        with pytest.raises(ExternalChannelIngestionReplayUnavailable):
            await service.replay_access_allow(
                access_request_id="access-1",
                initial_title_eligible=False,
                deadline=ExternalChannelOperationDeadline(
                    datetime.datetime.now(datetime.UTC) + datetime.timedelta(seconds=30)
                ),
            )

        ingestion.ingest.assert_not_awaited()


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
                labels={
                    "provider_event_type": "app_mention",
                    "thread_ts": "2.000000",
                },
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
