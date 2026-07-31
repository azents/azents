"""Tests for durable External Channel mailbox activation helpers."""

import datetime
import json
from contextlib import AbstractAsyncContextManager
from typing import cast
from unittest.mock import AsyncMock, MagicMock

from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.config import Config
from azents.core.enums import (
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
    ExternalChannelSessionActivationState,
    ExternalChannelTransport,
)
from azents.rdb.session import SessionManager
from azents.repos.external_channel.data import (
    ExternalChannelAgentRoute,
    ExternalChannelBinding,
    ExternalChannelConnection,
    ExternalChannelConversationPosition,
    ExternalChannelDeliveryAttempt,
    ExternalChannelResource,
    ExternalChannelSessionActivation,
)
from azents.repos.workspace.data import Workspace
from azents.services.external_channel.conversation import (
    ExternalChannelConversationScope,
    ExternalChannelHistoryRange,
    ExternalChannelOperationDeadline,
)
from azents.services.external_channel.ingestion import (
    ExternalChannelCanonicalHistoryMessage,
    ExternalChannelIngestionAdmission,
    ExternalChannelIngestionOperation,
    ExternalChannelIngestionPreparation,
    ExternalChannelIngestionReason,
    ExternalChannelIngestionRequest,
    ExternalChannelIngressAuthority,
    ExternalChannelIngressAuthorityKind,
    ExternalChannelTriggerLocator,
)
from azents.services.external_channel.mailbox_ingestion_store import (
    ExternalChannelMailboxIngestionStore,
    build_external_channel_session_url,
)


def test_session_url_uses_canonical_workspace_route() -> None:
    """Provider navigation targets the real Agent Session App Router page."""
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


class _Session:
    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1


class _SessionScope(AbstractAsyncContextManager[AsyncSession]):
    def __init__(self, session: _Session) -> None:
        self.session = session

    async def __aenter__(self) -> AsyncSession:
        return cast(AsyncSession, self.session)

    async def __aexit__(self, *exc_info: object) -> None:
        return None


class _SessionManager:
    def __init__(self, session: _Session) -> None:
        self.session = session

    def __call__(self) -> _SessionScope:
        return _SessionScope(self.session)


async def test_stale_admission_rejects_an_already_blocked_activation() -> None:
    """A stale retry cannot resume provider delivery after activation blocking."""
    request = _slack_request()
    session = _Session()
    connection = ExternalChannelConnection.model_construct(id="connection-1")
    position = ExternalChannelConversationPosition.model_construct(
        id="position-1",
        connection_id=connection.id,
        read_through_position=None,
    )
    activation = ExternalChannelSessionActivation.model_construct(
        id="activation-1",
        connection_id=connection.id,
        conversation_position_id=position.id,
        trigger_provider_message_key=request.locator.trigger_provider_message_key,
        trigger_position=request.locator.trigger_position,
        state=ExternalChannelSessionActivationState.BLOCKED,
    )
    repository = MagicMock()
    repository.lock_conversation_position = AsyncMock(return_value=position)
    repository.get_open_session_activation_by_position = AsyncMock(
        return_value=activation
    )
    repository.get_resource_by_provider_key = AsyncMock()
    store = ExternalChannelMailboxIngestionStore(
        session_manager=cast(
            SessionManager[AsyncSession],
            _SessionManager(session),
        ),
        repository=repository,
        work_repository=MagicMock(),
        agent_repository=MagicMock(),
        workspace_repository=MagicMock(),
        agent_session_repository=MagicMock(),
        root_agent_session_creation_service=MagicMock(),
        mailbox_service=MagicMock(),
        config=Config.model_construct(web_url="https://azents.example"),
    )
    store._lock_authority = AsyncMock(  # pyright: ignore[reportPrivateUsage]
        return_value=connection
    )

    result = await store.admit(
        request=request,
        preparation=ExternalChannelIngestionPreparation(
            position_id=position.id,
            exclusive_start_position=None,
            activation_id=activation.id,
            immediate_outcome=None,
            wake_mailbox_item_id=None,
            wake_session_id=None,
        ),
        history=cast(
            ExternalChannelHistoryRange[ExternalChannelCanonicalHistoryMessage],
            MagicMock(),
        ),
    )

    assert result.status == "terminal_rejection"
    assert result.reason is ExternalChannelIngestionReason.INITIAL_DELIVERY_UNAVAILABLE
    assert session.commits == 1
    assert session.rollbacks == 0
    repository.get_resource_by_provider_key.assert_not_awaited()


async def test_activation_locks_resource_before_session_mutation() -> None:
    """Provider resource loss fences activation before Session state can change."""
    request = _slack_request()
    session = _Session()
    connection = ExternalChannelConnection.model_construct(id="connection-1")
    position = ExternalChannelConversationPosition.model_construct(
        id="position-1",
        connection_id=connection.id,
        read_through_position=None,
    )
    resource_snapshot = ExternalChannelResource.model_construct(
        id="resource-1",
        connection_id=connection.id,
        provider_resource_key=request.locator.provider_resource_key,
        status=ExternalChannelResourceStatus.ACTIVE,
    )
    unavailable_resource = resource_snapshot.model_copy(
        update={"status": ExternalChannelResourceStatus.UNAVAILABLE}
    )
    repository = MagicMock()
    repository.lock_conversation_position = AsyncMock(return_value=position)
    repository.get_resource_by_provider_key = AsyncMock(return_value=resource_snapshot)
    repository.lock_resource = AsyncMock(return_value=unavailable_resource)
    agent_session_repository = MagicMock()
    agent_session_repository.lock_by_id = AsyncMock()
    store = ExternalChannelMailboxIngestionStore(
        session_manager=cast(
            SessionManager[AsyncSession],
            _SessionManager(session),
        ),
        repository=repository,
        work_repository=MagicMock(),
        agent_repository=MagicMock(),
        workspace_repository=MagicMock(),
        agent_session_repository=agent_session_repository,
        root_agent_session_creation_service=MagicMock(),
        mailbox_service=MagicMock(),
        config=Config.model_construct(web_url="https://azents.example"),
    )
    store._lock_authority = AsyncMock(  # pyright: ignore[reportPrivateUsage]
        return_value=connection
    )

    result = await store.activate(
        request=request,
        preparation=ExternalChannelIngestionPreparation(
            position_id=position.id,
            exclusive_start_position=None,
            activation_id="activation-1",
            immediate_outcome=None,
            wake_mailbox_item_id=None,
            wake_session_id=None,
        ),
        history=cast(
            ExternalChannelHistoryRange[ExternalChannelCanonicalHistoryMessage],
            MagicMock(),
        ),
        stage=ExternalChannelIngestionAdmission(
            status="ready",
            reason=ExternalChannelIngestionReason.ACCEPTED,
            activation_id="activation-1",
            binding_id="binding-1",
            session_id="session-1",
            mailbox_item_id="mailbox-1",
            required_delivery_attempt_ids=("delivery-1",),
            control_delivery_attempt_id=None,
            connection_id=None,
        ),
    )

    assert result.status == "terminal_rejection"
    assert result.reason is ExternalChannelIngestionReason.CONVERSATION_UNAVAILABLE
    repository.lock_resource.assert_awaited_once_with(
        cast(AsyncSession, session),
        resource_id=resource_snapshot.id,
    )
    agent_session_repository.lock_by_id.assert_not_awaited()


async def test_session_link_intent_contains_the_retained_session_route() -> None:
    """The actual provider payload links to the exact retained Session."""
    now = datetime.datetime(2026, 7, 31, tzinfo=datetime.UTC)
    workspace_repository = MagicMock()
    workspace_repository.get_by_id = AsyncMock(
        return_value=Workspace(
            name="Workspace",
            handle="workspace name",
            default_runtime_profile_id=None,
            default_runtime_profile_version=1,
            created_at=now,
            updated_at=now,
        )
    )
    repository = MagicMock()
    repository.create_delivery_attempt_idempotent = AsyncMock(
        return_value=ExternalChannelDeliveryAttempt.model_construct(
            id="delivery-1",
            status=ExternalChannelDeliveryStatus.PENDING,
        )
    )
    store = ExternalChannelMailboxIngestionStore(
        session_manager=MagicMock(),
        repository=repository,
        work_repository=MagicMock(),
        agent_repository=MagicMock(),
        workspace_repository=workspace_repository,
        agent_session_repository=MagicMock(),
        root_agent_session_creation_service=MagicMock(),
        mailbox_service=MagicMock(),
        config=Config.model_construct(web_url="https://azents.example/base"),
    )
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
        labels=None,
        status=ExternalChannelResourceStatus.ACTIVE,
    )
    binding = ExternalChannelBinding.model_construct(
        id="binding-1",
        resource_id=resource.id,
        route_id=route.id,
        agent_session_id="session id",
        disconnected_at=None,
    )

    delivery_id = await store._create_session_link_intent(  # pyright: ignore[reportPrivateUsage]
        MagicMock(),
        request=_slack_request(),
        connection=connection,
        route=route,
        resource=resource,
        binding=binding,
    )

    assert delivery_id == "delivery-1"
    create = repository.create_delivery_attempt_idempotent.await_args.args[1]
    rendered_payload = json.dumps(create.request_payload, sort_keys=True)
    assert (
        "https://azents.example/w/workspace%20name/agents/agent%2Fid/"
        "sessions/session%20id"
    ) in rendered_payload
