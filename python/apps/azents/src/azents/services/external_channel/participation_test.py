"""Provider-neutral External Channel participation service tests."""

import datetime
from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from unittest.mock import ANY, AsyncMock, create_autospec

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    ExternalChannelAppMode,
    ExternalChannelConnectionStatus,
    ExternalChannelConversationLocation,
    ExternalChannelConversationScopeKind,
    ExternalChannelParticipationSettingStatus,
    ExternalChannelProvider,
    ExternalChannelResourceStatus,
    ExternalChannelResourceType,
    ExternalChannelResponseMode,
    ExternalChannelSetupClaimStatus,
    ExternalChannelTransport,
)
from azents.core.external_channel_conversation_data import (
    ExternalChannelConversationLockLease,
    ExternalChannelConversationScope,
    ExternalChannelOperationDeadline,
    ExternalChannelParticipationScope,
)
from azents.core.external_channel_ingestion import (
    ExternalChannelIngestionOutcome,
    ExternalChannelIngestionOutcomeKind,
    ExternalChannelIngestionReason,
)
from azents.core.external_channel_participation_state import (
    ExternalChannelSetupSourceProjection,
    projection_with_setup_source,
)
from azents.repos.agent import AgentRepository
from azents.repos.external_channel.data import (
    ExternalChannelAgentRoute,
    ExternalChannelBinding,
    ExternalChannelConnection,
    ExternalChannelConnectionConfiguration,
    ExternalChannelParticipationSetting,
    ExternalChannelResource,
    ExternalChannelResourceCreate,
    ExternalChannelSetupClaim,
)
from azents.repos.external_channel.management import ExternalChannelManagementRepository
from azents.repos.external_channel.repository import ExternalChannelRepository
from azents.repos.workspace import WorkspaceRepository
from azents.services.external_channel.ingestion_replay import (
    ExternalChannelIngestionReplayService,
)
from azents.services.external_channel.participation import (
    ExternalChannelParticipationError,
    ExternalChannelParticipationService,
    ExternalChannelParticipationSessionNavigation,
    _AuthorizedSettingsActor,
    _CommittedLocation,
    _session_navigation,
    _thread_conversation_scope,
)

_NOW = datetime.datetime(2026, 8, 1, tzinfo=datetime.UTC)


@asynccontextmanager
async def _session_manager() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSession() as session:
        yield session


class _Lease:
    async def assert_owned(self) -> None:
        pass


class _Lock:
    def acquire(
        self,
        *,
        scope: ExternalChannelConversationScope | ExternalChannelParticipationScope,
        deadline: ExternalChannelOperationDeadline,
    ) -> AbstractAsyncContextManager[ExternalChannelConversationLockLease]:
        del scope, deadline

        @asynccontextmanager
        async def owned() -> AsyncIterator[ExternalChannelConversationLockLease]:
            yield _Lease()

        return owned()


def _configuration(
    *,
    id: str,
    status: ExternalChannelConnectionStatus,
    provider: ExternalChannelProvider,
    provider_tenant_id: str,
) -> ExternalChannelConnectionConfiguration:
    return ExternalChannelConnectionConfiguration(
        id=id,
        workspace_id="workspace-1",
        provider=provider,
        status=status,
        provider_tenant_id=provider_tenant_id,
        transport=ExternalChannelTransport.HTTP,
        app_mode=ExternalChannelAppMode.SINGLE,
        provider_app_id=None,
        provider_bot_user_id=None,
        http_callback_selector_hash=None,
        encrypted_credentials=None,
        capabilities=None,
        provider_config=None,
        last_verified_at=None,
        last_health_at=None,
        disconnected_at=None,
        socket_lease_owner=None,
        socket_lease_until=None,
        socket_heartbeat_at=None,
        socket_gap_detected_at=None,
        socket_gap_reason=None,
        created_at=_NOW,
        updated_at=_NOW,
    )


class _Repository(ExternalChannelRepository):
    def __init__(self) -> None:
        super().__init__()
        self.configuration_call = AsyncMock(
            side_effect=AssertionError("Unexpected configuration read")
        )
        self.provider_resource_call = AsyncMock(
            side_effect=AssertionError("Unexpected resource read")
        )
        self.delivery_resource_call = AsyncMock(
            side_effect=AssertionError("Unexpected Discord resource read")
        )
        self.setting_call = AsyncMock(
            side_effect=AssertionError("Unexpected setting read")
        )
        self.connection_lock_call = AsyncMock(
            side_effect=AssertionError("Unexpected connection lock")
        )
        self.setting_lock_call = AsyncMock(
            side_effect=AssertionError("Unexpected setting lock")
        )
        self.setting_update_call = AsyncMock(
            side_effect=AssertionError("Unexpected setting mutation")
        )
        self.claim_call = AsyncMock(
            side_effect=AssertionError("Unexpected setup claim read")
        )
        self.resource_lock_call = AsyncMock(
            side_effect=AssertionError("Unexpected resource lock")
        )
        self.resource_create_call = AsyncMock(
            side_effect=AssertionError("Unexpected resource create")
        )

    async def get_connection_configuration(
        self,
        session: AsyncSession,
        *,
        connection_id: str,
    ) -> ExternalChannelConnectionConfiguration | None:
        result: object = await self.configuration_call(
            session, connection_id=connection_id
        )
        assert result is None or isinstance(
            result, ExternalChannelConnectionConfiguration
        )
        return result

    async def get_resource_by_provider_key(
        self,
        session: AsyncSession,
        *,
        connection_id: str,
        resource_type: ExternalChannelResourceType,
        provider_resource_key: str,
    ) -> ExternalChannelResource | None:
        result: object = await self.provider_resource_call(
            session,
            connection_id=connection_id,
            resource_type=resource_type,
            provider_resource_key=provider_resource_key,
        )
        assert result is None or isinstance(result, ExternalChannelResource)
        return result

    async def get_discord_resource_by_delivery_channel(
        self,
        session: AsyncSession,
        *,
        connection_id: str,
        guild_id: str,
        delivery_channel_id: str,
    ) -> ExternalChannelResource | None:
        result: object = await self.delivery_resource_call(
            session,
            connection_id=connection_id,
            guild_id=guild_id,
            delivery_channel_id=delivery_channel_id,
        )
        assert result is None or isinstance(result, ExternalChannelResource)
        return result

    async def get_active_participation_setting(
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

    async def lock_connection_for_routing(
        self,
        session: AsyncSession,
        *,
        connection_id: str,
    ) -> ExternalChannelConnection | None:
        result: object = await self.connection_lock_call(
            session, connection_id=connection_id
        )
        assert result is None or isinstance(result, ExternalChannelConnection)
        return result

    async def lock_active_participation_setting(
        self,
        session: AsyncSession,
        *,
        connection_id: str,
        provider_parent_channel_id: str,
    ) -> ExternalChannelParticipationSetting | None:
        result: object = await self.setting_lock_call(
            session,
            connection_id=connection_id,
            provider_parent_channel_id=provider_parent_channel_id,
        )
        assert result is None or isinstance(result, ExternalChannelParticipationSetting)
        return result

    async def update_participation_setting(
        self,
        session: AsyncSession,
        *,
        setting_id: str,
        expected_settings_generation: int,
        location: ExternalChannelConversationLocation,
        response_mode: ExternalChannelResponseMode,
        configured_by_principal_id: str,
    ) -> ExternalChannelParticipationSetting | None:
        result: object = await self.setting_update_call(
            session,
            setting_id=setting_id,
            expected_settings_generation=expected_settings_generation,
            location=location,
            response_mode=response_mode,
            configured_by_principal_id=configured_by_principal_id,
        )
        assert result is None or isinstance(result, ExternalChannelParticipationSetting)
        return result

    async def get_setup_claim(
        self,
        session: AsyncSession,
        *,
        claim_id: str,
    ) -> ExternalChannelSetupClaim | None:
        result: object = await self.claim_call(session, claim_id=claim_id)
        assert result is None or isinstance(result, ExternalChannelSetupClaim)
        return result

    async def lock_resource(
        self,
        session: AsyncSession,
        *,
        resource_id: str,
    ) -> ExternalChannelResource | None:
        result: object = await self.resource_lock_call(session, resource_id=resource_id)
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


class _Replay(ExternalChannelIngestionReplayService):
    def __init__(self, replay_setup_claim: AsyncMock) -> None:
        self.replay_call = replay_setup_claim

    async def replay_setup_claim(
        self,
        *,
        setup_claim_id: str,
        deadline: ExternalChannelOperationDeadline,
    ) -> ExternalChannelIngestionOutcome:
        result: object = await self.replay_call(
            setup_claim_id=setup_claim_id, deadline=deadline
        )
        assert isinstance(result, ExternalChannelIngestionOutcome)
        return result


def _source() -> ExternalChannelSetupSourceProjection:
    return ExternalChannelSetupSourceProjection(
        schema_version=1,
        provider=ExternalChannelProvider.SLACK,
        provider_event_type="app_mention",
        provider_tenant_id="tenant-1",
        provider_channel_id="channel-1",
        provider_parent_channel_id="channel-1",
        scope_kind=ExternalChannelConversationScopeKind.PARENT_CHANNEL,
        provider_thread_key=None,
        delivery_thread_key="1.000000",
        provider_resource_key="slack:tenant-1:channel-1:1.000000",
        trigger_provider_message_key="slack:tenant-1:channel-1:1.000000",
        trigger_provider_message_id="1.000000",
        trigger_position="00000000000000000001",
        range_start_position=None,
    )


def _claim(
    *,
    status: ExternalChannelSetupClaimStatus,
) -> ExternalChannelSetupClaim:
    return ExternalChannelSetupClaim.model_construct(
        id="claim-1",
        connection_id="connection-1",
        provider_parent_channel_id="channel-1",
        route_id="route-1",
        conversation_position_id="position-1",
        source_resource_id="source-resource-1",
        principal_id="principal-1",
        source_projection=projection_with_setup_source(_source()),
        source_revision=2,
        claim_generation=1,
        status=status,
        selected_setting_id=(
            "setting-1"
            if status
            in {
                ExternalChannelSetupClaimStatus.SELECTED,
                ExternalChannelSetupClaimStatus.COMPLETED,
            }
            else None
        ),
        selected_resource_id=(
            "parent-resource-1"
            if status
            in {
                ExternalChannelSetupClaimStatus.SELECTED,
                ExternalChannelSetupClaimStatus.COMPLETED,
            }
            else None
        ),
        selected_source_revision=(
            2
            if status
            in {
                ExternalChannelSetupClaimStatus.SELECTED,
                ExternalChannelSetupClaimStatus.COMPLETED,
            }
            else None
        ),
    )


def _setting() -> ExternalChannelParticipationSetting:
    return ExternalChannelParticipationSetting.model_construct(
        id="setting-1",
        connection_id="connection-1",
        provider_parent_channel_id="channel-1",
        route_id="route-1",
        location=ExternalChannelConversationLocation.CHANNEL,
        response_mode=ExternalChannelResponseMode.MENTION_ONLY,
        settings_generation=1,
        configured_by_user_id=None,
        configured_by_principal_id="principal-1",
        status=ExternalChannelParticipationSettingStatus.ACTIVE,
    )


def _service(
    *,
    repository: _Repository,
    replay: _Replay | None = None,
) -> ExternalChannelParticipationService:
    return ExternalChannelParticipationService(
        session_manager=_session_manager,
        repository=repository,
        management_repository=create_autospec(
            ExternalChannelManagementRepository, instance=True, spec_set=True
        ),
        agent_repository=create_autospec(AgentRepository, instance=True, spec_set=True),
        workspace_repository=create_autospec(
            WorkspaceRepository, instance=True, spec_set=True
        ),
        ingestion_replay_service=replay
        if replay is not None
        else create_autospec(
            ExternalChannelIngestionReplayService, instance=True, spec_set=True
        ),
        conversation_lock=_Lock(),
        participation_lock=_Lock(),
    )


def test_session_navigation_requires_the_authorized_route_binding() -> None:
    """Project one exact Session target and omit unrelated or absent Bindings."""
    actor = _AuthorizedSettingsActor(
        route=ExternalChannelAgentRoute.model_construct(
            id="route-1",
            agent_id="agent-1",
        ),
        agent_name="Agent One",
        workspace_handle="workspace",
    )
    binding = ExternalChannelBinding.model_construct(
        id="binding-1",
        route_id="route-1",
        agent_session_id="session-1",
    )

    assert _session_navigation(actor=actor, binding=binding) == (
        ExternalChannelParticipationSessionNavigation(
            workspace_handle="workspace",
            agent_id="agent-1",
            session_id="session-1",
        )
    )
    assert (
        _session_navigation(
            actor=actor,
            binding=binding.model_copy(update={"route_id": "route-2"}),
        )
        is None
    )
    assert _session_navigation(actor=actor, binding=None) is None


def test_slack_thread_settings_use_channel_and_thread_timestamp_lock_scope() -> None:
    """Reuse the same Slack conversation identity as trigger ingestion."""
    scope = _thread_conversation_scope(
        connection_id="connection-1",
        connection_provider=ExternalChannelProvider.SLACK,
        provider_parent_channel_id="channel-1",
        resource=ExternalChannelResource.model_construct(
            labels={"thread_ts": "1.000000"},
        ),
    )

    assert scope == ExternalChannelConversationScope(
        connection_id="connection-1",
        kind=ExternalChannelConversationScopeKind.THREAD,
        provider_channel_id="channel-1",
        provider_thread_key="1.000000",
    )


def test_discord_thread_settings_use_delivery_channel_lock_scope() -> None:
    """Reuse the Discord thread channel identity used by trigger ingestion."""
    scope = _thread_conversation_scope(
        connection_id="connection-1",
        connection_provider=ExternalChannelProvider.DISCORD,
        provider_parent_channel_id="parent-1",
        resource=ExternalChannelResource.model_construct(
            labels={
                "thread_id": "thread-1",
                "delivery_channel_id": "thread-1",
            },
        ),
    )

    assert scope == ExternalChannelConversationScope(
        connection_id="connection-1",
        kind=ExternalChannelConversationScopeKind.THREAD,
        provider_channel_id="thread-1",
        provider_thread_key="thread-1",
    )


def test_thread_settings_reject_resources_without_provider_lock_identity() -> None:
    """Reject resources that cannot reproduce their canonical ingestion scope."""
    with pytest.raises(
        ExternalChannelParticipationError,
        match="thread settings are unavailable",
    ):
        _thread_conversation_scope(
            connection_id="connection-1",
            connection_provider=ExternalChannelProvider.DISCORD,
            provider_parent_channel_id="parent-1",
            resource=ExternalChannelResource.model_construct(labels={}),
        )


@pytest.mark.asyncio
async def test_thread_settings_never_fall_back_to_parent_scope() -> None:
    """A proven thread scope requires its exact connected thread Binding."""
    repository = _Repository()
    repository.configuration_call = AsyncMock(
        return_value=_configuration(
            id="connection-1",
            status=ExternalChannelConnectionStatus.ACTIVE,
            provider=ExternalChannelProvider.SLACK,
            provider_tenant_id="tenant-1",
        )
    )
    repository.provider_resource_call = AsyncMock(return_value=None)
    repository.setting_call = AsyncMock(return_value=_setting())
    service = _service(repository=repository)

    with pytest.raises(
        ExternalChannelParticipationError,
        match="thread settings are unavailable",
    ):
        await service.resolve_settings(
            connection_id="connection-1",
            provider_parent_channel_id="channel-1",
            provider_thread_resource_key="slack:tenant-1:channel-1:1.000000",
            expected_binding_id=None,
            principal_id="principal-1",
        )

    repository.setting_call.assert_not_awaited()


@pytest.mark.asyncio
async def test_discord_thread_settings_resolve_by_delivery_channel() -> None:
    """A Discord interaction finds a provisioned thread through retained labels."""
    repository = _Repository()
    repository.configuration_call = AsyncMock(
        return_value=_configuration(
            id="connection-1",
            status=ExternalChannelConnectionStatus.ACTIVE,
            provider=ExternalChannelProvider.DISCORD,
            provider_tenant_id="guild-1",
        )
    )
    repository.delivery_resource_call = AsyncMock(return_value=None)
    repository.provider_resource_call = AsyncMock()
    service = _service(repository=repository)

    with pytest.raises(
        ExternalChannelParticipationError,
        match="thread settings are unavailable",
    ):
        await service.resolve_settings(
            connection_id="connection-1",
            provider_parent_channel_id="channel-1",
            provider_thread_resource_key="discord:guild-1:thread-1",
            expected_binding_id=None,
            principal_id="principal-1",
        )

    repository.delivery_resource_call.assert_awaited_once_with(
        ANY,
        connection_id="connection-1",
        guild_id="guild-1",
        delivery_channel_id="thread-1",
    )
    repository.provider_resource_call.assert_not_awaited()


@pytest.mark.asyncio
async def test_parent_mutation_rejects_replacement_setting_before_any_write() -> None:
    """Fence a stale modal by signed setting identity as well as generation."""
    repository = _Repository()
    repository.connection_lock_call = AsyncMock(
        return_value=ExternalChannelConnection.model_validate(
            _configuration(
                id="connection-1",
                status=ExternalChannelConnectionStatus.ACTIVE,
                provider=ExternalChannelProvider.SLACK,
                provider_tenant_id="tenant-1",
            ).model_dump(exclude={"encrypted_credentials"})
        )
    )
    repository.setting_lock_call = AsyncMock(
        return_value=_setting().model_copy(update={"id": "replacement-setting"})
    )
    repository.setting_update_call = AsyncMock()
    service = _service(repository=repository)

    with pytest.raises(
        ExternalChannelParticipationError,
        match="settings changed before submission",
    ):
        await service.mutate_parent_settings(
            connection_id="connection-1",
            provider_parent_channel_id="channel-1",
            principal_id="principal-1",
            expected_setting_id="setting-1",
            expected_settings_generation=1,
            location=ExternalChannelConversationLocation.THREADS,
            response_mode=ExternalChannelResponseMode.MENTION_ONLY,
            now=_NOW,
            deadline=ExternalChannelOperationDeadline(
                _NOW + datetime.timedelta(seconds=30)
            ),
        )

    repository.setting_update_call.assert_not_awaited()


@pytest.mark.asyncio
async def test_replay_failure_preserves_committed_location_for_recovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Selection commits first and reports a recoverable replay failure."""
    events: list[str] = []
    pending = _claim(status=ExternalChannelSetupClaimStatus.PENDING_LOCATION)
    selected = _claim(status=ExternalChannelSetupClaimStatus.SELECTED)
    repository = _Repository()
    repository.claim_call = AsyncMock(return_value=pending)

    async def replay_setup_claim(**kwargs: object) -> ExternalChannelIngestionOutcome:
        del kwargs
        events.append("replay")
        return ExternalChannelIngestionOutcome(
            kind=ExternalChannelIngestionOutcomeKind.RETRYABLE_FAILURE,
            reason=ExternalChannelIngestionReason.HISTORY_UNAVAILABLE,
            mailbox_item_id=None,
            control_plans=(),
            connection_id=None,
        )

    replay = _Replay(AsyncMock(side_effect=replay_setup_claim))
    service = _service(repository=repository, replay=replay)

    async def commit_location(
        *,
        setup_claim_id: str,
        expected_claim_generation: int,
        expected_source_revision: int,
        location: ExternalChannelConversationLocation,
        configured_by_principal_id: str,
        source: ExternalChannelSetupSourceProjection,
        now: datetime.datetime,
    ) -> _CommittedLocation:
        del (
            setup_claim_id,
            expected_claim_generation,
            expected_source_revision,
            location,
            configured_by_principal_id,
            source,
            now,
        )
        events.append("commit")
        return _CommittedLocation(
            setting=_setting(),
            claim=selected,
            created=True,
        )

    monkeypatch.setattr(service, "_commit_location", commit_location)

    result = await service.select_location(
        setup_claim_id=pending.id,
        expected_claim_generation=1,
        expected_source_revision=2,
        location=ExternalChannelConversationLocation.CHANNEL,
        configured_by_principal_id="principal-1",
        now=_NOW,
        deadline=ExternalChannelOperationDeadline(
            _NOW + datetime.timedelta(seconds=30)
        ),
    )

    assert events == ["commit", "replay"]
    assert result.status == "pending_recovery"
    assert result.setting.id == "setting-1"
    assert result.claim.status is ExternalChannelSetupClaimStatus.SELECTED
    assert result.replay_outcome is not None
    assert (
        result.replay_outcome.kind
        is ExternalChannelIngestionOutcomeKind.RETRYABLE_FAILURE
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("location", "expected_resource_type"),
    [
        (
            ExternalChannelConversationLocation.CHANNEL,
            ExternalChannelResourceType.PARENT_CHANNEL,
        ),
        (
            ExternalChannelConversationLocation.THREADS,
            ExternalChannelResourceType.THREAD,
        ),
    ],
)
async def test_location_selection_resolves_explicit_target_resource(
    location: ExternalChannelConversationLocation,
    expected_resource_type: ExternalChannelResourceType,
) -> None:
    """Channel creates a parent Resource while Threads retains the source Resource."""
    source_resource = ExternalChannelResource.model_construct(
        id="source-resource-1",
        connection_id="connection-1",
        resource_type=ExternalChannelResourceType.THREAD,
        provider_resource_key="slack:tenant-1:channel-1:1.000000",
        status=ExternalChannelResourceStatus.ACTIVE,
    )
    parent_resource = ExternalChannelResource.model_construct(
        id="parent-resource-1",
        connection_id="connection-1",
        resource_type=ExternalChannelResourceType.PARENT_CHANNEL,
        provider_resource_key="channel-1",
        status=ExternalChannelResourceStatus.ACTIVE,
    )
    repository = _Repository()
    repository.resource_lock_call = AsyncMock(return_value=source_resource)
    repository.resource_create_call = AsyncMock(return_value=parent_resource)
    service = _service(repository=repository)

    resolved = await service._resolve_selected_resource(
        AsyncSession(),
        claim=_claim(status=ExternalChannelSetupClaimStatus.PENDING_LOCATION),
        source=_source(),
        location=location,
        now=_NOW,
    )

    assert resolved.resource_type is expected_resource_type
    if location is ExternalChannelConversationLocation.CHANNEL:
        create_args = repository.resource_create_call.await_args
        assert create_args is not None
        create = create_args.args[1]
        assert create.resource_type is ExternalChannelResourceType.PARENT_CHANNEL
        assert create.provider_resource_key == "channel-1"
        repository.resource_lock_call.assert_not_awaited()
    else:
        assert resolved is source_resource
        repository.resource_create_call.assert_not_awaited()
