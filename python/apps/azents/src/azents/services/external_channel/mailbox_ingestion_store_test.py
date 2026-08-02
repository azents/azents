"""Tests for canonical External Channel mailbox ingestion helpers."""

import dataclasses
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
    ExternalChannelMessageLifecycle,
    ExternalChannelMessageRevisionKind,
    ExternalChannelPrincipalAuthorType,
    ExternalChannelProvider,
    ExternalChannelResourceStatus,
    ExternalChannelResourceType,
    ExternalChannelResponseMode,
    ExternalChannelRouteCatalogStatus,
    ExternalChannelRouteMode,
    ExternalChannelSetupClaimStatus,
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
    ExternalChannelSetupClaim,
)
from azents.repos.external_channel.repository import ExternalChannelRepository
from azents.services.external_channel.conversation import (
    ExternalChannelConversationScope,
    ExternalChannelHistoryRange,
    ExternalChannelOperationDeadline,
)
from azents.services.external_channel.ingestion import (
    ExternalChannelCanonicalHistoryMessage,
    ExternalChannelIngestionOperation,
    ExternalChannelIngestionReason,
    ExternalChannelIngestionRequest,
    ExternalChannelIngressAuthority,
    ExternalChannelIngressAuthorityKind,
    ExternalChannelTriggerLocator,
)
from azents.services.external_channel.mailbox_ingestion_store import (
    ExternalChannelMailboxIngestionStore,
    _Conversation,  # pyright: ignore[reportPrivateUsage]
    _response_mode_ignored_reason,  # pyright: ignore[reportPrivateUsage]
)
from azents.services.external_channel.participation_state import (
    setup_source_from_projection,
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


def test_response_mode_accepts_every_explicit_invocation() -> None:
    """An explicit provider invocation triggers every connected response mode."""
    request = _slack_request()
    for mode in ExternalChannelResponseMode:
        binding = ExternalChannelBinding.model_construct(response_mode=mode)
        assert (
            _response_mode_ignored_reason(
                request=request,
                binding=binding,
            )
            is None
        )


def test_response_mode_requires_invocation_without_connected_binding() -> None:
    """An ordinary message cannot create or recreate a disconnected binding."""
    request = _slack_request()
    ordinary = dataclasses.replace(
        request,
        locator=dataclasses.replace(request.locator, invocation=False),
    )
    assert (
        _response_mode_ignored_reason(
            request=ordinary,
            binding=None,
        )
        is ExternalChannelIngestionReason.NOT_AN_INVOCATION
    )


def test_response_mode_ignores_ordinary_message_for_mention_only() -> None:
    """Mention-only bindings retain ordinary provider messages as later context."""
    request = _slack_request()
    ordinary = dataclasses.replace(
        request,
        locator=dataclasses.replace(request.locator, invocation=False),
    )
    binding = ExternalChannelBinding.model_construct(
        response_mode=ExternalChannelResponseMode.MENTION_ONLY
    )
    assert (
        _response_mode_ignored_reason(
            request=ordinary,
            binding=binding,
        )
        is ExternalChannelIngestionReason.RESPONSE_MODE_NOT_TRIGGERED
    )


def test_response_mode_accepts_ordinary_message_for_all_messages() -> None:
    """All-messages bindings preserve ordinary eligible continuation."""
    request = _slack_request()
    ordinary = dataclasses.replace(
        request,
        locator=dataclasses.replace(request.locator, invocation=False),
    )
    binding = ExternalChannelBinding.model_construct(
        response_mode=ExternalChannelResponseMode.ALL_MESSAGES
    )
    assert (
        _response_mode_ignored_reason(
            request=ordinary,
            binding=binding,
        )
        is None
    )


def _store(
    *,
    repository: object,
    agent_repository: object | None = None,
    root_creation_service: object | None = None,
    participation_enabled: bool = False,
) -> ExternalChannelMailboxIngestionStore:
    return ExternalChannelMailboxIngestionStore(
        session_manager=MagicMock(),
        repository=cast(ExternalChannelRepository, repository),
        work_repository=MagicMock(),
        agent_repository=agent_repository or MagicMock(),
        agent_session_repository=MagicMock(),
        root_agent_session_creation_service=root_creation_service or MagicMock(),
        mailbox_service=MagicMock(),
        config=Config.model_construct(
            web_url="https://azents.example/base",
            external_channel_participation_enabled=participation_enabled,
        ),
    )


def _parent_slack_request(
    *,
    trigger_key: str = "message-key-1",
    trigger_position: str = "00000000000000000001",
) -> ExternalChannelIngestionRequest:
    request = _slack_request()
    return dataclasses.replace(
        request,
        locator=dataclasses.replace(
            request.locator,
            provider_parent_channel_id="channel-1",
            provider_thread_key=None,
            delivery_thread_key=trigger_position,
            trigger_provider_message_key=trigger_key,
            trigger_provider_message_id=trigger_position,
            trigger_position=trigger_position,
        ),
        scope=ExternalChannelConversationScope(
            connection_id=request.locator.connection_id,
            kind=ExternalChannelConversationScopeKind.PARENT_CHANNEL,
            provider_channel_id=request.locator.provider_channel_id,
            provider_thread_key=None,
        ),
    )


def _history(
    *,
    trigger_key: str = "message-key-1",
    trigger_position: str = "00000000000000000001",
) -> ExternalChannelHistoryRange[ExternalChannelCanonicalHistoryMessage]:
    trigger = ExternalChannelCanonicalHistoryMessage(
        provider_message_key=trigger_key,
        provider_position=trigger_position,
        revision_key=f"{trigger_key}:original",
        revision_kind=ExternalChannelMessageRevisionKind.ORIGINAL,
        lifecycle=ExternalChannelMessageLifecycle.CURRENT,
        author_type=ExternalChannelPrincipalAuthorType.HUMAN,
        provider_user_id="participant-1",
        sender_display_name="Participant",
        normalized_body="provider history body",
        attachment_metadata=None,
        reference_mappings=None,
        normalized_size=21,
        provider_created_at=datetime.datetime(2026, 8, 1, tzinfo=datetime.UTC),
        provider_updated_at=None,
        original_url=None,
    )
    return ExternalChannelHistoryRange(
        messages=(trigger,),
        trigger=trigger,
        context_omitted=False,
        range_start_position=None,
        trigger_position=trigger_position,
        provider_request_count=1,
        scanned_message_count=1,
        elapsed_seconds=0,
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
    repository.lock_active_participation_setting = AsyncMock(return_value=None)
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
        source_resource=ExternalChannelResource.model_construct(id="resource-1"),
        position=ExternalChannelConversationPosition.model_construct(id="position-1"),
        now=datetime.datetime(2026, 8, 1, tzinfo=datetime.UTC),
    )

    assert conversation.binding is None
    root_creation_service.create_root_session.assert_not_awaited()


async def test_setup_required_commits_claim_without_conversation_side_effects() -> None:
    """Authorized setup admission creates no Binding, Session, mailbox, or wake."""
    session = cast(
        AsyncSession,
        SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock()),
    )
    repository = MagicMock()
    repository.get_active_block = AsyncMock(return_value=None)
    repository.get_active_access_grant = AsyncMock(return_value=object())
    repository.create_binding_idempotent = AsyncMock()
    work_repository = MagicMock()
    work_repository.ensure_active_work = AsyncMock()
    root_creation_service = MagicMock()
    root_creation_service.create_root_session = AsyncMock()
    mailbox_service = MagicMock()
    mailbox_service.enqueue = AsyncMock()
    agent_session_repository = MagicMock()
    agent_session_repository.mark_running_for_input_wakeup = AsyncMock()
    store = _store(
        repository=repository,
        root_creation_service=root_creation_service,
        participation_enabled=True,
    )
    store.work_repository = work_repository
    store.mailbox_service = mailbox_service
    store.agent_session_repository = agent_session_repository
    route = ExternalChannelAgentRoute.model_construct(
        id="route-1",
        connection_id="connection-1",
        agent_id="agent-1",
    )
    source_resource = ExternalChannelResource.model_construct(
        id="source-resource-1",
        connection_id="connection-1",
        resource_type=ExternalChannelResourceType.THREAD,
        status=ExternalChannelResourceStatus.ACTIVE,
    )
    claim = ExternalChannelSetupClaim.model_construct(
        id="claim-1",
        connection_id="connection-1",
        provider_parent_channel_id="channel-1",
        route_id=route.id,
        source_resource_id=source_resource.id,
        status=ExternalChannelSetupClaimStatus.PENDING_LOCATION,
    )
    store._ensure_setup_claim = AsyncMock(  # pyright: ignore[reportPrivateUsage]
        return_value=claim
    )

    acceptance = await store._accept_setup_required(  # pyright: ignore[reportPrivateUsage]
        session,
        request=_parent_slack_request(),
        connection=ExternalChannelConnection.model_construct(id="connection-1"),
        position=ExternalChannelConversationPosition.model_construct(id="position-1"),
        history=_history(),
        conversation=_Conversation(
            source_resource=source_resource,
            resource=source_resource,
            route=route,
            setting=None,
            binding=None,
            principal_id="principal-1",
            selector=None,
            setup_claim=None,
            setup_required=True,
        ),
        now=datetime.datetime(2026, 8, 1, tzinfo=datetime.UTC),
    )

    assert acceptance.reason is ExternalChannelIngestionReason.SETUP_REQUIRED
    assert acceptance.mailbox_item_id is None
    assert acceptance.session_id is None
    session.commit.assert_awaited_once()  # type: ignore[attr-defined]
    repository.create_binding_idempotent.assert_not_awaited()
    work_repository.ensure_active_work.assert_not_awaited()
    root_creation_service.create_root_session.assert_not_awaited()
    mailbox_service.enqueue.assert_not_awaited()
    agent_session_repository.mark_running_for_input_wakeup.assert_not_awaited()


async def test_latest_eligible_setup_mention_replaces_continuation_source() -> None:
    """A later eligible mention advances only the pending claim source revision."""
    repository = MagicMock()
    old_claim = ExternalChannelSetupClaim.model_construct(
        id="claim-1",
        connection_id="connection-1",
        provider_parent_channel_id="channel-1",
        route_id="route-1",
        conversation_position_id="position-old",
        source_resource_id="source-old",
        principal_id="principal-old",
        source_projection={"setup_source": {"schema_version": 0}},
        source_revision=3,
        claim_generation=2,
        status=ExternalChannelSetupClaimStatus.PENDING_LOCATION,
    )
    replacement = old_claim.model_copy(
        update={
            "conversation_position_id": "position-new",
            "source_resource_id": "source-new",
            "principal_id": "principal-new",
            "source_revision": 4,
        }
    )
    repository.lock_nonterminal_setup_claim = AsyncMock(return_value=old_claim)
    repository.replace_setup_claim_source = AsyncMock(return_value=replacement)
    store = _store(repository=repository, participation_enabled=True)
    request = _parent_slack_request(
        trigger_key="message-key-new",
        trigger_position="00000000000000000009",
    )
    position = ExternalChannelConversationPosition.model_construct(
        id="position-new",
        read_through_position="00000000000000000008",
    )
    source_resource = ExternalChannelResource.model_construct(id="source-new")
    route = ExternalChannelAgentRoute.model_construct(id="route-1")

    result = await store._ensure_setup_claim(  # pyright: ignore[reportPrivateUsage]
        cast(AsyncSession, MagicMock()),
        request=request,
        position=position,
        source_resource=source_resource,
        principal_id="principal-new",
        route=route,
        history=_history(
            trigger_key="message-key-new",
            trigger_position="00000000000000000009",
        ),
        now=datetime.datetime(2026, 8, 1, tzinfo=datetime.UTC),
    )

    assert result is replacement
    call = repository.replace_setup_claim_source.await_args.kwargs
    assert call["expected_claim_generation"] == 2
    assert call["expected_source_revision"] == 3
    assert call["conversation_position_id"] == "position-new"
    assert call["source_resource_id"] == "source-new"
    assert call["principal_id"] == "principal-new"
    source = setup_source_from_projection(call["source_projection"])
    assert source.trigger_provider_message_key == "message-key-new"
    assert source.trigger_position == "00000000000000000009"


async def test_discord_thread_resolves_multi_default_from_parent_channel() -> None:
    """A new Discord thread uses the parent channel's one selected Agent route."""
    repository = MagicMock()
    selected_route = ExternalChannelAgentRoute.model_construct(id="route-1")
    repository.lock_routable_channel_default = AsyncMock(return_value=selected_route)
    store = _store(repository=repository, participation_enabled=True)
    request = _slack_request()
    request = dataclasses.replace(
        request,
        locator=dataclasses.replace(
            request.locator,
            provider=ExternalChannelProvider.DISCORD,
            provider_event_type="discord_message_create",
            provider_channel_id="thread-channel-1",
            provider_parent_channel_id="parent-channel-1",
            provider_thread_key="thread-channel-1",
            delivery_thread_key="thread-channel-1",
        ),
        scope=ExternalChannelConversationScope(
            connection_id=request.locator.connection_id,
            kind=ExternalChannelConversationScopeKind.THREAD,
            provider_channel_id="thread-channel-1",
            provider_thread_key="thread-channel-1",
        ),
    )

    route = await store._resolve_route(  # pyright: ignore[reportPrivateUsage]
        cast(AsyncSession, MagicMock()),
        request=request,
        connection=ExternalChannelConnection.model_construct(
            id="connection-1",
            app_mode=ExternalChannelAppMode.MULTI,
        ),
    )

    assert route is selected_route
    assert (
        repository.lock_routable_channel_default.await_args.kwargs[
            "provider_channel_id"
        ]
        == "parent-channel-1"
    )


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
            external_channel_default_response_mode=(
                ExternalChannelResponseMode.ALL_MESSAGES
            ),
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
        response_mode=None,
    )
    repeated = await store._create_binding(  # pyright: ignore[reportPrivateUsage]
        cast(AsyncSession, MagicMock()),
        route=route,
        resource=resource,
        response_mode=None,
    )

    assert first.binding.agent_session_id == "session-1"
    assert first.session_created
    assert repeated.binding.agent_session_id == "session-1"
    assert not repeated.session_created
