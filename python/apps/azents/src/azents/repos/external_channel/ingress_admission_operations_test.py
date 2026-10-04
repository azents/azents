"""Real PostgreSQL transaction ownership for configured channel admission."""

import datetime
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, replace
from unittest.mock import AsyncMock, MagicMock

import pytest
import sqlalchemy as sa
from azcommon.result import Success
from sqlalchemy.ext.asyncio import AsyncEngine

from azents.core.enums import (
    ExternalChannelAccessRequestStatus,
    ExternalChannelAppMode,
    ExternalChannelConnectionStatus,
    ExternalChannelConversationLocation,
    ExternalChannelConversationScopeKind,
    ExternalChannelIngressAuthorityKind,
    ExternalChannelIngressProfile,
    ExternalChannelParticipationSettingStatus,
    ExternalChannelPrincipalAuthorType,
    ExternalChannelProvider,
    ExternalChannelResponseMode,
    ExternalChannelRouteCatalogStatus,
    ExternalChannelRouteMode,
    ExternalChannelTransport,
    LLMProvider,
)
from azents.core.external_channel_conversation_data import (
    ExternalChannelConversationScope,
    ExternalChannelOperationDeadline,
)
from azents.core.external_channel_ingestion import (
    ExternalChannelIngestionOperation,
    ExternalChannelIngestionOutcome,
    ExternalChannelIngestionOutcomeKind,
    ExternalChannelIngestionRequest,
    ExternalChannelIngressAuthority,
    ExternalChannelTriggerLocator,
)
from azents.core.external_channel_replay import (
    ExternalChannelIngestionReplayUnavailable,
)
from azents.core.workspace import WorkspaceCreate
from azents.job_runtime.types import JobHandle, JobOutcome, JobRequest
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.external_channel import (
    RDBExternalChannelAgentRoute,
    RDBExternalChannelConversationPosition,
    RDBExternalChannelPrincipal,
    RDBExternalChannelResource,
)
from azents.rdb.models.external_channel_ingress import (
    RDBExternalChannelIngressItem,
    RDBExternalChannelIngressOwner,
)
from azents.rdb.models.llm_provider_integration import RDBLLMProviderIntegration
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import (
    ReadSession,
    WriteSession,
    create_read_only_session_manager,
    create_read_write_session_manager,
)
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.external_channel.data import (
    ExternalChannelAccessRequestCreate,
    ExternalChannelAgentRouteCreate,
    ExternalChannelConnectionCreate,
    ExternalChannelParticipationSettingCreate,
    ExternalChannelPrincipalCreate,
)
from azents.repos.external_channel.http_admission_read import (
    ExternalChannelHTTPAdmissionReadRepository,
)
from azents.repos.external_channel.ingestion_history_read import (
    ExternalChannelHistoryReadRepository,
)
from azents.repos.external_channel.ingestion_replay_operations import (
    ExternalChannelReplayOperations,
)
from azents.repos.external_channel.ingress_admission_operations import (
    ExternalChannelIngressAdmissionOperations,
)
from azents.repos.external_channel.ingress_queue import (
    ExternalChannelIngressQueueRepository,
)
from azents.repos.external_channel.ingress_queue_data import (
    ExternalChannelIngressAdmission,
    ExternalChannelIngressItemCreate,
    ExternalChannelIngressOwnerCreate,
)
from azents.repos.external_channel.repository import ExternalChannelRepository
from azents.repos.external_channel.transport_ingestion_read import (
    ExternalChannelTransportReadRepository,
)
from azents.repos.workspace import WorkspaceRepository
from azents.services.external_channel.ingestion import (
    ExternalChannelConversationIngestionService,
)
from azents.services.external_channel.ingestion_replay import (
    ExternalChannelIngestionReplayService,
)
from azents.services.external_channel.ingress_admission import (
    ExternalChannelIngressAdmissionService,
)
from azents.testing.model_selection import (
    make_test_model_selection_dict,
    make_test_selectable_model_option_dicts,
)
from azents.testing.types import require_instance


@dataclass(frozen=True)
class _Fixture:
    operations: ExternalChannelIngressAdmissionOperations
    request: ExternalChannelIngestionRequest
    route_id: str


async def _fixture(engine: AsyncEngine, *, label: str) -> _Fixture:
    """Create committed isolated authority using the native RW scope factory."""
    manager = create_read_write_session_manager(engine)
    repository = ExternalChannelRepository()
    now = datetime.datetime.now(datetime.UTC)
    async with manager() as session:
        workspace_repository = WorkspaceRepository()
        created = await workspace_repository.create(
            session, WorkspaceCreate(name=label, handle=label)
        )
        assert isinstance(created, Success)
        workspace_id = await workspace_repository.resolve_id(session, label)
        assert workspace_id is not None
        integration = RDBLLMProviderIntegration(
            workspace_id=workspace_id,
            provider=LLMProvider.ANTHROPIC,
            name=label,
            encrypted_credentials="encrypted",
            config=None,
        )
        session.write_session.add(integration)
        await session.write_session.flush()
        selection = make_test_model_selection_dict(
            integration_id=integration.id,
            provider=LLMProvider.ANTHROPIC,
            model_identifier="admission-model",
        )
        agent = RDBAgent(
            workspace_id=workspace_id,
            name=label,
            model_selection=selection,
            lightweight_model_selection=selection,
            selectable_model_options=make_test_selectable_model_option_dicts(
                model_selection=selection, lightweight_model_selection=selection
            ),
            main_model_label="default",
            lightweight_model_label="lightweight",
        )
        session.write_session.add(agent)
        await session.write_session.flush()
        connection = await repository.create_connection(
            session,
            ExternalChannelConnectionCreate(
                workspace_id=workspace_id,
                provider=ExternalChannelProvider.SLACK,
                transport=ExternalChannelTransport.HTTP,
                ingress_profile=ExternalChannelIngressProfile.SLACK_HTTP,
                app_mode=ExternalChannelAppMode.SINGLE,
                status=ExternalChannelConnectionStatus.ACTIVE,
                provider_app_id=f"{label}-app",
                provider_tenant_id=f"{label}-tenant",
                provider_bot_user_id=None,
                http_callback_selector_hash=None,
                encrypted_credentials="ciphertext",
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
            ),
        )
        route = await repository.create_agent_route(
            session,
            ExternalChannelAgentRouteCreate(
                connection_id=connection.id,
                agent_id=agent.id,
                agent_id_snapshot=agent.id,
                route_mode=ExternalChannelRouteMode.DEDICATED,
                connection_app_mode=ExternalChannelAppMode.SINGLE,
                catalog_status=ExternalChannelRouteCatalogStatus.AVAILABLE,
                catalog_removed_at=None,
                catalog_removed_by_user_id=None,
            ),
        )
        configuring_principal = await repository.create_principal_idempotent(
            session,
            ExternalChannelPrincipalCreate(
                provider=ExternalChannelProvider.SLACK,
                provider_tenant_id=f"{label}-tenant",
                provider_user_id="UCONFIG",
                author_type=ExternalChannelPrincipalAuthorType.HUMAN,
                display_name=None,
                avatar_url=None,
                profile=None,
            ),
        )
        await repository.create_participation_setting(
            session,
            ExternalChannelParticipationSettingCreate(
                connection_id=connection.id,
                provider_parent_channel_id="C1",
                route_id=route.id,
                location=ExternalChannelConversationLocation.THREADS,
                response_mode=ExternalChannelResponseMode.ALL_MESSAGES,
                settings_generation=1,
                configured_by_user_id=None,
                configured_by_principal_id=configuring_principal.id,
                status=ExternalChannelParticipationSettingStatus.ACTIVE,
                invalidated_at=None,
                invalidation_reason=None,
            ),
        )
    tenant = f"{label}-tenant"
    request = ExternalChannelIngestionRequest(
        locator=ExternalChannelTriggerLocator(
            connection_id=connection.id,
            provider=ExternalChannelProvider.SLACK,
            provider_event_type="app_mention",
            provider_tenant_id=tenant,
            provider_channel_id="C1",
            provider_parent_channel_id=None,
            provider_thread_key="1.0",
            delivery_thread_key="1.0",
            provider_resource_key=f"slack:{tenant}:C1:1.0",
            trigger_provider_message_key=f"slack:{tenant}:C1:2.0",
            trigger_provider_message_id="2.0",
            trigger_position="00000000000000000002",
            provider_user_id="U1",
            invocation=True,
            expected_file_count=None,
        ),
        scope=ExternalChannelConversationScope(
            connection_id=connection.id,
            kind=ExternalChannelConversationScopeKind.THREAD,
            provider_channel_id="C1",
            provider_thread_key="1.0",
        ),
        authority=ExternalChannelIngressAuthority(
            kind=ExternalChannelIngressAuthorityKind.CONFIGURATION,
            ingress_profile=ExternalChannelIngressProfile.SLACK_HTTP,
            configuration_generation=connection.configuration_generation,
            lease_owner=None,
            lease_generation=None,
        ),
        deadline=ExternalChannelOperationDeadline(now + datetime.timedelta(seconds=30)),
        operation=ExternalChannelIngestionOperation.CURRENT_TRIGGER,
        selected_route_id=None,
        replay_boundary=None,
        initial_title_eligible=False,
    )
    return _Fixture(
        operations=ExternalChannelIngressAdmissionOperations(
            session_manager=manager,
            repository=repository,
            queue_repository=ExternalChannelIngressQueueRepository(),
            agent_session_repository=AgentSessionRepository(),
        ),
        request=request,
        route_id=route.id,
    )


async def _counts(session: ReadSession, connection_id: str) -> tuple[int, ...]:
    """Count actual committed rows through a fresh PostgreSQL read scope."""
    queries = (
        sa.select(sa.func.count())
        .select_from(RDBExternalChannelResource)
        .where(RDBExternalChannelResource.connection_id == connection_id),
        sa.select(sa.func.count())
        .select_from(RDBExternalChannelConversationPosition)
        .where(RDBExternalChannelConversationPosition.connection_id == connection_id),
        sa.select(sa.func.count())
        .select_from(RDBExternalChannelIngressOwner)
        .where(RDBExternalChannelIngressOwner.connection_id == connection_id),
        sa.select(sa.func.count())
        .select_from(RDBExternalChannelIngressItem)
        .where(RDBExternalChannelIngressItem.connection_id == connection_id),
    )
    counts = []
    for query in queries:
        counts.append(int(await session.read_session.scalar(query) or 0))
    return tuple(counts)


async def test_completed_trigger_operation_is_atomic_and_idempotent(
    rdb_engine: AsyncEngine, latest_db_schema: None
) -> None:
    fixture = await _fixture(rdb_engine, label="wt9-admission-idempotency")
    now = datetime.datetime.now(datetime.UTC)
    first = await fixture.operations.admit_current_trigger(
        provider_event_id="event-1", request=fixture.request, now=now
    )
    second = await fixture.operations.admit_current_trigger(
        provider_event_id="event-1", request=fixture.request, now=now
    )
    assert first.outcome is not None and second.outcome is not None
    assert first.outcome.kind is ExternalChannelIngestionOutcomeKind.ACCEPTED
    assert second.outcome.kind is ExternalChannelIngestionOutcomeKind.DUPLICATE
    assert first.admission is not None and second.admission is not None
    assert first.admission.owner.id == second.admission.owner.id
    async with create_read_only_session_manager(rdb_engine)() as session:
        assert (
            await session.read_session.scalar(sa.text("SHOW transaction_read_only"))
            == "on"
        )
        assert await _counts(session, fixture.request.locator.connection_id) == (
            1,
            1,
            1,
            1,
        )


class _FailingQueue(ExternalChannelIngressQueueRepository):
    """Fail after the real queue writes to exercise the encompassing rollback."""

    async def admit(
        self,
        session: WriteSession,
        *,
        owner_create: ExternalChannelIngressOwnerCreate,
        item_create: ExternalChannelIngressItemCreate,
    ) -> ExternalChannelIngressAdmission:
        await super().admit(session, owner_create=owner_create, item_create=item_create)
        raise RuntimeError("Injected queue failure after writes")


async def test_queue_failure_rolls_back_source_principal_position_owner_and_item(
    rdb_engine: AsyncEngine, latest_db_schema: None
) -> None:
    fixture = await _fixture(rdb_engine, label="wt9-admission-rollback")
    operations = replace(fixture.operations, queue_repository=_FailingQueue())
    with pytest.raises(RuntimeError, match="Injected queue failure"):
        await operations.admit_current_trigger(
            provider_event_id="event-1",
            request=fixture.request,
            now=datetime.datetime.now(datetime.UTC),
        )
    async with create_read_only_session_manager(rdb_engine)() as session:
        assert await _counts(session, fixture.request.locator.connection_id) == (
            0,
            0,
            0,
            0,
        )
        principal_count = await session.read_session.scalar(
            sa.select(sa.func.count())
            .select_from(RDBExternalChannelPrincipal)
            .where(
                RDBExternalChannelPrincipal.provider_tenant_id
                == fixture.request.locator.provider_tenant_id,
                RDBExternalChannelPrincipal.provider_user_id == "U1",
            )
        )
        assert principal_count == 0


async def test_stale_authority_and_restricted_route_never_queue(
    rdb_engine: AsyncEngine, latest_db_schema: None
) -> None:
    fixture = await _fixture(rdb_engine, label="wt9-admission-authorization")
    stale = replace(
        fixture.request,
        authority=replace(
            fixture.request.authority,
            configuration_generation=fixture.request.authority.configuration_generation
            + 1,
        ),
    )
    result = await fixture.operations.admit_current_trigger(
        provider_event_id="stale",
        request=stale,
        now=datetime.datetime.now(datetime.UTC),
    )
    assert result.outcome is None and result.admission is None
    async with create_read_write_session_manager(rdb_engine)() as session:
        await session.write_session.execute(
            sa.update(RDBExternalChannelAgentRoute)
            .where(RDBExternalChannelAgentRoute.id == fixture.route_id)
            .values(open_access_enabled=False)
        )
    result = await fixture.operations.admit_current_trigger(
        provider_event_id="restricted",
        request=fixture.request,
        now=datetime.datetime.now(datetime.UTC),
    )
    assert result.outcome is None and result.admission is None
    async with create_read_only_session_manager(rdb_engine)() as session:
        counts = await _counts(session, fixture.request.locator.connection_id)
        assert counts[1:] == (0, 0, 0)


async def test_native_read_snapshots_and_replay_close_before_external_processing(
    rdb_engine: AsyncEngine,
    latest_db_schema: None,
) -> None:
    """Real RO/RW transactions complete before credential/provider/job collaborators."""
    fixture = await _fixture(rdb_engine, label="wt9-admission-completion")
    base_read = create_read_only_session_manager(rdb_engine)
    base_write = create_read_write_session_manager(rdb_engine)
    active = 0
    read_count = 0
    write_count = 0

    @asynccontextmanager
    async def read_scope() -> AsyncIterator[ReadSession]:
        nonlocal active, read_count
        async with base_read() as session:
            active += 1
            read_count += 1
            assert (
                await session.read_session.scalar(sa.text("SHOW transaction_read_only"))
                == "on"
            )
            try:
                yield session
            finally:
                active -= 1
        assert not session.read_session.in_transaction()

    @asynccontextmanager
    async def write_scope() -> AsyncIterator[WriteSession]:
        nonlocal active, write_count
        async with base_write() as session:
            active += 1
            write_count += 1
            try:
                yield session
            finally:
                active -= 1
        assert not session.write_session.in_transaction()

    reader: SessionManager[ReadSession] = read_scope
    writer: SessionManager[WriteSession] = write_scope
    repository = ExternalChannelRepository()
    http = ExternalChannelHTTPAdmissionReadRepository(
        session_manager=reader, repository=repository
    )
    history = ExternalChannelHistoryReadRepository(
        session_manager=reader, repository=repository
    )
    transport = ExternalChannelTransportReadRepository(
        session_manager=reader, repository=repository
    )
    configuration = await http.get_slack_configuration(
        provider_app_id="wt9-admission-completion-app",
        provider_tenant_id=fixture.request.locator.provider_tenant_id,
    )
    assert configuration is not None and active == 0
    assert (
        await history.get_configuration(connection_id=configuration.id)
    ) == configuration
    assert active == 0
    assert (
        await transport.get_discord_resource(
            connection_id=configuration.id,
            guild_id="unused",
            thread_id=None,
            message_id="missing",
        )
        is None
    )
    assert (
        await transport.get_owned_discord_configuration(
            connection_id=configuration.id,
            lease_owner="missing",
            lease_generation=1,
            now=datetime.datetime.now(datetime.UTC),
        )
        is None
    )
    assert active == 0

    class _Handle:
        async def wait(self) -> JobOutcome:
            raise AssertionError("Admission must not wait for job completion")

    class _Runtime:
        requests: list[JobRequest]

        def __init__(self) -> None:
            self.requests = []

        @property
        def active_count(self) -> int:
            return 0

        @property
        def shutdown_drain_seconds(self) -> float | None:
            return None

        async def submit(self, request: JobRequest) -> JobHandle:
            assert active == 0
            async with base_read() as session:
                assert await _counts(session, configuration.id) == (1, 1, 1, 1)
            self.requests.append(request)
            return _Handle()

    runtime = _Runtime()
    service = ExternalChannelIngressAdmissionService(
        operations=replace(fixture.operations, session_manager=writer),
        job_runtime=runtime,
    )
    outcome = await service.admit_current_trigger(
        provider_event_id="committed", request=fixture.request
    )
    assert (
        outcome is not None
        and outcome.kind is ExternalChannelIngestionOutcomeKind.ACCEPTED
    )
    assert len(runtime.requests) == 1
    assert active == 0

    committed = await fixture.operations.admit_current_trigger(
        provider_event_id="committed",
        request=fixture.request,
        now=datetime.datetime.now(datetime.UTC),
    )
    assert committed.admission is not None
    item = committed.admission.item
    async with base_write() as session:
        access = await repository.create_access_request_idempotent(
            session,
            ExternalChannelAccessRequestCreate(
                route_id=fixture.route_id,
                source_resource_id=item.source_resource_id,
                resource_id=item.source_resource_id,
                trigger_provider_message_key=item.trigger_provider_message_key,
                principal_id=item.principal_id,
                agent_session_id=None,
                setup_claim_id=None,
                status=ExternalChannelAccessRequestStatus.ALLOWED,
                decision_policy_snapshot={},
                decided_by_user_id=None,
                decision_summary=None,
                decided_at=None,
                control_provider_message_key=None,
                control_projection_status=None,
                expires_at=datetime.datetime.now(datetime.UTC)
                + datetime.timedelta(days=1),
                connection_id=configuration.id,
                conversation_position_id=item.conversation_position_id,
                range_start_position=None,
                trigger_position=item.trigger_position,
            ),
        )
    replay_operations = ExternalChannelReplayOperations(
        read_session_manager=reader,
        write_session_manager=writer,
        repository=repository,
    )
    ingest = MagicMock(spec=ExternalChannelConversationIngestionService)

    async def ingest_after_read(
        request: ExternalChannelIngestionRequest,
    ) -> ExternalChannelIngestionOutcome:
        assert active == 0
        assert request is not None
        return outcome

    ingest.ingest = AsyncMock(side_effect=ingest_after_read)
    replay = ExternalChannelIngestionReplayService(
        operations=replay_operations,
        ingestion_service=require_instance(
            ingest, ExternalChannelConversationIngestionService
        ),
    )
    replayed = await replay.replay_access_allow(
        access_request_id=access.id,
        deadline=fixture.request.deadline,
        initial_title_eligible=False,
    )
    assert replayed is outcome and active == 0
    ingest.ingest.assert_awaited_once()
    assert await replay_operations.list_selected_setup_claim_ids(limit=10) == ()
    with pytest.raises(ExternalChannelIngestionReplayUnavailable):
        await replay_operations.read_setup_claim(setup_claim_id="f" * 32)
    with pytest.raises(ExternalChannelIngestionReplayUnavailable):
        await replay_operations.read_selected_interaction(
            selector_interaction_id="f" * 32,
            principal_id=item.principal_id,
        )
    assert active == 0 and read_count >= 7 and write_count == 2
