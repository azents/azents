"""Tests for canonical External Channel mailbox ingestion helpers."""

import datetime
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, MagicMock

from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.config import Config
from azents.core.enums import (
    AgentLifecycleStatus,
    ExternalChannelAppMode,
    ExternalChannelConnectionStatus,
    ExternalChannelConversationScopeKind,
    ExternalChannelDeliveryStatus,
    ExternalChannelIngressProfile,
    ExternalChannelProvider,
    ExternalChannelResourceStatus,
    ExternalChannelResourceType,
    ExternalChannelRouteCatalogStatus,
    ExternalChannelRouteMode,
    ExternalChannelTransport,
)
from azents.core.external_channel_session_presence import (
    build_external_channel_session_url,
)
from azents.repos.agent.data import Agent
from azents.repos.external_channel.data import (
    ExternalChannelAgentRoute,
    ExternalChannelBinding,
    ExternalChannelConnection,
    ExternalChannelConversationPosition,
    ExternalChannelDeliveryAttempt,
    ExternalChannelResource,
)
from azents.repos.external_channel.repository import ExternalChannelRepository
from azents.services.external_channel.conversation import (
    ExternalChannelConversationScope,
    ExternalChannelOperationDeadline,
)
from azents.services.external_channel.ingestion import (
    ExternalChannelIngestionOperation,
    ExternalChannelIngestionRequest,
    ExternalChannelIngressAuthority,
    ExternalChannelIngressAuthorityKind,
    ExternalChannelTriggerLocator,
)
from azents.services.external_channel.mailbox_ingestion_store import (
    ExternalChannelMailboxIngestionStore,
)


def test_session_url_uses_canonical_workspace_route() -> None:
    """Provider navigation targets the canonical Agent Session route."""
    assert build_external_channel_session_url(
        "https://azents.example/base",
        "workspace name",
        "agent/id",
        "session id",
    ) == (
        "https://azents.example/w/workspace%20name/agents/agent%2Fid/"
        "sessions/session%20id"
    )


def test_session_url_rejects_non_http_web_origin() -> None:
    """Provider navigation is omitted when the configured Web origin is invalid."""
    assert (
        build_external_channel_session_url(
            "azents.example",
            "workspace",
            "agent",
            "session",
        )
        is None
    )


def _slack_request() -> ExternalChannelIngestionRequest:
    locator = ExternalChannelTriggerLocator(
        connection_id="connection-1",
        provider=ExternalChannelProvider.SLACK,
        provider_event_type="app_mention",
        provider_tenant_id="tenant-1",
        provider_channel_id="channel-1",
        provider_parent_channel_id=None,
        provider_thread_key="thread-1",
        delivery_thread_key="thread-1",
        provider_resource_key="resource-key-1",
        trigger_provider_message_key="message-key-1",
        trigger_provider_message_id="1.000000",
        trigger_position="00000000000000000001",
        provider_user_id="participant-1",
        invocation=True,
    )
    return ExternalChannelIngestionRequest(
        locator=locator,
        scope=ExternalChannelConversationScope(
            connection_id=locator.connection_id,
            kind=ExternalChannelConversationScopeKind.THREAD,
            provider_channel_id=locator.provider_channel_id,
            provider_thread_key=locator.provider_thread_key,
        ),
        authority=ExternalChannelIngressAuthority(
            kind=ExternalChannelIngressAuthorityKind.CONFIGURATION,
            ingress_profile=ExternalChannelIngressProfile.SLACK_HTTP,
            configuration_generation=1,
            lease_owner=None,
            lease_generation=None,
        ),
        deadline=ExternalChannelOperationDeadline(
            datetime.datetime.now(datetime.UTC) + datetime.timedelta(seconds=30)
        ),
        operation=ExternalChannelIngestionOperation.CURRENT_TRIGGER,
        selected_route_id=None,
        replay_boundary=None,
    )


def _store(
    *,
    repository: object,
    agent_repository: object | None = None,
    root_creation_service: object | None = None,
) -> ExternalChannelMailboxIngestionStore:
    return ExternalChannelMailboxIngestionStore(
        session_manager=MagicMock(),
        repository=cast(ExternalChannelRepository, repository),
        work_repository=MagicMock(),
        agent_repository=agent_repository or MagicMock(),
        agent_session_repository=MagicMock(),
        root_agent_session_creation_service=root_creation_service or MagicMock(),
        mailbox_service=MagicMock(),
        config=Config.model_construct(web_url="https://azents.example/base"),
    )


async def test_session_presence_intent_replaces_open_session_control() -> None:
    """A new binding commits provider-neutral joined presence instead of link copy."""
    repository = MagicMock()
    repository.create_delivery_attempt_idempotent = AsyncMock(
        return_value=ExternalChannelDeliveryAttempt.model_construct(
            id="delivery-1",
            status=ExternalChannelDeliveryStatus.PENDING,
        )
    )
    store = _store(repository=repository)
    connection = ExternalChannelConnection.model_construct(
        id="connection-1",
        workspace_id="workspace-1",
        provider=ExternalChannelProvider.SLACK,
        transport=ExternalChannelTransport.HTTP,
        status=ExternalChannelConnectionStatus.ACTIVE,
        app_mode=ExternalChannelAppMode.SINGLE,
    )
    route = ExternalChannelAgentRoute.model_construct(
        id="route-1",
        connection_id=connection.id,
        agent_id="agent/id",
        agent_id_snapshot="agent/id",
        route_mode=ExternalChannelRouteMode.DEDICATED,
        connection_app_mode=ExternalChannelAppMode.SINGLE,
        catalog_status=ExternalChannelRouteCatalogStatus.AVAILABLE,
    )
    resource = ExternalChannelResource.model_construct(
        id="resource-1",
        connection_id=connection.id,
        resource_type=ExternalChannelResourceType.THREAD,
        provider_resource_key="resource-key-1",
        labels={
            "provider": "slack",
            "tenant_id": "tenant-1",
            "channel_id": "channel-1",
            "thread_ts": "thread-1",
        },
        status=ExternalChannelResourceStatus.ACTIVE,
    )
    binding = ExternalChannelBinding.model_construct(
        id="binding-1",
        resource_id=resource.id,
        route_id=route.id,
        agent_session_id="session id",
        disconnected_at=None,
    )

    delivery_id = await store._create_session_presence_intent(  # pyright: ignore[reportPrivateUsage]
        cast(AsyncSession, MagicMock()),
        resource=resource,
        binding=binding,
    )

    assert delivery_id == "delivery-1"
    create = repository.create_delivery_attempt_idempotent.await_args.args[1]
    assert create.request_payload == {
        "control_kind": "session_presence",
        "presence_state": "joined",
        "tenant_id": "tenant-1",
        "channel_id": "channel-1",
        "thread_ts": "thread-1",
    }


async def test_conversation_resolution_does_not_create_session_before_acceptance() -> (
    None
):
    """Provider-history preparation does not leave a Session without mailbox input."""
    repository = MagicMock()
    repository.lock_connected_binding_by_resource = AsyncMock(return_value=None)
    root_creation_service = MagicMock()
    root_creation_service.create_root_session = AsyncMock()
    store = _store(
        repository=repository,
        root_creation_service=root_creation_service,
    )
    store._ensure_principal = AsyncMock(  # pyright: ignore[reportPrivateUsage]
        return_value="principal-1"
    )
    store._resolve_route = AsyncMock(  # pyright: ignore[reportPrivateUsage]
        return_value=ExternalChannelAgentRoute.model_construct(
            id="route-1",
            agent_id="agent-1",
        )
    )

    conversation = await store._resolve_conversation(  # pyright: ignore[reportPrivateUsage]
        cast(AsyncSession, MagicMock()),
        request=_slack_request(),
        connection=ExternalChannelConnection.model_construct(id="connection-1"),
        resource=ExternalChannelResource.model_construct(id="resource-1"),
        position=ExternalChannelConversationPosition.model_construct(id="position-1"),
        now=datetime.datetime(2026, 8, 1, tzinfo=datetime.UTC),
    )

    assert conversation.binding is None
    root_creation_service.create_root_session.assert_not_awaited()


async def test_create_binding_reports_only_the_new_root_session() -> None:
    """Binding creation reports whether this transaction created the root Session."""
    repository = MagicMock()
    repository.create_binding_idempotent = AsyncMock(
        return_value=ExternalChannelBinding.model_construct(
            id="binding-1",
            resource_id="resource-1",
            route_id="route-1",
            agent_session_id="session-1",
            disconnected_at=None,
        )
    )
    agent_repository = MagicMock()
    agent_repository.get_by_id = AsyncMock(
        return_value=Agent.model_construct(
            id="agent-1",
            workspace_id="workspace-1",
            lifecycle_status=AgentLifecycleStatus.ACTIVE,
        )
    )
    root_creation_service = MagicMock()
    root_creation_service.create_root_session = AsyncMock(
        side_effect=[
            SimpleNamespace(
                agent_session=SimpleNamespace(id="session-1"),
                created=True,
            ),
            SimpleNamespace(
                agent_session=SimpleNamespace(id="session-1"),
                created=False,
            ),
        ]
    )
    store = _store(
        repository=repository,
        agent_repository=agent_repository,
        root_creation_service=root_creation_service,
    )
    route = ExternalChannelAgentRoute.model_construct(
        id="route-1",
        agent_id="agent-1",
    )
    resource = ExternalChannelResource.model_construct(id="resource-1")

    first = await store._create_binding(  # pyright: ignore[reportPrivateUsage]
        cast(AsyncSession, MagicMock()),
        route=route,
        resource=resource,
    )
    repeated = await store._create_binding(  # pyright: ignore[reportPrivateUsage]
        cast(AsyncSession, MagicMock()),
        route=route,
        resource=resource,
    )

    assert first.binding.agent_session_id == "session-1"
    assert first.session_created
    assert repeated.binding.agent_session_id == "session-1"
    assert not repeated.session_created
