"""DB-only effective-target admission tests."""

import datetime
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, create_autospec, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.agent_session_data import AgentSession
from azents.core.enums import (
    AgentSessionKind,
    AgentSessionProductMode,
    AgentSessionStartReason,
    AgentSessionStatus,
    ExternalChannelAccessGrantScope,
    ExternalChannelAppMode,
    ExternalChannelConversationLocation,
    ExternalChannelConversationScopeKind,
    ExternalChannelIngressAuthorityKind,
    ExternalChannelIngressItemState,
    ExternalChannelIngressProfile,
    ExternalChannelPrincipalAuthorType,
    ExternalChannelProvider,
    ExternalChannelResourceStatus,
    ExternalChannelResourceType,
    ExternalChannelResponseMode,
)
from azents.core.external_channel_conversation_data import (
    ExternalChannelConversationScope,
    ExternalChannelOperationDeadline,
)
from azents.core.external_channel_ingestion import (
    ExternalChannelIngestionOperation,
    ExternalChannelIngestionOutcomeKind,
    ExternalChannelIngestionReason,
    ExternalChannelIngestionRequest,
    ExternalChannelIngressAuthority,
    ExternalChannelTriggerLocator,
)
from azents.job_runtime.types import JobRuntime
from azents.rdb.session import SessionManager
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.external_channel.data import (
    ExternalChannelAccessGrant,
    ExternalChannelAgentRoute,
    ExternalChannelBinding,
    ExternalChannelBlock,
    ExternalChannelConnection,
    ExternalChannelConversationPosition,
    ExternalChannelConversationPositionCreate,
    ExternalChannelParticipationSetting,
    ExternalChannelPrincipal,
    ExternalChannelPrincipalCreate,
    ExternalChannelResource,
    ExternalChannelResourceCreate,
)
from azents.repos.external_channel.ingress_queue import (
    ExternalChannelIngressQueueRepository,
)
from azents.repos.external_channel.ingress_queue_data import (
    ExternalChannelIngressAdmission,
    ExternalChannelIngressItem,
    ExternalChannelIngressItemCreate,
    ExternalChannelIngressOwner,
    ExternalChannelIngressOwnerCreate,
)
from azents.repos.external_channel.repository import ExternalChannelRepository
from azents.services.external_channel.ingress_admission import (
    ExternalChannelIngressAdmissionService,
    _EffectiveTarget,
    _response_mode_triggered,
)


class _Session(AsyncSession):
    def __init__(self, commit: AsyncMock) -> None:
        super().__init__()
        self.commit_call = commit

    async def commit(self) -> None:
        await self.commit_call()


class _Repository(ExternalChannelRepository):
    def __init__(self) -> None:
        super().__init__()
        self.principal_call = AsyncMock(
            side_effect=AssertionError("Unexpected principal create")
        )
        self.block_call = AsyncMock(side_effect=AssertionError("Unexpected block read"))
        self.grant_call = AsyncMock(side_effect=AssertionError("Unexpected grant read"))
        self.position_call = AsyncMock(
            side_effect=AssertionError("Unexpected position create")
        )
        self.binding_call = AsyncMock(
            side_effect=AssertionError("Unexpected binding lock")
        )
        self.route_call = AsyncMock(side_effect=AssertionError("Unexpected route lock"))
        self.setting_call = AsyncMock(
            side_effect=AssertionError("Unexpected setting lock")
        )
        self.resource_lock_call = AsyncMock(
            side_effect=AssertionError("Unexpected resource lock")
        )
        self.resource_create_call = AsyncMock(
            side_effect=AssertionError("Unexpected resource create")
        )

    async def create_principal_idempotent(
        self,
        session: AsyncSession,
        create: ExternalChannelPrincipalCreate,
    ) -> ExternalChannelPrincipal:
        result: object = await self.principal_call(session, create)
        assert isinstance(result, ExternalChannelPrincipal)
        return result

    async def get_active_block(
        self,
        session: AsyncSession,
        *,
        agent_id: str,
        principal_id: str,
    ) -> ExternalChannelBlock | None:
        result: object = await self.block_call(
            session, agent_id=agent_id, principal_id=principal_id
        )
        assert result is None or isinstance(result, ExternalChannelBlock)
        return result

    async def get_active_access_grant(
        self,
        session: AsyncSession,
        *,
        agent_id: str,
        principal_id: str,
        agent_session_id: str | None,
    ) -> ExternalChannelAccessGrant | None:
        result: object = await self.grant_call(
            session,
            agent_id=agent_id,
            principal_id=principal_id,
            agent_session_id=agent_session_id,
        )
        assert result is None or isinstance(result, ExternalChannelAccessGrant)
        return result

    async def create_conversation_position_idempotent(
        self,
        session: AsyncSession,
        create: ExternalChannelConversationPositionCreate,
    ) -> ExternalChannelConversationPosition:
        result: object = await self.position_call(session, create)
        assert isinstance(result, ExternalChannelConversationPosition)
        return result

    async def lock_connected_binding_by_resource(
        self,
        session: AsyncSession,
        *,
        resource_id: str,
    ) -> ExternalChannelBinding | None:
        result: object = await self.binding_call(session, resource_id=resource_id)
        assert result is None or isinstance(result, ExternalChannelBinding)
        return result

    async def lock_routable_single_route(
        self,
        session: AsyncSession,
        *,
        connection_id: str,
    ) -> ExternalChannelAgentRoute | None:
        result: object = await self.route_call(session, connection_id=connection_id)
        assert result is None or isinstance(result, ExternalChannelAgentRoute)
        return result

    async def lock_active_participation_setting(
        self,
        session: AsyncSession,
        *,
        connection_id: str,
        provider_parent_channel_id: str,
    ) -> ExternalChannelParticipationSetting | None:
        result: object = await self.setting_call(
            session,
            connection_id=connection_id,
            provider_parent_channel_id=provider_parent_channel_id,
        )
        assert result is None or isinstance(result, ExternalChannelParticipationSetting)
        return result

    async def lock_resource_by_provider_key(
        self,
        session: AsyncSession,
        *,
        connection_id: str,
        resource_type: ExternalChannelResourceType,
        provider_resource_key: str,
    ) -> ExternalChannelResource | None:
        result: object = await self.resource_lock_call(
            session,
            connection_id=connection_id,
            resource_type=resource_type,
            provider_resource_key=provider_resource_key,
        )
        assert result is None or isinstance(result, ExternalChannelResource)
        return result

    async def create_resource_idempotent(
        self,
        session: AsyncSession,
        create: ExternalChannelResourceCreate,
    ) -> ExternalChannelResource:
        result: object = await self.resource_create_call(session, create)
        assert isinstance(result, ExternalChannelResource)
        return result


class _QueueRepository(ExternalChannelIngressQueueRepository):
    def __init__(self) -> None:
        self.admit_call = AsyncMock()

    async def admit(
        self,
        session: AsyncSession,
        *,
        owner_create: ExternalChannelIngressOwnerCreate,
        item_create: ExternalChannelIngressItemCreate,
    ) -> ExternalChannelIngressAdmission:
        await self.admit_call(
            session, owner_create=owner_create, item_create=item_create
        )
        now = datetime.datetime.now(datetime.UTC)
        owner = ExternalChannelIngressOwner.model_validate(
            {
                **owner_create.model_dump(),
                "id": "owner-1",
                "preparation_attempt_count": 0,
                "preparation_next_attempt_at": None,
                "lease_owner": None,
                "lease_generation": 0,
                "lease_acquired_at": None,
                "lease_expires_at": None,
                "first_batch_pending": True,
                "current_batch_id": None,
                "current_batch_started_at": None,
                "created_at": now,
                "updated_at": now,
            }
        )
        item = ExternalChannelIngressItem.model_validate(
            {
                **item_create.model_dump(),
                "id": "item-1",
                "owner_id": owner.id,
                "queue_key": "queue-key",
                "state": ExternalChannelIngressItemState.PENDING,
                "attempt_count": 0,
                "next_attempt_at": None,
                "processing_owner": None,
                "processing_generation": None,
                "batch_id": None,
                "created_at": now,
                "updated_at": now,
            }
        )
        return ExternalChannelIngressAdmission(
            owner=owner,
            item=item,
            created=True,
            replaced_stale_owner=False,
        )


class _SessionRepository(AgentSessionRepository):
    def __init__(
        self, get_by_id: AsyncMock | None, lock_by_id: AsyncMock | None
    ) -> None:
        self.get_call = get_by_id
        self.lock_call = lock_by_id

    async def get_by_id(
        self,
        session: AsyncSession,
        agent_session_id: str,
    ) -> AgentSession | None:
        assert self.get_call is not None
        result: object = await self.get_call(session, agent_session_id)
        assert result is None or isinstance(result, AgentSession)
        return result

    async def lock_by_id(
        self,
        session: AsyncSession,
        agent_session_id: str,
    ) -> AgentSession | None:
        assert self.lock_call is not None
        result: object = await self.lock_call(session, agent_session_id)
        assert result is None or isinstance(result, AgentSession)
        return result


def _session_manager(
    session: AsyncSession | None = None,
) -> SessionManager[AsyncSession]:
    @asynccontextmanager
    async def manager() -> AsyncIterator[AsyncSession]:
        async with session if session is not None else AsyncSession() as db_session:
            yield db_session

    return manager


def _service(
    repository: _Repository,
    *,
    session_manager: SessionManager[AsyncSession] | None = None,
    queue_repository: _QueueRepository | None = None,
) -> ExternalChannelIngressAdmissionService:
    return ExternalChannelIngressAdmissionService(
        session_manager=session_manager or _session_manager(),
        repository=repository,
        queue_repository=queue_repository or _QueueRepository(),
        agent_session_repository=_SessionRepository(None, None),
        job_runtime=create_autospec(JobRuntime, instance=True, spec_set=True),
    )


def _connection() -> ExternalChannelConnection:
    return ExternalChannelConnection.model_construct(
        id="connection-1",
        provider=ExternalChannelProvider.DISCORD,
        app_mode=ExternalChannelAppMode.SINGLE,
    )


def _route() -> ExternalChannelAgentRoute:
    return ExternalChannelAgentRoute.model_construct(
        id="route-1",
        connection_id="connection-1",
        agent_id="agent-1",
    )


def _resource(
    resource_id: str,
    resource_type: ExternalChannelResourceType,
) -> ExternalChannelResource:
    return ExternalChannelResource.model_construct(
        id=resource_id,
        connection_id="connection-1",
        resource_type=resource_type,
        provider_resource_key=resource_id,
        labels=None,
        status=ExternalChannelResourceStatus.ACTIVE,
    )


def _request(
    *,
    invocation: bool = True,
    provider: ExternalChannelProvider = ExternalChannelProvider.DISCORD,
) -> ExternalChannelIngestionRequest:
    discord = provider is ExternalChannelProvider.DISCORD
    return ExternalChannelIngestionRequest(
        locator=ExternalChannelTriggerLocator(
            connection_id="connection-1",
            provider=provider,
            provider_event_type="discord_message_create" if discord else "message",
            provider_tenant_id="guild-1",
            provider_channel_id="thread-1",
            provider_parent_channel_id="parent-1",
            provider_thread_key="thread-1",
            delivery_thread_key="thread-1",
            provider_resource_key="discord:guild-1:thread-1",
            trigger_provider_message_key="discord:message-1",
            trigger_provider_message_id="message-1",
            trigger_position="0001",
            provider_user_id="user-1",
            invocation=invocation,
            expected_file_count=None,
        ),
        scope=ExternalChannelConversationScope(
            connection_id="connection-1",
            kind=ExternalChannelConversationScopeKind.THREAD,
            provider_channel_id="thread-1",
            provider_thread_key="thread-1",
        ),
        authority=ExternalChannelIngressAuthority(
            ingress_profile=ExternalChannelIngressProfile.DISCORD_GATEWAY_HTTP
            if discord
            else ExternalChannelIngressProfile.SLACK_SOCKET,
            configuration_generation=1,
            kind=ExternalChannelIngressAuthorityKind.LEASE,
            lease_owner="lease-owner-1",
            lease_generation=1 if discord else None,
        ),
        deadline=ExternalChannelOperationDeadline(
            datetime.datetime.now(datetime.UTC) + datetime.timedelta(seconds=30)
        ),
        operation=ExternalChannelIngestionOperation.CURRENT_TRIGGER,
        selected_route_id=None,
        replay_boundary=None,
        initial_title_eligible=False,
    )


def _principal() -> ExternalChannelPrincipal:
    now = datetime.datetime.now(datetime.UTC)
    return ExternalChannelPrincipal(
        id="principal-1",
        provider=ExternalChannelProvider.DISCORD,
        provider_tenant_id="guild-1",
        provider_user_id="user-1",
        author_type=ExternalChannelPrincipalAuthorType.HUMAN,
        display_name=None,
        avatar_url=None,
        profile=None,
        first_observed_at=now,
        last_observed_at=now,
        created_at=now,
        updated_at=now,
    )


def _grant() -> ExternalChannelAccessGrant:
    now = datetime.datetime.now(datetime.UTC)
    return ExternalChannelAccessGrant(
        id="grant-1",
        agent_id="agent-1",
        principal_id="principal-1",
        scope=ExternalChannelAccessGrantScope.AGENT,
        agent_session_id=None,
        granted_by_user_id="user-1",
        source_access_request_id=None,
        revoked_by_user_id=None,
        revoked_at=None,
        created_at=now,
        updated_at=now,
    )


def _position() -> ExternalChannelConversationPosition:
    now = datetime.datetime.now(datetime.UTC)
    return ExternalChannelConversationPosition(
        id="position-1",
        connection_id="connection-1",
        scope_kind=ExternalChannelConversationScopeKind.THREAD,
        provider_channel_id="thread-1",
        provider_thread_key="thread-1",
        read_through_position=None,
        created_at=now,
        updated_at=now,
    )


def _active_session() -> AgentSession:
    now = datetime.datetime.now(datetime.UTC)
    return AgentSession(
        id="session-1",
        workspace_id="workspace-1",
        agent_id="agent-1",
        handle="test-session-handle",
        inference_state=None,
        applied_profile_generation=0,
        session_kind=AgentSessionKind.ROOT,
        status=AgentSessionStatus.ACTIVE,
        product_mode=AgentSessionProductMode.TEAM,
        associated_user_id=None,
        start_reason=AgentSessionStartReason.INITIAL,
        title=None,
        title_source=None,
        title_generated_at=None,
        title_generation_event_id=None,
        last_user_input_at=now,
        last_activity_at=now,
        pinned=False,
        started_at=now,
        owner_generation=0,
        created_at=now,
        updated_at=now,
        stop_requested_at=None,
    )


def _binding(
    response_mode: ExternalChannelResponseMode,
) -> ExternalChannelBinding:
    return ExternalChannelBinding.model_construct(
        id="binding-1",
        resource_id="source-1",
        route_id="route-1",
        agent_session_id="session-1",
        response_mode=response_mode,
    )


@pytest.mark.parametrize(
    ("invocation", "binding", "response_mode", "expected"),
    [
        (False, None, ExternalChannelResponseMode.ALL_MESSAGES, False),
        (True, None, ExternalChannelResponseMode.ALL_MESSAGES, True),
        (False, None, ExternalChannelResponseMode.MENTION_ONLY, False),
        (True, None, ExternalChannelResponseMode.MENTION_ONLY, True),
        (
            False,
            _binding(ExternalChannelResponseMode.ALL_MESSAGES),
            ExternalChannelResponseMode.ALL_MESSAGES,
            True,
        ),
        (
            False,
            _binding(ExternalChannelResponseMode.MENTION_ONLY),
            ExternalChannelResponseMode.MENTION_ONLY,
            False,
        ),
        (
            True,
            _binding(ExternalChannelResponseMode.MENTION_ONLY),
            ExternalChannelResponseMode.MENTION_ONLY,
            True,
        ),
    ],
)
def test_response_mode_requires_invocation_until_binding_exists(
    invocation: bool,
    binding: ExternalChannelBinding | None,
    response_mode: ExternalChannelResponseMode,
    expected: bool,
) -> None:
    """Only a connected all-messages Binding admits ordinary continuation."""
    assert (
        _response_mode_triggered(
            invocation=invocation,
            binding=binding,
            response_mode=response_mode,
        )
        is expected
    )


@pytest.mark.parametrize(
    ("provider", "location"),
    [
        (
            ExternalChannelProvider.SLACK,
            ExternalChannelConversationLocation.CHANNEL,
        ),
        (
            ExternalChannelProvider.SLACK,
            ExternalChannelConversationLocation.THREADS,
        ),
        (
            ExternalChannelProvider.DISCORD,
            ExternalChannelConversationLocation.CHANNEL,
        ),
        (
            ExternalChannelProvider.DISCORD,
            ExternalChannelConversationLocation.THREADS,
        ),
    ],
)
async def test_unbound_all_messages_non_invocation_stops_before_queue(
    provider: ExternalChannelProvider,
    location: ExternalChannelConversationLocation,
) -> None:
    """Parent configuration cannot join an unbound conversation automatically."""
    commit = AsyncMock()
    session = _Session(commit)
    repository = _Repository()
    repository.principal_call = AsyncMock()
    queue_repository = _QueueRepository()
    queue_repository.admit_call = AsyncMock()
    service = _service(
        repository,
        session_manager=_session_manager(session),
        queue_repository=queue_repository,
    )
    source = _resource("source-1", ExternalChannelResourceType.THREAD)
    target_resource = (
        _resource(
            "parent-resource-1",
            ExternalChannelResourceType.PARENT_CHANNEL,
        )
        if location is ExternalChannelConversationLocation.CHANNEL
        else source
    )
    target = _EffectiveTarget(
        resource=target_resource,
        route=_route(),
        setting=ExternalChannelParticipationSetting.model_construct(
            id="setting-1",
            route_id="route-1",
            location=location,
            response_mode=ExternalChannelResponseMode.ALL_MESSAGES,
            settings_generation=1,
        ),
        binding=None,
        response_mode=ExternalChannelResponseMode.ALL_MESSAGES,
    )

    with (
        patch.object(
            ExternalChannelIngressAdmissionService,
            "_lock_authority",
            new=AsyncMock(return_value=_connection()),
        ),
        patch.object(
            ExternalChannelIngressAdmissionService,
            "_ensure_source_resource",
            new=AsyncMock(return_value=source),
        ),
        patch.object(
            ExternalChannelIngressAdmissionService,
            "_resolve_target",
            new=AsyncMock(return_value=target),
        ),
    ):
        outcome = await service.admit_current_trigger(
            provider_event_id="event-1",
            request=_request(
                invocation=False,
                provider=provider,
            ),
        )

    assert outcome is not None
    assert outcome.kind is ExternalChannelIngestionOutcomeKind.IGNORED
    assert outcome.reason is ExternalChannelIngestionReason.RESPONSE_MODE_NOT_TRIGGERED
    commit.assert_awaited_once()
    repository.principal_call.assert_not_awaited()
    queue_repository.admit_call.assert_not_awaited()


async def test_bound_trigger_checks_session_without_row_lock() -> None:
    """Queue admission reads Session availability without serializing the row."""
    commit = AsyncMock()
    session = _Session(commit)
    repository = _Repository()
    repository.principal_call = AsyncMock(return_value=_principal())
    repository.block_call = AsyncMock(return_value=None)
    repository.grant_call = AsyncMock(return_value=_grant())
    repository.position_call = AsyncMock(return_value=_position())
    queue_repository = _QueueRepository()
    queue_repository.admit_call = AsyncMock()
    service = _service(
        repository,
        session_manager=_session_manager(session),
        queue_repository=queue_repository,
    )
    session_repository = _SessionRepository(
        get_by_id=AsyncMock(return_value=_active_session()),
        lock_by_id=AsyncMock(),
    )
    service.agent_session_repository = session_repository
    service._submit = AsyncMock()  # noqa: SLF001
    source = _resource("source-1", ExternalChannelResourceType.THREAD)
    route = _route().model_copy(update={"open_access_enabled": False})
    target = _EffectiveTarget(
        resource=source,
        route=route,
        setting=None,
        binding=_binding(ExternalChannelResponseMode.ALL_MESSAGES),
        response_mode=ExternalChannelResponseMode.ALL_MESSAGES,
    )

    with (
        patch.object(
            ExternalChannelIngressAdmissionService,
            "_lock_authority",
            new=AsyncMock(return_value=_connection()),
        ),
        patch.object(
            ExternalChannelIngressAdmissionService,
            "_ensure_source_resource",
            new=AsyncMock(return_value=source),
        ),
        patch.object(
            ExternalChannelIngressAdmissionService,
            "_resolve_target",
            new=AsyncMock(return_value=target),
        ),
    ):
        outcome = await service.admit_current_trigger(
            provider_event_id="event-1",
            request=_request(),
        )

    assert outcome is not None
    assert outcome.kind is ExternalChannelIngestionOutcomeKind.ACCEPTED
    assert session_repository.get_call is not None
    session_repository.get_call.assert_awaited_once_with(
        session,
        "session-1",
    )
    assert session_repository.lock_call is not None
    session_repository.lock_call.assert_not_awaited()
    queue_repository.admit_call.assert_awaited_once()
    commit.assert_awaited_once()


async def test_discord_channel_location_keeps_thread_as_owner_target() -> None:
    """Discord Threads remain independent from the configured parent conversation."""
    source = _resource("source-1", ExternalChannelResourceType.THREAD)
    repository = _Repository()
    repository.binding_call = AsyncMock(return_value=None)
    repository.route_call = AsyncMock(return_value=_route())
    repository.setting_call = AsyncMock(
        return_value=ExternalChannelParticipationSetting.model_construct(
            id="setting-1",
            route_id="route-1",
            location=ExternalChannelConversationLocation.CHANNEL,
            response_mode=ExternalChannelResponseMode.ALL_MESSAGES,
            settings_generation=1,
        )
    )
    repository.resource_lock_call = AsyncMock()
    repository.resource_create_call = AsyncMock()
    service = _service(repository)
    session = AsyncSession()

    target = await service._resolve_target(  # noqa: SLF001
        session,
        request=_request(),
        connection=_connection(),
        source_resource=source,
        now=datetime.datetime.now(datetime.UTC),
    )

    assert target is not None
    assert target.resource is source
    assert target.setting is not None
    assert target.binding is None
    assert target.response_mode is ExternalChannelResponseMode.ALL_MESSAGES
    repository.resource_lock_call.assert_not_awaited()
    repository.resource_create_call.assert_not_awaited()


async def test_threads_location_keeps_source_thread_as_owner_target() -> None:
    """A configured per-thread conversation does not fan into its parent."""
    source = _resource("source-1", ExternalChannelResourceType.THREAD)
    repository = _Repository()
    repository.binding_call = AsyncMock(return_value=None)
    repository.route_call = AsyncMock(return_value=_route())
    repository.setting_call = AsyncMock(
        return_value=ExternalChannelParticipationSetting.model_construct(
            id="setting-1",
            route_id="route-1",
            location=ExternalChannelConversationLocation.THREADS,
            response_mode=ExternalChannelResponseMode.MENTION_ONLY,
            settings_generation=1,
        )
    )
    repository.resource_lock_call = AsyncMock()
    service = _service(repository)

    target = await service._resolve_target(  # noqa: SLF001
        AsyncSession(),
        request=_request(),
        connection=_connection(),
        source_resource=source,
        now=datetime.datetime.now(datetime.UTC),
    )

    assert target is not None
    assert target.resource is source
    assert target.response_mode is ExternalChannelResponseMode.MENTION_ONLY
    repository.resource_lock_call.assert_not_awaited()


async def test_source_resource_create_race_rejects_inactive_result() -> None:
    """An idempotent create conflict cannot admit an unavailable source."""
    inactive = ExternalChannelResource.model_construct(
        id="source-1",
        connection_id="connection-1",
        resource_type=ExternalChannelResourceType.THREAD,
        provider_resource_key="discord:guild-1:thread-1",
        labels=None,
        status=ExternalChannelResourceStatus.UNAVAILABLE,
    )
    repository = _Repository()
    repository.resource_lock_call = AsyncMock(side_effect=[None, inactive])
    repository.resource_create_call = AsyncMock(return_value=inactive)
    service = _service(repository)

    resource = await service._ensure_source_resource(  # noqa: SLF001
        AsyncSession(),
        request=_request(),
        now=datetime.datetime.now(datetime.UTC),
    )

    assert resource is None
    repository.resource_create_call.assert_awaited_once()
