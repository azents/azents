"""Tests for content-free selector and access ingestion replay."""

import datetime
from contextlib import AbstractAsyncContextManager
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    ExternalChannelAccessRequestStatus,
    ExternalChannelAppMode,
    ExternalChannelConversationScopeKind,
    ExternalChannelIngressProfile,
    ExternalChannelProvider,
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
)


class _SessionContext(AbstractAsyncContextManager[AsyncSession]):
    async def __aenter__(self) -> AsyncSession:
        return cast(AsyncSession, SimpleNamespace())

    async def __aexit__(self, *args: object) -> None:
        return None


class _SessionManager:
    def __call__(self) -> AbstractAsyncContextManager[AsyncSession]:
        return _SessionContext()


async def test_access_allow_rebuilds_slack_replay_without_content() -> None:
    request = SimpleNamespace(
        id="access-1",
        status=ExternalChannelAccessRequestStatus.ALLOWED,
        connection_id="connection-1",
        conversation_position_id="position-1",
        resource_id="resource-1",
        source_message_id="message-1",
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
            )
        ),
        get_message=AsyncMock(
            return_value=SimpleNamespace(
                id="message-1",
                resource_id="resource-1",
                provider_message_key="slack:tenant-1:channel-1:2.000000",
                provider_position="00000000000000000002",
                principal_id="principal-1",
            )
        ),
        get_principal=AsyncMock(
            return_value=SimpleNamespace(
                id="principal-1",
                provider_user_id="participant-1",
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
        batch_id="batch-1",
        control_delivery_attempt_id=None,
        connection_id=None,
    )
    ingestion = SimpleNamespace(ingest=AsyncMock(return_value=expected))
    service = ExternalChannelIngestionReplayService(
        session_manager=cast(Any, _SessionManager()),
        repository=cast(Any, repository),
        ingestion_service=cast(Any, ingestion),
    )

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
        source_message_id="message-1",
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
            )
        ),
        get_message=AsyncMock(
            return_value=SimpleNamespace(
                id="message-1",
                resource_id="resource-1",
                provider_message_key="discord:guild-1:message-2",
                provider_position="00000000000000000002",
                principal_id="principal-1",
            )
        ),
        get_principal=AsyncMock(
            return_value=SimpleNamespace(
                id="principal-1",
                provider_user_id="participant-1",
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
                batch_id=None,
                control_delivery_attempt_id=None,
                connection_id=None,
            )
        )
    )
    service = ExternalChannelIngestionReplayService(
        session_manager=cast(Any, _SessionManager()),
        repository=cast(Any, repository),
        ingestion_service=cast(Any, ingestion),
    )

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
