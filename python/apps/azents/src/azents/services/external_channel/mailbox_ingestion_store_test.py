"""Tests for canonical External Channel mailbox ingestion helpers."""

import dataclasses
import datetime
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, create_autospec

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.config import Config
from azents.core.enums import (
    AgentLifecycleStatus,
    AgentSessionStatus,
    ExternalChannelAppMode,
    ExternalChannelConnectionStatus,
    ExternalChannelConversationScopeKind,
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
    ExternalChannelWorkStatus,
)
from azents.core.external_channel_session_presence import (
    build_external_channel_session_url,
)
from azents.repos.agent import AgentRepository
from azents.repos.agent.data import Agent
from azents.repos.external_channel.data import (
    ExternalChannelAgentRoute,
    ExternalChannelBinding,
    ExternalChannelConnection,
    ExternalChannelConversationPosition,
    ExternalChannelResource,
    ExternalChannelSetupClaim,
)
from azents.repos.external_channel.repository import ExternalChannelRepository
from azents.repos.external_channel.work import ExternalChannelWorkRepository
from azents.repos.external_channel.work_state import ChannelWorkState
from azents.services.external_channel.conversation import (
    ExternalChannelConversationScope,
    ExternalChannelHistoryRange,
    ExternalChannelOperationDeadline,
)
from azents.services.external_channel.conversation_provisioning import (
    ExternalChannelConversationProvisioningService,
)
from azents.services.external_channel.ingestion import (
    ExternalChannelCanonicalHistoryMessage,
    ExternalChannelIngestionAcceptance,
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
    _Conversation,
    _response_mode_ignored_reason,
)
from azents.services.external_channel.participation_state import (
    ExternalChannelSetupSourceProjection,
    projection_with_setup_source,
    setup_source_from_projection,
)
from azents.services.mailbox import MailboxService
from azents.services.root_agent_session_creation import (
    RootAgentSessionCreationService,
)
from azents.testing.external_channel import make_provider_effect_plan


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
        expected_file_count=None,
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
        initial_title_eligible=False,
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


def test_response_mode_requires_invocation_for_unbound_discord_thread() -> None:
    """A parent all-messages setting does not join an unbound Discord Thread."""
    request = _slack_request()
    ordinary_discord_thread = dataclasses.replace(
        request,
        locator=dataclasses.replace(
            request.locator,
            provider=ExternalChannelProvider.DISCORD,
            provider_event_type="discord_message_create",
            invocation=False,
        ),
    )
    assert (
        _response_mode_ignored_reason(
            request=ordinary_discord_thread,
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


def _session(
    *,
    commit: AsyncMock | None = None,
    rollback: AsyncMock | None = None,
) -> AsyncSession:
    """Build one runtime-specced AsyncSession fake."""
    session = MagicMock(spec=AsyncSession)
    session.commit = commit or AsyncMock()
    session.rollback = rollback or AsyncMock()
    return session


def _store(
    *,
    repository: ExternalChannelRepository,
    work_repository: ExternalChannelWorkRepository | None = None,
    agent_repository: AgentRepository | None = None,
    root_creation_service: RootAgentSessionCreationService | None = None,
) -> ExternalChannelMailboxIngestionStore:
    return ExternalChannelMailboxIngestionStore(
        session_manager=MagicMock(),
        repository=repository,
        work_repository=work_repository
        or create_autospec(ExternalChannelWorkRepository, instance=True),
        conversation_provisioning=create_autospec(
            ExternalChannelConversationProvisioningService,
            instance=True,
        ),
        agent_repository=agent_repository
        or create_autospec(AgentRepository, instance=True),
        agent_session_repository=MagicMock(),
        root_agent_session_creation_service=root_creation_service
        or create_autospec(RootAgentSessionCreationService, instance=True),
        mailbox_service=create_autospec(MailboxService, instance=True),
        config=Config.model_construct(
            web_url="https://azents.example/base",
        ),
    )


async def test_configured_binding_rejects_a_stopping_session() -> None:
    """Ready transition cannot retain a connected Binding for a stopping Session."""
    repository = create_autospec(ExternalChannelRepository, instance=True)
    resource = ExternalChannelResource.model_construct(
        id="resource-1",
        connection_id="connection-1",
        status=ExternalChannelResourceStatus.ACTIVE,
    )
    route = ExternalChannelAgentRoute.model_construct(
        id="route-1",
        connection_id="connection-1",
        agent_id="agent-1",
    )
    binding = ExternalChannelBinding.model_construct(
        id="binding-1",
        resource_id="resource-1",
        route_id="route-1",
        agent_session_id="session-1",
        response_mode=ExternalChannelResponseMode.ALL_MESSAGES,
        disconnected_at=None,
    )
    repository.lock_resource = AsyncMock(return_value=resource)
    repository.get_routable_route_by_id = AsyncMock(return_value=route)
    repository.lock_connected_binding_by_resource = AsyncMock(return_value=binding)
    store = _store(repository=repository)
    store.agent_session_repository.lock_by_id = AsyncMock(
        return_value=SimpleNamespace(
            status=AgentSessionStatus.ACTIVE,
            stop_requested_at=datetime.datetime.now(datetime.UTC),
        )
    )

    with pytest.raises(
        ValueError,
        match="configured Session is unavailable",
    ):
        await store.create_configured_binding(
            _session(),
            resource_id="resource-1",
            route_id="route-1",
            response_mode=ExternalChannelResponseMode.ALL_MESSAGES,
            tracker_visibility="visible",
        )

    ensure_active_work = store.work_repository.ensure_active_work
    assert isinstance(ensure_active_work, AsyncMock)
    ensure_active_work.assert_not_awaited()


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


async def _accepted_control_plan_case(
    *,
    existing_binding: bool,
    stopping_session: bool = False,
    admission_succeeds: bool = True,
    access_granted: bool = True,
    separate_target: bool = False,
    provider: ExternalChannelProvider = ExternalChannelProvider.SLACK,
    invocation: bool = True,
) -> SimpleNamespace:
    session = _session()

    @asynccontextmanager
    async def session_context() -> AsyncIterator[AsyncSession]:
        yield session

    repository = MagicMock()
    work_repository = MagicMock()
    mailbox_service = MagicMock()
    mailbox_service.enqueue_many = AsyncMock(
        side_effect=lambda _session, inputs: [
            SimpleNamespace(
                created=True,
                mailbox_item=SimpleNamespace(
                    id=f"mailbox-{index}",
                    idempotency_key=input.idempotency_key,
                ),
            )
            for index, input in enumerate(inputs)
        ],
    )
    store = _store(repository=repository, work_repository=work_repository)
    store.session_manager = MagicMock(return_value=session_context())
    store.mailbox_service = mailbox_service
    target_session = SimpleNamespace(
        status=AgentSessionStatus.ACTIVE,
        stop_requested_at=(
            datetime.datetime.now(datetime.UTC) if stopping_session else None
        ),
    )
    store.agent_session_repository = MagicMock()
    store.agent_session_repository.lock_by_id = AsyncMock()
    store.agent_session_repository.get_by_id = AsyncMock(return_value=target_session)
    store.agent_session_repository.admit_input_wakeup = AsyncMock(
        return_value=target_session if admission_succeeds else None
    )

    request = _slack_request()
    request = dataclasses.replace(
        request,
        locator=dataclasses.replace(
            request.locator,
            provider=provider,
            provider_event_type=(
                "discord_message_create"
                if provider is ExternalChannelProvider.DISCORD
                else request.locator.provider_event_type
            ),
            invocation=invocation,
        ),
    )
    connection = ExternalChannelConnection.model_construct(id="connection-1")
    position = ExternalChannelConversationPosition.model_construct(
        id="position-1",
        connection_id=connection.id,
        read_through_position=None,
    )
    route = ExternalChannelAgentRoute.model_construct(
        id="route-1",
        agent_id="agent-1",
        open_access_enabled=False,
    )
    resource = ExternalChannelResource.model_construct(
        id="resource-1",
        connection_id=connection.id,
        resource_type=ExternalChannelResourceType.THREAD,
        provider_resource_key=request.locator.provider_resource_key,
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
        agent_session_id="session-1",
        response_mode=ExternalChannelResponseMode.ALL_MESSAGES,
        disconnected_at=None,
    )
    target_resource = (
        ExternalChannelResource.model_construct(
            id="target-resource-1",
            connection_id=connection.id,
            resource_type=ExternalChannelResourceType.PARENT_CHANNEL,
            provider_resource_key="channel-1",
            labels={
                "provider": "slack",
                "tenant_id": "tenant-1",
                "channel_id": "channel-1",
            },
            status=ExternalChannelResourceStatus.ACTIVE,
        )
        if separate_target
        else resource
    )
    conversation = _Conversation(
        source_resource=resource,
        resource=target_resource,
        route=route,
        setting=None,
        binding=binding if existing_binding else None,
        principal_id="principal-1",
        selector=None,
        setup_claim=None,
        setup_required=False,
    )
    work = SimpleNamespace(work_cycle_id="work-1")
    presence_plan = make_provider_effect_plan("joined-presence")
    progress_plan = make_provider_effect_plan("initial-progress")
    presence_intent = AsyncMock(return_value=presence_plan)

    store._lock_authority = AsyncMock(return_value=connection)
    repository.lock_conversation_position = AsyncMock(return_value=position)
    repository.get_resource_by_provider_key = AsyncMock(return_value=resource)
    store._replay_source_matches = MagicMock(return_value=True)
    store._resolve_conversation = AsyncMock(return_value=conversation)
    repository.get_active_block = AsyncMock(return_value=None)
    repository.get_active_access_grant = AsyncMock(
        return_value=object() if access_granted else None
    )
    repository.create_access_request_idempotent = AsyncMock(
        return_value=SimpleNamespace(id="access-1")
    )
    store._create_access_control_intent = AsyncMock(return_value=None)
    store._create_binding = AsyncMock(
        return_value=SimpleNamespace(binding=binding, session_created=True)
    )
    work_repository.ensure_active_work = AsyncMock(return_value=work)
    store._create_session_presence_intent = presence_intent
    store._create_initial_progress_intent = AsyncMock(return_value=progress_plan)
    repository.advance_conversation_position_if_current = AsyncMock(return_value=True)
    store._initialize_thread_position = AsyncMock()
    store._complete_setup_replay = AsyncMock()

    acceptance: ExternalChannelIngestionAcceptance = await store.accept(
        request=request,
        preparation=ExternalChannelIngestionPreparation(
            position_id=position.id,
            exclusive_start_position=None,
            immediate_outcome=None,
            wake_mailbox_item_id=None,
            wake_session_id=None,
            priority_request=None,
        ),
        history=_history(),
        provider_preparation=None,
    )
    return SimpleNamespace(
        acceptance=acceptance,
        work_repository=work_repository,
        presence_intent=presence_intent,
        presence_plan=presence_plan,
        progress_plan=progress_plan,
        repository=repository,
        agent_session_repository=store.agent_session_repository,
        session=session,
    )


async def test_new_binding_admission_includes_joined_presence() -> None:
    """A new Binding admission returns joined presence with initial progress."""
    case = await _accepted_control_plan_case(existing_binding=False)

    assert case.acceptance.control_plans == (
        case.presence_plan,
        case.progress_plan,
    )
    call = case.work_repository.ensure_active_work.await_args.kwargs
    assert call["agent_id"] == "agent-1"
    assert call["session_id"] == "session-1"
    assert call["binding_id"] == "binding-1"
    assert call["desired_progress"].state == "checking"
    assert call["tracker_visibility"] == "visible"
    assert call["slack_presence_thread_ts"] == "thread-1"
    assert call["slack_presence_initiator_user_id"] == "participant-1"
    case.presence_intent.assert_awaited_once()
    case.agent_session_repository.lock_by_id.assert_not_awaited()
    case.agent_session_repository.admit_input_wakeup.assert_awaited_once()


async def test_existing_binding_admission_excludes_joined_presence() -> None:
    """An existing Binding mention returns only its normal Tracker plan."""
    case = await _accepted_control_plan_case(existing_binding=True)

    assert case.acceptance.control_plans == (case.progress_plan,)
    case.presence_intent.assert_not_awaited()


async def test_existing_discord_binding_uses_tracker_without_settings_message() -> None:
    """Discord follow-up settings access is carried by the visible Tracker."""
    case = await _accepted_control_plan_case(
        existing_binding=True,
        provider=ExternalChannelProvider.DISCORD,
    )

    assert case.acceptance.control_plans == (case.progress_plan,)
    case.presence_intent.assert_not_awaited()


@pytest.mark.parametrize(
    ("provider", "invocation", "tracker_visibility"),
    [
        (ExternalChannelProvider.SLACK, False, "hidden"),
        (ExternalChannelProvider.SLACK, True, "visible"),
        (ExternalChannelProvider.DISCORD, False, "hidden"),
        (ExternalChannelProvider.DISCORD, True, "visible"),
    ],
)
async def test_admission_derives_tracker_visibility_from_provider_invocation(
    provider: ExternalChannelProvider,
    invocation: bool,
    tracker_visibility: str,
) -> None:
    """Ordinary all-messages input starts hidden until explicit invocation."""
    case = await _accepted_control_plan_case(
        existing_binding=True,
        provider=provider,
        invocation=invocation,
    )

    assert (
        case.work_repository.ensure_active_work.await_args.kwargs["tracker_visibility"]
        == tracker_visibility
    )


async def test_existing_binding_admission_rejects_a_stopping_session() -> None:
    """Synchronous replay never enqueues into a Session that is stopping."""
    case = await _accepted_control_plan_case(
        existing_binding=True,
        stopping_session=True,
    )

    assert case.acceptance.status == "terminal_rejection"
    assert (
        case.acceptance.reason
        is ExternalChannelIngestionReason.CONVERSATION_UNAVAILABLE
    )
    case.work_repository.ensure_active_work.assert_not_awaited()
    case.presence_intent.assert_not_awaited()
    case.agent_session_repository.admit_input_wakeup.assert_not_awaited()


async def test_admission_cas_failure_rolls_back_prepared_input() -> None:
    """A concurrent stop prevents canonical mailbox admission from committing."""
    case = await _accepted_control_plan_case(
        existing_binding=True,
        admission_succeeds=False,
    )

    assert case.acceptance.status == "terminal_rejection"
    assert (
        case.acceptance.reason
        is ExternalChannelIngestionReason.CONVERSATION_UNAVAILABLE
    )
    case.session.rollback.assert_awaited_once()
    case.session.commit.assert_not_awaited()
    case.agent_session_repository.lock_by_id.assert_not_awaited()
    case.agent_session_repository.admit_input_wakeup.assert_awaited_once()


async def test_access_request_retains_source_and_effective_target_resources() -> None:
    """Channel fan-in access replay freezes independent source and target IDs."""
    case = await _accepted_control_plan_case(
        existing_binding=False,
        access_granted=False,
        separate_target=True,
    )

    assert case.acceptance.status == "awaiting_access"
    create = case.repository.create_access_request_idempotent.await_args.args[1]
    assert create.source_resource_id == "resource-1"
    assert create.resource_id == "target-resource-1"


async def test_initial_progress_intent_uses_binding_toolkit_state_identity() -> None:
    """Initial progress plans retain the binding-specific Work cycle identity."""
    work_repository = MagicMock()
    plan = make_provider_effect_plan("initial-progress")
    work_repository.prepare_initial_progress = AsyncMock(return_value=plan)
    store = _store(repository=MagicMock(), work_repository=work_repository)
    binding = ExternalChannelBinding.model_construct(
        id="binding-1",
        agent_session_id="session-1",
    )
    work = ChannelWorkState(
        schema_version=4,
        binding_id=binding.id,
        work_cycle_id="work-cycle-1",
        status=ExternalChannelWorkStatus.ACTIVE,
        slack_presence_thread_ts=None,
        slack_presence_initiator_user_id=None,
        title=None,
        tasks=[],
        state_revision=1,
        desired_progress_revision=1,
        desired_progress=None,
        awaiting_input_run_id=None,
        finished_at=None,
        projection_parts=[],
        tracker_visibility="visible",
    )
    session = _session()

    result = await store._create_initial_progress_intent(
        session,
        agent_id="agent-1",
        binding=binding,
        work=work,
    )

    assert result == plan
    work_repository.prepare_initial_progress.assert_awaited_once_with(
        session,
        agent_id="agent-1",
        session_id="session-1",
        binding_id="binding-1",
        work_cycle_id="work-cycle-1",
    )


async def test_session_presence_intent_replaces_open_session_control() -> None:
    """A new binding commits provider-neutral joined presence instead of link copy."""
    repository = MagicMock()
    work_repository = MagicMock()
    plan = make_provider_effect_plan("joined-presence")
    work_repository.prepare_direct_control = AsyncMock(return_value=plan)
    store = _store(repository=repository, work_repository=work_repository)
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

    result = await store._create_session_presence_intent(
        _session(),
        resource=resource,
        binding=binding,
    )

    assert result == plan
    call = work_repository.prepare_direct_control.await_args
    assert call is not None
    call = call.kwargs
    assert call["request_payload"] == {
        "control_kind": "session_presence",
        "control_version": 2,
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
    store._ensure_principal = AsyncMock(return_value="principal-1")
    store._resolve_route = AsyncMock(
        return_value=ExternalChannelAgentRoute.model_construct(
            id="route-1",
            agent_id="agent-1",
        )
    )

    conversation = await store._resolve_conversation(
        _session(),
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
    commit = AsyncMock()
    session = _session(commit=commit)
    repository = MagicMock()
    repository.get_active_block = AsyncMock(return_value=None)
    repository.get_active_access_grant = AsyncMock(return_value=object())
    repository.create_binding_idempotent = AsyncMock()
    work_repository = MagicMock()
    work_repository.ensure_active_work = AsyncMock()
    plan = make_provider_effect_plan("setup-required")
    work_repository.prepare_direct_control = AsyncMock(return_value=plan)
    root_creation_service = MagicMock()
    root_creation_service.create_root_session = AsyncMock()
    mailbox_service = MagicMock()
    mailbox_service.enqueue_many = AsyncMock()
    agent_session_repository = MagicMock()
    agent_session_repository.mark_running_for_input_wakeup = AsyncMock()
    store = _store(
        repository=repository,
        work_repository=work_repository,
        root_creation_service=root_creation_service,
    )
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
        labels={
            "provider": "slack",
            "tenant_id": "tenant-1",
            "channel_id": "channel-1",
            "thread_ts": "1.000000",
        },
    )
    claim = ExternalChannelSetupClaim.model_construct(
        id="claim-1",
        connection_id="connection-1",
        provider_parent_channel_id="channel-1",
        route_id=route.id,
        source_resource_id=source_resource.id,
        source_revision=1,
        claim_generation=1,
        status=ExternalChannelSetupClaimStatus.PENDING_LOCATION,
    )
    store._ensure_setup_claim = AsyncMock(return_value=claim)

    acceptance = await store._accept_setup_required(
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
    assert acceptance.control_plans == (plan,)
    assert acceptance.connection_id == "connection-1"
    call = work_repository.prepare_direct_control.await_args
    assert call is not None
    call = call.kwargs
    assert call["operation_seed"] == "setup:claim-1:1:1"
    assert call["request_payload"] == {
        "control_kind": "setup_required",
        "control_version": 2,
        "setup_claim_id": "claim-1",
        "claim_generation": 1,
        "source_revision": 1,
        "tenant_id": "tenant-1",
        "channel_id": "channel-1",
        "thread_ts": "1.000000",
    }
    commit.assert_awaited_once()
    repository.create_binding_idempotent.assert_not_awaited()
    work_repository.ensure_active_work.assert_not_awaited()
    root_creation_service.create_root_session.assert_not_awaited()
    mailbox_service.enqueue_many.assert_not_awaited()
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
        source_projection=projection_with_setup_source(
            ExternalChannelSetupSourceProjection(
                schema_version=1,
                provider=ExternalChannelProvider.SLACK,
                provider_event_type="message",
                provider_tenant_id="tenant-1",
                provider_channel_id="channel-1",
                provider_parent_channel_id="channel-1",
                scope_kind=ExternalChannelConversationScopeKind.PARENT_CHANNEL,
                provider_thread_key=None,
                delivery_thread_key="00000000000000000003",
                provider_resource_key="resource-key-old",
                trigger_provider_message_key="message-key-old",
                trigger_provider_message_id="3.000000",
                trigger_position="00000000000000000003",
                range_start_position="00000000000000000002",
            )
        ),
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
    store = _store(repository=repository)
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

    result = await store._ensure_setup_claim(
        _session(),
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
    call = repository.replace_setup_claim_source.await_args
    assert call is not None
    call = call.kwargs
    assert call["expected_claim_generation"] == 2
    assert call["expected_source_revision"] == 3
    assert call["conversation_position_id"] == "position-new"
    assert call["source_resource_id"] == "source-new"
    assert call["principal_id"] == "principal-new"
    source = setup_source_from_projection(call["source_projection"])
    assert source.trigger_provider_message_key == "message-key-new"
    assert source.trigger_position == "00000000000000000009"


async def test_duplicate_slack_event_types_reuse_setup_claim_source() -> None:
    """Slack message and app_mention callbacks for one message create one revision."""
    repository = MagicMock()
    request = _parent_slack_request()
    old_claim = ExternalChannelSetupClaim.model_construct(
        id="claim-1",
        connection_id="connection-1",
        provider_parent_channel_id="channel-1",
        route_id="route-1",
        conversation_position_id="position-1",
        source_resource_id="source-1",
        principal_id="principal-1",
        source_projection=projection_with_setup_source(
            ExternalChannelSetupSourceProjection(
                schema_version=1,
                provider=ExternalChannelProvider.SLACK,
                provider_event_type="message",
                provider_tenant_id=request.locator.provider_tenant_id,
                provider_channel_id=request.locator.provider_channel_id,
                provider_parent_channel_id="channel-1",
                scope_kind=ExternalChannelConversationScopeKind.PARENT_CHANNEL,
                provider_thread_key=None,
                delivery_thread_key=request.locator.delivery_thread_key,
                provider_resource_key=request.locator.provider_resource_key,
                trigger_provider_message_key=(
                    request.locator.trigger_provider_message_key
                ),
                trigger_provider_message_id=(
                    request.locator.trigger_provider_message_id
                ),
                trigger_position=request.locator.trigger_position,
                range_start_position=None,
            )
        ),
        source_revision=5,
        claim_generation=5,
        status=ExternalChannelSetupClaimStatus.PENDING_LOCATION,
    )
    repository.lock_nonterminal_setup_claim = AsyncMock(return_value=old_claim)
    repository.replace_setup_claim_source = AsyncMock()
    store = _store(repository=repository)

    result = await store._ensure_setup_claim(
        _session(),
        request=request,
        position=ExternalChannelConversationPosition.model_construct(id="position-1"),
        source_resource=ExternalChannelResource.model_construct(id="source-1"),
        principal_id="principal-1",
        route=ExternalChannelAgentRoute.model_construct(id="route-1"),
        history=_history(),
        now=datetime.datetime(2026, 8, 2, tzinfo=datetime.UTC),
    )

    assert result is old_claim
    repository.replace_setup_claim_source.assert_not_awaited()


async def test_discord_thread_resolves_multi_default_from_parent_channel() -> None:
    """A new Discord thread uses the parent channel's one selected Agent route."""
    repository = MagicMock()
    selected_route = ExternalChannelAgentRoute.model_construct(id="route-1")
    repository.lock_routable_channel_default = AsyncMock(return_value=selected_route)
    store = _store(repository=repository)
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

    route = await store._resolve_route(
        _session(),
        request=request,
        connection=ExternalChannelConnection.model_construct(
            id="connection-1",
            app_mode=ExternalChannelAppMode.MULTI,
        ),
    )

    assert route is selected_route
    call = repository.lock_routable_channel_default.await_args
    assert call is not None
    assert call.kwargs["provider_channel_id"] == "parent-channel-1"


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

    first = await store._create_binding(
        _session(),
        route=route,
        resource=resource,
        response_mode=None,
    )
    repeated = await store._create_binding(
        _session(),
        route=route,
        resource=resource,
        response_mode=None,
    )

    assert first.binding.agent_session_id == "session-1"
    assert first.session_created
    assert repeated.binding.agent_session_id == "session-1"
    assert not repeated.session_created
