"""Tests for content-free selector and access ingestion replay."""

import datetime
from contextlib import AbstractAsyncContextManager
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    ExternalChannelAccessRequestStatus,
    ExternalChannelAppMode,
    ExternalChannelConnectionStatus,
    ExternalChannelConversationScopeKind,
    ExternalChannelIngressAuthorityKind,
    ExternalChannelIngressProfile,
    ExternalChannelInteractionStatus,
    ExternalChannelInteractionType,
    ExternalChannelPrincipalAuthorType,
    ExternalChannelProvider,
    ExternalChannelResourceStatus,
    ExternalChannelResourceType,
    ExternalChannelRouteCatalogStatus,
    ExternalChannelRouteMode,
    ExternalChannelTransport,
)
from azents.core.external_channel_conversation_data import (
    ExternalChannelOperationDeadline,
)
from azents.core.external_channel_ingestion import (
    ExternalChannelIngestionOperation,
    ExternalChannelIngestionOutcome,
    ExternalChannelIngestionOutcomeKind,
    ExternalChannelIngestionReason,
    ExternalChannelIngestionRequest,
    ExternalChannelReplayBoundary,
)
from azents.repos.external_channel.data import (
    ExternalChannelAccessRequest,
    ExternalChannelAgentRoute,
    ExternalChannelConnectionConfiguration,
    ExternalChannelConversationPosition,
    ExternalChannelInteraction,
    ExternalChannelPrincipal,
    ExternalChannelResource,
)
from azents.repos.external_channel.repository import ExternalChannelRepository
from azents.services.external_channel.ingestion import (
    ExternalChannelConversationIngestionService,
)
from azents.services.external_channel.ingestion_replay import (
    ExternalChannelIngestionReplayService,
    ExternalChannelIngestionReplayUnavailable,
)

_NOW = datetime.datetime(2026, 8, 1, tzinfo=datetime.UTC)


def _access_request(**facts: object) -> ExternalChannelAccessRequest:
    return ExternalChannelAccessRequest.model_validate(
        {
            "agent_session_id": None,
            "setup_claim_id": None,
            "decision_policy_snapshot": {},
            "decided_by_user_id": None,
            "decision_summary": None,
            "expires_at": _NOW + datetime.timedelta(days=1),
            "decided_at": None,
            "control_provider_message_key": None,
            "control_projection_status": None,
            "created_at": _NOW,
            "updated_at": _NOW,
            **facts,
        }
    )


def _configuration(**facts: object) -> ExternalChannelConnectionConfiguration:
    return ExternalChannelConnectionConfiguration.model_validate(
        {
            "workspace_id": "workspace-1",
            "provider_app_id": None,
            "provider_bot_user_id": None,
            "http_callback_selector_hash": None,
            "encrypted_credentials": None,
            "capabilities": None,
            "provider_config": None,
            "last_verified_at": None,
            "last_health_at": None,
            "disconnected_at": None,
            "socket_lease_owner": None,
            "socket_lease_until": None,
            "socket_heartbeat_at": None,
            "socket_gap_detected_at": None,
            "socket_gap_reason": None,
            "created_at": _NOW,
            "updated_at": _NOW,
            **facts,
        }
    )


def _position(**facts: object) -> ExternalChannelConversationPosition:
    return ExternalChannelConversationPosition.model_validate(
        {
            "created_at": _NOW,
            "updated_at": _NOW,
            **facts,
        }
    )


def _resource(**facts: object) -> ExternalChannelResource:
    return ExternalChannelResource.model_validate(
        {
            "resource_type": ExternalChannelResourceType.THREAD,
            "discovered_at": _NOW,
            "latest_activity_at": None,
            "unavailable_at": None,
            "deleted_at": None,
            "created_at": _NOW,
            "updated_at": _NOW,
            **facts,
        }
    )


def _principal(**facts: object) -> ExternalChannelPrincipal:
    return ExternalChannelPrincipal.model_validate(
        {
            "display_name": None,
            "avatar_url": None,
            "profile": None,
            "first_observed_at": _NOW,
            "last_observed_at": _NOW,
            "created_at": _NOW,
            "updated_at": _NOW,
            **facts,
        }
    )


def _route(**facts: object) -> ExternalChannelAgentRoute:
    return ExternalChannelAgentRoute.model_validate(
        {
            "agent_id": "agent-1",
            "agent_id_snapshot": "agent-1",
            "route_mode": ExternalChannelRouteMode.DEDICATED,
            "connection_app_mode": ExternalChannelAppMode.SINGLE,
            "catalog_status": ExternalChannelRouteCatalogStatus.AVAILABLE,
            "catalog_removed_at": None,
            "catalog_removed_by_user_id": None,
            "created_at": _NOW,
            "updated_at": _NOW,
            **facts,
        }
    )


def _interaction(**facts: object) -> ExternalChannelInteraction:
    return ExternalChannelInteraction.model_validate(
        {
            "connection_id": "connection-1",
            "transport": ExternalChannelTransport.SOCKET,
            "provider_interaction_key": "interaction-key",
            "interaction_type": ExternalChannelInteractionType.MANAGEMENT_ACTION,
            "callback_id": None,
            "action_id": None,
            "setup_claim_id": None,
            "resource_correlation_key": None,
            "expires_at": _NOW + datetime.timedelta(days=1),
            "error_kind": None,
            "error_summary": None,
            "created_at": _NOW,
            "updated_at": _NOW,
            **facts,
        }
    )


class _Repository(ExternalChannelRepository):
    """Explicitly typed replay reads, with AsyncMock restricted to call observation."""

    def __init__(
        self,
        *,
        get_access_request: AsyncMock | None,
        get_connection_configuration: AsyncMock,
        get_conversation_position: AsyncMock,
        get_resource: AsyncMock,
        get_principal: AsyncMock,
        get_agent_route: AsyncMock,
        lock_interaction: AsyncMock | None,
    ) -> None:
        super().__init__()
        self.access_call = get_access_request
        self.configuration_call = get_connection_configuration
        self.position_call = get_conversation_position
        self.resource_call = get_resource
        self.principal_call = get_principal
        self.route_call = get_agent_route
        self.interaction_call = lock_interaction

    async def get_access_request(
        self, session: AsyncSession, *, access_request_id: str
    ) -> ExternalChannelAccessRequest | None:
        assert self.access_call is not None
        result: object = await self.access_call(
            session, access_request_id=access_request_id
        )
        assert result is None or isinstance(result, ExternalChannelAccessRequest)
        return result

    async def get_connection_configuration(
        self, session: AsyncSession, *, connection_id: str
    ) -> ExternalChannelConnectionConfiguration | None:
        result: object = await self.configuration_call(
            session, connection_id=connection_id
        )
        assert result is None or isinstance(
            result, ExternalChannelConnectionConfiguration
        )
        return result

    async def get_conversation_position(
        self, session: AsyncSession, *, position_id: str
    ) -> ExternalChannelConversationPosition | None:
        result: object = await self.position_call(session, position_id=position_id)
        assert result is None or isinstance(result, ExternalChannelConversationPosition)
        return result

    async def get_resource(
        self, session: AsyncSession, *, resource_id: str
    ) -> ExternalChannelResource | None:
        result: object = await self.resource_call(session, resource_id=resource_id)
        assert result is None or isinstance(result, ExternalChannelResource)
        return result

    async def get_principal(
        self, session: AsyncSession, *, principal_id: str
    ) -> ExternalChannelPrincipal | None:
        result: object = await self.principal_call(session, principal_id=principal_id)
        assert result is None or isinstance(result, ExternalChannelPrincipal)
        return result

    async def get_agent_route(
        self, session: AsyncSession, *, route_id: str
    ) -> ExternalChannelAgentRoute | None:
        result: object = await self.route_call(session, route_id=route_id)
        assert result is None or isinstance(result, ExternalChannelAgentRoute)
        return result

    async def lock_interaction(
        self, session: AsyncSession, *, interaction_id: str
    ) -> ExternalChannelInteraction | None:
        assert self.interaction_call is not None
        result: object = await self.interaction_call(
            session, interaction_id=interaction_id
        )
        assert result is None or isinstance(result, ExternalChannelInteraction)
        return result


class _Ingestion(ExternalChannelConversationIngestionService):
    def __init__(self, *, ingest: AsyncMock) -> None:
        self.ingest_call = ingest
        self.requests: list[ExternalChannelIngestionRequest] = []

    async def ingest(
        self, request: ExternalChannelIngestionRequest
    ) -> ExternalChannelIngestionOutcome:
        self.requests.append(request)
        result: object = await self.ingest_call(request)
        assert isinstance(result, ExternalChannelIngestionOutcome)
        return result


class _SessionContext(AbstractAsyncContextManager[AsyncSession]):
    def __init__(self) -> None:
        self.session = AsyncSession()

    async def __aenter__(self) -> AsyncSession:
        return self.session

    async def __aexit__(self, *args: object) -> None:
        await self.session.close()
        return None


class _SessionManager:
    def __call__(self) -> AbstractAsyncContextManager[AsyncSession]:
        return _SessionContext()


def _service(
    *,
    repository: _Repository,
    ingestion: _Ingestion,
) -> ExternalChannelIngestionReplayService:
    return ExternalChannelIngestionReplayService(
        session_manager=_SessionManager(),
        repository=repository,
        ingestion_service=ingestion,
    )


async def test_access_allow_rebuilds_slack_replay_without_content() -> None:
    request = _access_request(
        id="access-1",
        status=ExternalChannelAccessRequestStatus.ALLOWED,
        connection_id="connection-1",
        conversation_position_id="position-1",
        source_resource_id="source-resource-1",
        resource_id="target-resource-1",
        trigger_provider_message_key="slack:tenant-1:channel-1:2.000000",
        principal_id="principal-1",
        route_id="route-1",
        range_start_position="00000000000000000001",
        trigger_position="00000000000000000002",
    )
    repository = _Repository(
        lock_interaction=None,
        get_access_request=AsyncMock(return_value=request),
        get_connection_configuration=AsyncMock(
            return_value=_configuration(
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
            return_value=_position(
                id="position-1",
                connection_id="connection-1",
                scope_kind=ExternalChannelConversationScopeKind.PARENT_CHANNEL,
                provider_channel_id="channel-1",
                provider_thread_key=None,
                read_through_position="00000000000000000009",
            )
        ),
        get_resource=AsyncMock(
            return_value=_resource(
                id="source-resource-1",
                connection_id="connection-1",
                provider_resource_key="slack:tenant-1:channel-1:2.000000",
                labels={"thread_ts": "2.000000"},
                status=ExternalChannelResourceStatus.ACTIVE,
            )
        ),
        get_principal=AsyncMock(
            return_value=_principal(
                id="principal-1",
                provider=ExternalChannelProvider.SLACK,
                provider_tenant_id="tenant-1",
                provider_user_id="participant-1",
                author_type=ExternalChannelPrincipalAuthorType.HUMAN,
            )
        ),
        get_agent_route=AsyncMock(
            return_value=_route(
                id="route-1",
                connection_id="connection-1",
            )
        ),
    )
    expected = ExternalChannelIngestionOutcome(
        kind=ExternalChannelIngestionOutcomeKind.ACCEPTED,
        reason=ExternalChannelIngestionReason.ACCEPTED,
        mailbox_item_id="batch-1",
        control_plans=(),
        connection_id=None,
    )
    ingestion = _Ingestion(ingest=AsyncMock(return_value=expected))
    service = _service(repository=repository, ingestion=ingestion)

    outcome = await service.replay_access_allow(
        access_request_id="access-1",
        initial_title_eligible=True,
        deadline=ExternalChannelOperationDeadline(
            datetime.datetime.now(datetime.UTC) + datetime.timedelta(seconds=30)
        ),
    )

    assert outcome is expected
    replay = ingestion.requests[-1]
    assert isinstance(replay.replay_boundary, ExternalChannelReplayBoundary)
    assert replay.operation is ExternalChannelIngestionOperation.ACCESS_ALLOW
    assert replay.initial_title_eligible
    assert replay.authority.kind is ExternalChannelIngressAuthorityKind.DURABLE_REPLAY
    assert replay.authority.lease_owner is None
    assert replay.locator.trigger_provider_message_id == "2.000000"
    assert replay.locator.delivery_thread_key == "2.000000"
    assert replay.locator.provider_event_type == "unknown"
    assert replay.locator.provider_user_id == "participant-1"
    assert replay.replay_boundary.principal_id == "principal-1"
    assert replay.replay_boundary.source_resource_id == "source-resource-1"
    assert replay.replay_boundary.target_resource_id == "target-resource-1"
    assert replay.replay_boundary.range_start_position == "00000000000000000001"
    assert repository.resource_call.await_args is not None
    assert repository.resource_call.await_args.kwargs["resource_id"] == (
        "source-resource-1"
    )
    assert "participant-1" not in repr(replay)
    assert "channel-1" not in repr(replay)


async def test_access_allow_rebuilds_discord_replay_from_legacy_thread_label() -> None:
    """Discord replay accepts the canonical thread label retained before cutover."""
    request = _access_request(
        id="access-1",
        status=ExternalChannelAccessRequestStatus.ALLOWED,
        connection_id="connection-1",
        conversation_position_id="position-1",
        source_resource_id="resource-1",
        resource_id="resource-1",
        trigger_provider_message_key="discord:guild-1:message-2",
        principal_id="principal-1",
        route_id="route-1",
        range_start_position=None,
        trigger_position="00000000000000000002",
    )
    repository = _Repository(
        lock_interaction=None,
        get_access_request=AsyncMock(return_value=request),
        get_connection_configuration=AsyncMock(
            return_value=_configuration(
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
            return_value=_position(
                id="position-1",
                connection_id="connection-1",
                scope_kind=ExternalChannelConversationScopeKind.PARENT_CHANNEL,
                provider_channel_id="channel-1",
                provider_thread_key=None,
                read_through_position="00000000000000000009",
            )
        ),
        get_resource=AsyncMock(
            return_value=_resource(
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
            return_value=_principal(
                id="principal-1",
                provider=ExternalChannelProvider.DISCORD,
                provider_tenant_id="guild-1",
                provider_user_id="participant-1",
                author_type=ExternalChannelPrincipalAuthorType.HUMAN,
            )
        ),
        get_agent_route=AsyncMock(
            return_value=_route(
                id="route-1",
                connection_id="connection-1",
            )
        ),
    )
    ingestion = _Ingestion(
        ingest=AsyncMock(
            return_value=ExternalChannelIngestionOutcome(
                kind=ExternalChannelIngestionOutcomeKind.ACCEPTED,
                reason=ExternalChannelIngestionReason.ACCEPTED,
                mailbox_item_id=None,
                control_plans=(),
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

    replay = ingestion.requests[-1]
    assert isinstance(replay.replay_boundary, ExternalChannelReplayBoundary)
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
    request = _access_request(
        id="access-1",
        status=ExternalChannelAccessRequestStatus.ALLOWED,
        connection_id="connection-1",
        conversation_position_id="position-1",
        source_resource_id="resource-1",
        resource_id="resource-1",
        trigger_provider_message_key=f"discord:{guild_id}:{message_id}",
        principal_id="principal-1",
        route_id="route-1",
        range_start_position=None,
        trigger_position="00000000000000000002",
    )
    repository = _Repository(
        lock_interaction=None,
        get_access_request=AsyncMock(return_value=request),
        get_connection_configuration=AsyncMock(
            return_value=_configuration(
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
            return_value=_position(
                id="position-1",
                connection_id="connection-1",
                scope_kind=ExternalChannelConversationScopeKind.PARENT_CHANNEL,
                provider_channel_id=channel_id,
                provider_thread_key=None,
                read_through_position=None,
            )
        ),
        get_resource=AsyncMock(
            return_value=_resource(
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
            return_value=_principal(
                id="principal-1",
                provider=ExternalChannelProvider.DISCORD,
                provider_tenant_id=guild_id,
                provider_user_id="participant-1",
                author_type=ExternalChannelPrincipalAuthorType.HUMAN,
            )
        ),
        get_agent_route=AsyncMock(
            return_value=_route(
                id="route-1",
                connection_id="connection-1",
            )
        ),
    )
    ingestion = _Ingestion(
        ingest=AsyncMock(
            return_value=ExternalChannelIngestionOutcome(
                kind=ExternalChannelIngestionOutcomeKind.ACCEPTED,
                reason=ExternalChannelIngestionReason.ACCEPTED,
                mailbox_item_id=None,
                control_plans=(),
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

    replay = ingestion.requests[-1]
    assert isinstance(replay.replay_boundary, ExternalChannelReplayBoundary)
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
    repository = _Repository(
        lock_interaction=None,
        get_access_request=AsyncMock(
            return_value=_access_request(
                id="access-1",
                status=ExternalChannelAccessRequestStatus.ALLOWED,
                connection_id="connection-1",
                conversation_position_id="position-1",
                source_resource_id="resource-1",
                resource_id="resource-1",
                trigger_provider_message_key="discord:200:500",
                principal_id="principal-1",
                route_id="route-1",
                range_start_position=None,
                trigger_position="00000000000000000500",
            )
        ),
        get_connection_configuration=AsyncMock(
            return_value=_configuration(
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
            return_value=_position(
                id="position-1",
                connection_id="connection-1",
                scope_kind=ExternalChannelConversationScopeKind.PARENT_CHANNEL,
                provider_channel_id="400",
                provider_thread_key=None,
                read_through_position=None,
            )
        ),
        get_resource=AsyncMock(
            return_value=_resource(
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
            return_value=_principal(
                id="principal-1",
                provider=ExternalChannelProvider.DISCORD,
                provider_tenant_id="200",
                provider_user_id="participant-1",
                author_type=ExternalChannelPrincipalAuthorType.HUMAN,
            )
        ),
        get_agent_route=AsyncMock(
            return_value=_route(
                id="route-1",
                connection_id="connection-1",
            )
        ),
    )
    expected = ExternalChannelIngestionOutcome(
        kind=ExternalChannelIngestionOutcomeKind.ACCEPTED,
        reason=ExternalChannelIngestionReason.ACCEPTED,
        mailbox_item_id="mailbox-1",
        control_plans=(),
        connection_id=None,
    )
    ingestion = _Ingestion(ingest=AsyncMock(return_value=expected))
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
        ingestion.ingest_call.assert_awaited_once()
    else:
        with pytest.raises(ExternalChannelIngestionReplayUnavailable):
            await service.replay_access_allow(
                access_request_id="access-1",
                initial_title_eligible=False,
                deadline=ExternalChannelOperationDeadline(
                    datetime.datetime.now(datetime.UTC) + datetime.timedelta(seconds=30)
                ),
            )

        ingestion.ingest_call.assert_not_awaited()


async def test_selector_replay_keeps_actor_separate_from_source_author() -> None:
    repository = _Repository(
        get_access_request=None,
        lock_interaction=AsyncMock(
            return_value=_interaction(
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
            return_value=_configuration(
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
            return_value=_position(
                id="position-1",
                connection_id="connection-1",
                scope_kind=ExternalChannelConversationScopeKind.PARENT_CHANNEL,
                provider_channel_id="channel-1",
                provider_thread_key=None,
                read_through_position=None,
            )
        ),
        get_resource=AsyncMock(
            return_value=_resource(
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
            return_value=_principal(
                id="principal-actor",
                provider=ExternalChannelProvider.SLACK,
                provider_tenant_id="tenant-1",
                provider_user_id="selector-actor",
                author_type=ExternalChannelPrincipalAuthorType.HUMAN,
            )
        ),
        get_agent_route=AsyncMock(
            return_value=_route(
                id="route-1",
                connection_id="connection-1",
            )
        ),
    )
    expected = ExternalChannelIngestionOutcome(
        kind=ExternalChannelIngestionOutcomeKind.ACCEPTED,
        reason=ExternalChannelIngestionReason.ACCEPTED,
        mailbox_item_id="mailbox-1",
        control_plans=(),
        connection_id=None,
    )
    ingestion = _Ingestion(ingest=AsyncMock(return_value=expected))
    service = _service(repository=repository, ingestion=ingestion)

    outcome = await service.replay_selected_interaction(
        selector_interaction_id="interaction-1",
        principal_id="principal-actor",
        deadline=ExternalChannelOperationDeadline(
            datetime.datetime.now(datetime.UTC) + datetime.timedelta(seconds=30)
        ),
    )

    assert outcome is expected
    replay = ingestion.requests[-1]
    assert isinstance(replay.replay_boundary, ExternalChannelReplayBoundary)
    assert replay.operation is ExternalChannelIngestionOperation.SELECTOR_CONTINUATION
    assert replay.locator.provider_user_id is None
    assert replay.replay_boundary.principal_id == "principal-actor"
    assert "selector-actor" not in repr(replay)
