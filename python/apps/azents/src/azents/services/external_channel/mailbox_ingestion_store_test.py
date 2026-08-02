"""Tests for canonical External Channel mailbox ingestion helpers."""

import dataclasses
import datetime
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from types import SimpleNamespace
from typing import AsyncIterator, cast
from unittest.mock import AsyncMock, MagicMock

from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.config import Config
from azents.core.enums import (
    AgentLifecycleStatus,
    ExternalChannelAppMode,
    ExternalChannelConnectionStatus,
    ExternalChannelConversationScopeKind,
    ExternalChannelDeliveryStatus,
    ExternalChannelDiscordThreadObservationStatus,
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
from azents.rdb.session import SessionManager
from azents.repos.agent import AgentRepository
from azents.repos.agent.data import Agent
from azents.repos.agent_session import AgentSessionRepository
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
from azents.repos.external_channel.title import ExternalChannelTitleRepository
from azents.repos.external_channel.work import ExternalChannelWorkRepository
from azents.services.external_channel.conversation import (
    DiscordRootThreadObservation,
    ExternalChannelConversationLockLease,
    ExternalChannelConversationScope,
    ExternalChannelHistoryRange,
    ExternalChannelOperationDeadline,
    ExternalChannelParticipationScope,
)
from azents.services.external_channel.ingestion import (
    ExternalChannelCanonicalHistoryMessage,
    ExternalChannelConversationIngestionService,
    ExternalChannelIngestionAcceptance,
    ExternalChannelIngestionHistoryReader,
    ExternalChannelIngestionOperation,
    ExternalChannelIngestionPreparation,
    ExternalChannelIngestionReason,
    ExternalChannelIngestionRequest,
    ExternalChannelIngressAuthority,
    ExternalChannelIngressAuthorityKind,
    ExternalChannelReplayBoundary,
    ExternalChannelTriggerLocator,
    ExternalChannelWakeDispatchResult,
)
from azents.services.external_channel.mailbox_ingestion_store import (
    ExternalChannelMailboxIngestionStore,
    _Conversation,  # pyright: ignore[reportPrivateUsage]
    _response_mode_ignored_reason,  # pyright: ignore[reportPrivateUsage]
)
from azents.services.external_channel.participation_state import (
    ExternalChannelSetupSourceProjection,
    projection_with_setup_source,
    setup_source_from_projection,
)
from azents.services.external_channel.title_artifact import (
    ExternalChannelTitleArtifactRequest,
    ExternalChannelTitleArtifactService,
)
from azents.services.mailbox import MailboxService
from azents.services.root_agent_session_creation import RootAgentSessionCreationService


class _RecordingSessionContext(AbstractAsyncContextManager[AsyncSession]):
    """Expose the one admission transaction commit in the event trace."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def __aenter__(self) -> AsyncSession:
        return self.session

    async def __aexit__(self, *exc_info: object) -> None:
        return None


class _RecordingSessionManager:
    """Return one transaction double with explicit commit ordering."""

    def __init__(self, events: list[str]) -> None:
        self.session = cast(
            AsyncSession,
            SimpleNamespace(
                commit=AsyncMock(side_effect=lambda: events.append("commit")),
                rollback=AsyncMock(side_effect=lambda: events.append("rollback")),
            ),
        )

    def __call__(self) -> _RecordingSessionContext:
        return _RecordingSessionContext(self.session)


class _RecordingTitleArtifactService:
    """Exercise real artifact behavior while retaining every producer request."""

    def __init__(self, title_repository: ExternalChannelTitleRepository) -> None:
        self.delegate = ExternalChannelTitleArtifactService(
            title_repository=title_repository
        )
        self.create_requests: list[ExternalChannelTitleArtifactRequest] = []
        self.projection_requests: list[ExternalChannelTitleArtifactRequest] = []
        self.events: list[str] | None = None

    async def create(
        self,
        session: AsyncSession,
        *,
        request: ExternalChannelTitleArtifactRequest,
    ) -> object:
        self.create_requests.append(request)
        if self.events is not None:
            self.events.append("artifact:create")
        return await self.delegate.create(session, request=request)

    async def create_projection_for_existing_candidate(
        self,
        session: AsyncSession,
        *,
        request: ExternalChannelTitleArtifactRequest,
    ) -> object:
        self.projection_requests.append(request)
        if self.events is not None:
            self.events.append("artifact:projection")
        return await self.delegate.create_projection_for_existing_candidate(
            session,
            request=request,
        )


class _NoopLease:
    """Satisfy ingestion's coordination fence without testing lock behavior here."""

    async def assert_owned(self) -> None:
        return None


class _NoopLock:
    """Provide the short-lived lock boundary required by ingestion orchestration."""

    def acquire(
        self,
        *,
        scope: ExternalChannelConversationScope | ExternalChannelParticipationScope,
        deadline: ExternalChannelOperationDeadline,
    ) -> AbstractAsyncContextManager[ExternalChannelConversationLockLease]:
        del scope, deadline

        @asynccontextmanager
        async def owned() -> AsyncIterator[ExternalChannelConversationLockLease]:
            yield _NoopLease()

        return owned()


@dataclasses.dataclass(frozen=True)
class _StaticHistoryReader:
    """Serve one canonical history range through the typed adapter boundary."""

    history: ExternalChannelHistoryRange[ExternalChannelCanonicalHistoryMessage]

    async def read_range(
        self,
        *,
        locator: ExternalChannelTriggerLocator,
        exclusive_start_position: str | None,
        deadline: ExternalChannelOperationDeadline,
    ) -> ExternalChannelHistoryRange[ExternalChannelCanonicalHistoryMessage]:
        del locator, exclusive_start_position, deadline
        return self.history


@dataclasses.dataclass
class _AdmissionStoreAdapter:
    """Expose one real admission store through the ingestion store protocol."""

    store: ExternalChannelMailboxIngestionStore
    preparation: ExternalChannelIngestionPreparation

    async def prepare(
        self,
        *,
        request: ExternalChannelIngestionRequest,
    ) -> ExternalChannelIngestionPreparation:
        del request
        return self.preparation

    async def accept(
        self,
        *,
        request: ExternalChannelIngestionRequest,
        preparation: ExternalChannelIngestionPreparation,
        history: ExternalChannelHistoryRange[ExternalChannelCanonicalHistoryMessage],
    ) -> ExternalChannelIngestionAcceptance:
        return await self.store.accept(
            request=request,
            preparation=preparation,
            history=history,
        )


class _RecordingWakeDispatcher:
    """Record the post-admission wake without adding a second transaction."""

    def __init__(self, events: list[str]) -> None:
        self.events = events

    async def dispatch(
        self,
        *,
        mailbox_item_id: str,
        session_id: str,
        now: datetime.datetime,
        deadline: ExternalChannelOperationDeadline,
    ) -> ExternalChannelWakeDispatchResult:
        del mailbox_item_id, session_id, now, deadline
        self.events.append("wake")
        return "dispatched"


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
        access_request_id=None,
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
    session_manager: object | None = None,
    work_repository: object | None = None,
    agent_session_repository: object | None = None,
    mailbox_service: object | None = None,
    title_artifact_service: object | None = None,
) -> ExternalChannelMailboxIngestionStore:
    default_title_artifact_service = MagicMock(spec=ExternalChannelTitleArtifactService)
    default_title_artifact_service.create = AsyncMock()
    default_title_artifact_service.create_projection_for_existing_candidate = (
        AsyncMock()
    )
    return ExternalChannelMailboxIngestionStore(
        session_manager=cast(
            SessionManager[AsyncSession],
            MagicMock() if session_manager is None else session_manager,
        ),
        repository=cast(ExternalChannelRepository, repository),
        work_repository=cast(
            ExternalChannelWorkRepository,
            MagicMock() if work_repository is None else work_repository,
        ),
        agent_repository=cast(
            AgentRepository,
            MagicMock() if agent_repository is None else agent_repository,
        ),
        agent_session_repository=cast(
            AgentSessionRepository,
            (
                MagicMock()
                if agent_session_repository is None
                else agent_session_repository
            ),
        ),
        root_agent_session_creation_service=cast(
            RootAgentSessionCreationService,
            (MagicMock() if root_creation_service is None else root_creation_service),
        ),
        mailbox_service=cast(
            MailboxService,
            MagicMock() if mailbox_service is None else mailbox_service,
        ),
        title_artifact_service=cast(
            ExternalChannelTitleArtifactService,
            (
                default_title_artifact_service
                if title_artifact_service is None
                else title_artifact_service
            ),
        ),
        config=Config.model_construct(
            web_url="https://azents.example/base",
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
    discord_root_thread_observation: DiscordRootThreadObservation | None = None,
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
        discord_root_thread_observation=discord_root_thread_observation,
    )


def _discord_access_allow_request() -> ExternalChannelIngestionRequest:
    """Build one immutable Discord Access-Allow replay request."""
    locator = ExternalChannelTriggerLocator(
        connection_id="connection-discord-1",
        provider=ExternalChannelProvider.DISCORD,
        provider_event_type="discord_message_create",
        provider_tenant_id="guild-1",
        provider_channel_id="parent-1",
        provider_parent_channel_id="parent-1",
        provider_thread_key="root-1",
        delivery_thread_key="root-1",
        provider_resource_key="discord:root-1",
        trigger_provider_message_key="discord:guild-1:root-1",
        trigger_provider_message_id="root-1",
        trigger_position="root-1",
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
            kind=ExternalChannelIngressAuthorityKind.DURABLE_REPLAY,
            ingress_profile=ExternalChannelIngressProfile.DISCORD_GATEWAY_HTTP,
            configuration_generation=1,
            lease_owner=None,
            lease_generation=None,
        ),
        deadline=ExternalChannelOperationDeadline(
            datetime.datetime(2026, 8, 2, 1, tzinfo=datetime.UTC)
        ),
        operation=ExternalChannelIngestionOperation.ACCESS_ALLOW,
        selected_route_id="route-discord-1",
        replay_boundary=ExternalChannelReplayBoundary(
            connection_id=locator.connection_id,
            resource_id="resource-discord-1",
            principal_id="principal-1",
            trigger_provider_message_key=locator.trigger_provider_message_key,
            conversation_position_id="position-discord-1",
            range_start_position=None,
            trigger_position=locator.trigger_position,
        ),
        access_request_id="access-allow-1",
    )


def _discord_observation(
    *,
    observed_at: datetime.datetime,
) -> DiscordRootThreadObservation:
    """Build one qualifying root-thread absence observation."""
    return DiscordRootThreadObservation(
        status=ExternalChannelDiscordThreadObservationStatus.THREAD_ABSENT,
        guild_id="guild-1",
        parent_channel_id="parent-1",
        root_message_id="root-1",
        trigger_provider_message_key="discord:guild-1:root-1",
        observed_at=observed_at,
        root_has_thread=False,
        thread=None,
    )


async def test_first_binding_persists_title_before_commit_then_wakes() -> None:
    """Initial admission writes title authority before enqueue, commit, and wake."""
    events: list[str] = []
    session_manager = _RecordingSessionManager(events)
    request = _slack_request()
    resource = ExternalChannelResource.model_construct(
        id="resource-1",
        connection_id="connection-1",
        resource_type=ExternalChannelResourceType.THREAD,
        provider_resource_key="resource-key-1",
        labels={"provider": "slack", "channel_id": "channel-1"},
        status=ExternalChannelResourceStatus.ACTIVE,
    )
    route = SimpleNamespace(
        id="route-1",
        require_active_agent_id=lambda: "agent-1",
    )
    binding = ExternalChannelBinding.model_construct(
        id="binding-1",
        resource_id=resource.id,
        route_id=route.id,
        agent_session_id="session-1",
        disconnected_at=None,
    )
    position = SimpleNamespace(
        id="position-1",
        connection_id="connection-1",
        read_through_position=None,
    )
    conversation = _Conversation(
        source_resource=resource,
        resource=resource,
        route=cast(ExternalChannelAgentRoute, route),
        setting=None,
        binding=None,
        principal_id="principal-1",
        selector=None,
        setup_claim=None,
        setup_required=False,
    )
    title_repository = MagicMock(spec=ExternalChannelTitleRepository)
    title_repository.create_session_title_candidate = AsyncMock(
        side_effect=lambda *_args: (
            events.append("candidate:persist"),
            SimpleNamespace(
                id="candidate-1",
                admission_provisional_title="Agent at admission",
            ),
        )[1]
    )
    title_artifacts = _RecordingTitleArtifactService(title_repository)
    title_artifacts.events = events
    repository = MagicMock()
    repository.lock_conversation_position = AsyncMock(return_value=position)
    repository.get_resource_by_provider_key = AsyncMock(return_value=resource)
    repository.get_active_block = AsyncMock(return_value=None)
    repository.get_active_access_grant = AsyncMock(return_value=SimpleNamespace())
    repository.ensure_active_work = AsyncMock(return_value=SimpleNamespace())
    repository.advance_conversation_position_if_current = AsyncMock(return_value=True)
    work_repository = MagicMock()
    work_repository.ensure_active_work = AsyncMock(return_value=SimpleNamespace())
    mailbox_service = MagicMock()
    mailbox_service.enqueue = AsyncMock(
        side_effect=lambda *_args: (
            events.append("mailbox:enqueue"),
            SimpleNamespace(
                created=True,
                mailbox_item=SimpleNamespace(id="mailbox-1"),
            ),
        )[1]
    )
    agent_session_repository = MagicMock()
    agent_session_repository.mark_running_for_input_wakeup = AsyncMock(
        side_effect=lambda *_args: events.append("session:mark-running")
    )
    store = _store(
        repository=repository,
        session_manager=session_manager,
        work_repository=work_repository,
        agent_session_repository=agent_session_repository,
        mailbox_service=mailbox_service,
        title_artifact_service=title_artifacts,
    )
    store._lock_authority = AsyncMock(  # pyright: ignore[reportPrivateUsage]
        return_value=SimpleNamespace(id="connection-1")
    )
    store._replay_source_matches = MagicMock(  # pyright: ignore[reportPrivateUsage]
        return_value=True
    )
    store._resolve_conversation = AsyncMock(  # pyright: ignore[reportPrivateUsage]
        return_value=conversation
    )
    store._create_binding = AsyncMock(  # pyright: ignore[reportPrivateUsage]
        return_value=SimpleNamespace(
            binding=binding,
            session_created=True,
            provisional_title_source="Agent at admission",
        )
    )
    store._create_session_presence_intent = AsyncMock(  # pyright: ignore[reportPrivateUsage]
        return_value=None
    )
    store._create_initial_progress_intent = AsyncMock(  # pyright: ignore[reportPrivateUsage]
        return_value=None
    )
    store._initialize_thread_position = AsyncMock(  # pyright: ignore[reportPrivateUsage]
    )
    store._complete_setup_replay = AsyncMock(  # pyright: ignore[reportPrivateUsage]
    )
    preparation = ExternalChannelIngestionPreparation(
        position_id=position.id,
        exclusive_start_position=None,
        immediate_outcome=None,
        wake_mailbox_item_id=None,
        wake_session_id=None,
        priority_request=None,
    )
    history = _history()
    history_reader: ExternalChannelIngestionHistoryReader = _StaticHistoryReader(
        history
    )
    service = ExternalChannelConversationIngestionService(
        conversation_lock=_NoopLock(),
        participation_lock=_NoopLock(),
        history_reader=history_reader,
        store=_AdmissionStoreAdapter(store=store, preparation=preparation),
        wake_dispatcher=_RecordingWakeDispatcher(events),
    )

    outcome = await service.ingest(request)

    assert outcome.kind.value == "accepted"
    assert len(title_artifacts.create_requests) == 1
    assert title_artifacts.projection_requests == []
    artifact_request = title_artifacts.create_requests[0]
    assert artifact_request.connection_id == "connection-1"
    assert artifact_request.agent_session_id == "session-1"
    assert artifact_request.binding_id == "binding-1"
    assert artifact_request.resource is resource
    assert artifact_request.trigger_provider_message_key == "message-key-1"
    assert artifact_request.provider is ExternalChannelProvider.SLACK
    assert artifact_request.provisional_title_source == "Agent at admission"
    assert artifact_request.access_request_id is None
    assert events == [
        "artifact:create",
        "candidate:persist",
        "mailbox:enqueue",
        "session:mark-running",
        "commit",
        "wake",
    ]

    store._resolve_conversation.return_value = dataclasses.replace(  # pyright: ignore[reportPrivateUsage]
        conversation,
        binding=binding,
    )
    store._create_binding_settings_on_demand_intent = AsyncMock(  # pyright: ignore[reportPrivateUsage]
        return_value=None
    )
    mailbox_service.enqueue = AsyncMock(
        return_value=SimpleNamespace(
            created=False,
            mailbox_item=SimpleNamespace(id="mailbox-1"),
        )
    )
    await store.accept(
        request=request,
        preparation=preparation,
        history=history,
    )

    assert len(title_artifacts.create_requests) == 1
    assert title_artifacts.projection_requests == []


async def test_access_allow_replay_uses_persisted_candidate_title_once() -> None:
    """Replay ignores renamed Agent state and persists at most one projection."""
    request = _discord_access_allow_request()
    resource = ExternalChannelResource.model_construct(
        id="resource-discord-1",
        connection_id="connection-discord-1",
        resource_type=ExternalChannelResourceType.THREAD,
        provider_resource_key="discord:root-1",
        labels={
            "provider": "discord",
            "guild_id": "guild-1",
            "parent_channel_id": "parent-1",
            "root_message_id": "root-1",
        },
        status=ExternalChannelResourceStatus.ACTIVE,
    )
    binding = ExternalChannelBinding.model_construct(
        id="binding-discord-1",
        resource_id=resource.id,
        route_id="route-discord-1",
        agent_session_id="session-discord-1",
        disconnected_at=None,
    )
    position = SimpleNamespace(
        id="position-discord-1",
        connection_id="connection-discord-1",
        read_through_position=None,
    )
    conversation = _Conversation(
        source_resource=resource,
        resource=resource,
        route=cast(
            ExternalChannelAgentRoute,
            SimpleNamespace(
                id="route-discord-1",
                require_active_agent_id=lambda: "agent-1",
            ),
        ),
        setting=None,
        binding=binding,
        principal_id="principal-1",
        selector=None,
        setup_claim=None,
        setup_required=False,
    )
    candidate = SimpleNamespace(
        id="candidate-1",
        admission_access_request_id="access-allow-1",
        admission_provisional_title="Agent before rename",
    )
    projection = SimpleNamespace(
        binding_id=binding.id,
        agent_session_id=binding.agent_session_id,
        session_title_candidate_id=candidate.id,
        requested_provisional_title="Agent before rename",
        admission_connection_id="connection-discord-1",
        admission_guild_id="guild-1",
        admission_parent_channel_id="parent-1",
        admission_root_message_id="root-1",
        admission_trigger_provider_message_key="discord:guild-1:root-1",
        admission_observation_status=(
            ExternalChannelDiscordThreadObservationStatus.THREAD_ABSENT
        ),
        admission_root_has_thread=False,
        admission_observed_thread_channel_id=None,
    )
    title_repository = MagicMock(spec=ExternalChannelTitleRepository)
    title_repository.get_candidate_by_identity = AsyncMock(return_value=candidate)
    title_repository.get_projection_by_resource_id = AsyncMock(
        side_effect=[None, projection]
    )
    title_repository.create_discord_thread_title_projection = AsyncMock(
        return_value=projection
    )
    title_artifacts = _RecordingTitleArtifactService(title_repository)
    repository = MagicMock()
    repository.lock_conversation_position = AsyncMock(return_value=position)
    repository.get_resource_by_provider_key = AsyncMock(return_value=resource)
    repository.get_active_block = AsyncMock(return_value=None)
    repository.get_active_access_grant = AsyncMock(return_value=SimpleNamespace())
    repository.ensure_active_work = AsyncMock(return_value=SimpleNamespace())
    repository.advance_conversation_position_if_current = AsyncMock(return_value=True)
    work_repository = MagicMock()
    work_repository.ensure_active_work = AsyncMock(return_value=SimpleNamespace())
    mailbox_service = MagicMock()
    mailbox_service.enqueue = AsyncMock(
        side_effect=[
            SimpleNamespace(
                created=True,
                mailbox_item=SimpleNamespace(id="mailbox-discord-1"),
            ),
            SimpleNamespace(
                created=False,
                mailbox_item=SimpleNamespace(id="mailbox-discord-1"),
            ),
        ]
    )
    agent_session_repository = MagicMock()
    agent_session_repository.mark_running_for_input_wakeup = AsyncMock()
    store = _store(
        repository=repository,
        session_manager=_RecordingSessionManager([]),
        work_repository=work_repository,
        agent_session_repository=agent_session_repository,
        mailbox_service=mailbox_service,
        title_artifact_service=title_artifacts,
    )
    store._lock_authority = AsyncMock(  # pyright: ignore[reportPrivateUsage]
        return_value=SimpleNamespace(id="connection-discord-1")
    )
    store._replay_source_matches = MagicMock(  # pyright: ignore[reportPrivateUsage]
        return_value=True
    )
    store._resolve_conversation = AsyncMock(  # pyright: ignore[reportPrivateUsage]
        return_value=conversation
    )
    store._access_allow_matches = AsyncMock(  # pyright: ignore[reportPrivateUsage]
        return_value=True
    )
    store._create_session_presence_intent = AsyncMock(  # pyright: ignore[reportPrivateUsage]
        return_value=None
    )
    store._create_binding_settings_on_demand_intent = AsyncMock(  # pyright: ignore[reportPrivateUsage]
        return_value=None
    )
    store._create_initial_progress_intent = AsyncMock(  # pyright: ignore[reportPrivateUsage]
        return_value=None
    )
    store._initialize_thread_position = AsyncMock(  # pyright: ignore[reportPrivateUsage]
    )
    store._complete_setup_replay = AsyncMock(  # pyright: ignore[reportPrivateUsage]
    )
    preparation = ExternalChannelIngestionPreparation(
        position_id=position.id,
        exclusive_start_position=None,
        immediate_outcome=None,
        wake_mailbox_item_id=None,
        wake_session_id=None,
        priority_request=None,
    )
    first_history = _history(
        trigger_key="discord:guild-1:root-1",
        trigger_position="root-1",
        discord_root_thread_observation=_discord_observation(
            observed_at=datetime.datetime(2026, 8, 2, 1, tzinfo=datetime.UTC)
        ),
    )
    second_history = _history(
        trigger_key="discord:guild-1:root-1",
        trigger_position="root-1",
        discord_root_thread_observation=_discord_observation(
            observed_at=datetime.datetime(2026, 8, 2, 2, tzinfo=datetime.UTC)
        ),
    )

    first = await store.accept(
        request=request,
        preparation=preparation,
        history=first_history,
    )
    second = await store.accept(
        request=request,
        preparation=preparation,
        history=second_history,
    )

    assert first.status == "accepted"
    assert second.status == "duplicate"
    assert title_artifacts.create_requests == []
    assert len(title_artifacts.projection_requests) == 2
    assert all(
        artifact_request.access_request_id == "access-allow-1"
        and artifact_request.provisional_title_source is None
        for artifact_request in title_artifacts.projection_requests
    )
    projection_create = (
        title_repository.create_discord_thread_title_projection.await_args.args[1]
    )
    assert projection_create.requested_provisional_title == "Agent before rename"
    assert title_repository.create_discord_thread_title_projection.await_count == 1


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
        "control_version": 2,
        "presence_state": "joined",
        "tenant_id": "tenant-1",
        "channel_id": "channel-1",
        "thread_ts": "thread-1",
    }


async def test_existing_binding_settings_intent_is_on_demand_and_versioned() -> None:
    """The next eligible mention creates one non-rollout settings entry point."""
    repository = MagicMock()
    repository.create_delivery_attempt_idempotent = AsyncMock(
        return_value=ExternalChannelDeliveryAttempt.model_construct(
            id="settings-delivery-1",
            status=ExternalChannelDeliveryStatus.PENDING,
        )
    )
    store = _store(repository=repository)
    resource = ExternalChannelResource.model_construct(
        id="resource-1",
        labels={
            "provider": "slack",
            "tenant_id": "tenant-1",
            "channel_id": "channel-1",
            "thread_ts": "thread-1",
        },
    )
    binding = ExternalChannelBinding.model_construct(
        id="binding-1",
        resource_id=resource.id,
    )

    delivery_id = await store._create_binding_settings_on_demand_intent(  # pyright: ignore[reportPrivateUsage]
        cast(AsyncSession, MagicMock()),
        resource=resource,
        binding=binding,
    )

    assert delivery_id == "settings-delivery-1"
    create = repository.create_delivery_attempt_idempotent.await_args.args[1]
    assert create.origin_type.value == "binding_settings_available"
    assert create.origin_id == "binding-1"
    assert create.binding_id == "binding-1"
    assert create.part_ordinal == 3
    assert create.request_payload == {
        "control_kind": "binding_settings_on_demand",
        "control_version": 3,
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
    repository.create_delivery_attempt_idempotent = AsyncMock(
        return_value=ExternalChannelDeliveryAttempt.model_construct(
            id="setup-delivery-1",
            status=ExternalChannelDeliveryStatus.PENDING,
        )
    )
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
    assert acceptance.control_delivery_attempt_id == "setup-delivery-1"
    assert acceptance.connection_id == "connection-1"
    create = repository.create_delivery_attempt_idempotent.await_args.args[1]
    assert create.origin_type.value == "setup_claim"
    assert create.origin_id == claim.id
    assert create.part_ordinal == claim.source_revision
    assert create.request_payload == {
        "control_kind": "setup_required",
        "control_version": 2,
        "setup_claim_id": "claim-1",
        "claim_generation": 1,
        "source_revision": 1,
        "tenant_id": "tenant-1",
        "channel_id": "channel-1",
        "thread_ts": "1.000000",
    }
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

    result = await store._ensure_setup_claim(  # pyright: ignore[reportPrivateUsage]
        cast(AsyncSession, MagicMock()),
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
            name="Agent One",
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
