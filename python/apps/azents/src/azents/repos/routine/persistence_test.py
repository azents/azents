"""Real PostgreSQL Routine ownership, exact updates and bounded record tests."""

import datetime

import pytest
import sqlalchemy as sa
from azcommon.result import Success
from azcommon.uuid import uuid7

from azents.core.agent_session_data import AgentSessionCreate
from azents.core.enums import (
    AgentSessionProductMode,
    AgentSessionStartReason,
    ExternalChannelAppMode,
    ExternalChannelConnectionStatus,
    ExternalChannelProvider,
    ExternalChannelResourceStatus,
    ExternalChannelResourceType,
    ExternalChannelResponseMode,
    ExternalChannelRouteCatalogStatus,
    ExternalChannelRouteMode,
    ExternalChannelTransport,
    LLMProvider,
)
from azents.core.routine import (
    ManualRoutineSource,
    RoutineContent,
    RoutineContentConflict,
    RoutineDeliveryStatus,
    RoutineLimitReached,
    RoutineObjectiveOutcome,
    RoutineScope,
    RoutineUnavailable,
    RoutineWorkResult,
)
from azents.core.session_resource_authority import SessionExecutionOwner
from azents.core.workspace import WorkspaceCreate
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.agent_session import RDBAgentSession
from azents.rdb.models.external_channel import (
    RDBExternalChannelAgentRoute,
    RDBExternalChannelBinding,
    RDBExternalChannelConnection,
    RDBExternalChannelResource,
)
from azents.rdb.models.llm_provider_integration import RDBLLMProviderIntegration
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import WriteSession
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.external_channel.data import ExternalChannelBindingCreate
from azents.repos.external_channel.repository import ExternalChannelRepository
from azents.repos.external_channel.work import terminate_binding_with_plans
from azents.repos.routine.definition import RoutineDefinitionRepository
from azents.repos.routine.operations import RoutineOperations
from azents.repos.routine.records import RoutineWorkRecordRepository
from azents.repos.session_execution import CanonicalExecutionOwnerGenerationStaleError
from azents.repos.session_primary_channel import (
    SessionPrimaryChannelAmbiguous,
    SessionPrimaryChannelRepository,
    SessionPrimaryChannelUnavailable,
)
from azents.repos.workspace import WorkspaceRepository
from azents.testing.model_selection import (
    make_test_model_selection_dict,
    make_test_selectable_model_option_dicts,
)


def _content() -> RoutineContent:
    return RoutineContent(
        title="Release news",
        objective="Check for official release announcements.",
        sources=(ManualRoutineSource(type="manual"),),
    )


def _operations(manager: SessionManager[WriteSession]) -> RoutineOperations:
    return RoutineOperations(
        session_manager=manager,
        read_session_manager=manager,
        definitions=RoutineDefinitionRepository(),
        records=RoutineWorkRecordRepository(),
    )


async def _subject(session: WriteSession) -> RoutineScope:
    """Seed a real authorized root without external provider or Runtime I/O."""
    handle = f"routine-{uuid7().hex}"
    workspaces = WorkspaceRepository()
    created = await workspaces.create(
        session, WorkspaceCreate(name="Routine persistence test", handle=handle)
    )
    assert isinstance(created, Success)
    workspace_id = await workspaces.resolve_id(session, handle)
    assert workspace_id is not None
    integration = RDBLLMProviderIntegration(
        workspace_id=workspace_id,
        provider=LLMProvider.ANTHROPIC,
        name="Routine test integration",
        encrypted_credentials="encrypted-test-value",
        config=None,
    )
    session.write_session.add(integration)
    await session.write_session.flush()
    model = make_test_model_selection_dict(
        integration_id=integration.id,
        provider=LLMProvider.ANTHROPIC,
        model_identifier="routine-test-model",
    )
    agent = RDBAgent(
        workspace_id=workspace_id,
        name="Routine test agent",
        routine_check_interval_minutes=30,
        routine_min_action_delay_minutes=30,
        model_selection=model,
        lightweight_model_selection=model,
        selectable_model_options=make_test_selectable_model_option_dicts(
            model_selection=model, lightweight_model_selection=model
        ),
        main_model_label="default",
        lightweight_model_label="lightweight",
    )
    session.write_session.add(agent)
    await session.write_session.flush()
    root = await AgentSessionRepository().create(
        session,
        AgentSessionCreate(
            workspace_id=workspace_id,
            agent_id=agent.id,
            product_mode=AgentSessionProductMode.TEAM,
            associated_user_id=None,
            title=None,
        ),
    )
    return RoutineScope(
        workspace_id=workspace_id, agent_id=agent.id, session_id=root.id
    )


async def test_definition_exact_update_preserves_other_content(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    async with rdb_session_manager() as session:
        scope = await _subject(session)
    operations = _operations(rdb_session_manager)
    created = await operations.create(scope=scope, content=_content(), owner=None)
    assert created.slug == "release-news"
    updated = await operations.update(
        scope=scope,
        slug=created.slug,
        expected=created.content,
        changes={"title": "Official launches"},
        owner=None,
    )
    assert updated.content.title == "Official launches"
    assert updated.content.objective == created.content.objective
    assert updated.content.sources == created.content.sources
    assert updated.id == created.id
    assert updated.slug == created.slug
    assert await operations.get(scope=scope, slug=created.slug) == updated


async def test_existing_stored_slug_remains_addressable_after_title_update(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    async with rdb_session_manager() as session:
        scope = await _subject(session)
    operations = _operations(rdb_session_manager)
    created = await operations.create(scope=scope, content=_content(), owner=None)
    stored_slug = f"routine-{uuid7().hex}"
    async with rdb_session_manager() as session:
        row = await operations.definitions.lock(session, scope=scope, slug=created.slug)
        row.slug = stored_slug
        await session.write_session.flush()
    existing = await operations.get(scope=scope, slug=stored_slug)
    assert existing is not None
    updated = await operations.update(
        scope=scope,
        slug=stored_slug,
        expected=existing.content,
        changes={"title": "Updated release news"},
        owner=None,
    )
    assert updated.slug == stored_slug
    assert updated.id == created.id


async def test_duplicate_slug_is_rejected_without_overwriting(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    async with rdb_session_manager() as session:
        scope = await _subject(session)
        other = await _subject(session)
    operations = _operations(rdb_session_manager)
    await operations.create(scope=scope, content=_content(), owner=None)
    with pytest.raises(
        ValueError, match="Routine slug 'release-news' already exists in this Session."
    ):
        await operations.create(scope=scope, content=_content(), owner=None)
    definitions = await operations.list_routines(scope=scope)
    assert len(definitions) == 1
    assert definitions[0].slug == "release-news"
    assert definitions[0].content == _content()
    separate = await operations.create(scope=other, content=_content(), owner=None)
    assert separate.slug == "release-news"
    assert separate.id != definitions[0].id


async def test_mismatched_prior_content_does_not_mutate_database(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    async with rdb_session_manager() as session:
        scope = await _subject(session)
    operations = _operations(rdb_session_manager)
    created = await operations.create(scope=scope, content=_content(), owner=None)
    wrong_prior = RoutineContent(
        title="Only the changed field was remembered",
        objective=created.content.objective,
        sources=created.content.sources,
    )
    with pytest.raises(RoutineContentConflict):
        await operations.update(
            scope=scope,
            slug=created.slug,
            expected=wrong_prior,
            changes={"objective": "Discard unrelated instructions."},
            owner=None,
        )
    assert await operations.get(scope=scope, slug=created.slug) == created


async def test_wrong_session_scope_cannot_read_or_modify_definition(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    async with rdb_session_manager() as session:
        scope = await _subject(session)
        other = await _subject(session)
    operations = _operations(rdb_session_manager)
    created = await operations.create(scope=scope, content=_content(), owner=None)
    assert await operations.get(scope=other, slug=created.slug) is None
    with pytest.raises(RoutineUnavailable):
        await operations.delete(scope=other, slug=created.slug, owner=None)
    invalid = RoutineScope(
        workspace_id=other.workspace_id,
        agent_id=scope.agent_id,
        session_id=scope.session_id,
    )
    with pytest.raises(RoutineUnavailable):
        await operations.list_routines(scope=invalid)
    assert await operations.get(scope=scope, slug=created.slug) == created


async def test_session_limit_does_not_create_twenty_first_definition(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    async with rdb_session_manager() as session:
        scope = await _subject(session)
    operations = _operations(rdb_session_manager)
    for index in range(20):
        content = _content().model_copy(update={"title": f"Release news {index}"})
        await operations.create(scope=scope, content=content, owner=None)
    with pytest.raises(RoutineLimitReached):
        await operations.create(scope=scope, content=_content(), owner=None)
    assert len(await operations.list_routines(scope=scope)) == 20


async def test_record_retention_and_duplicate_settlement(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    async with rdb_session_manager() as session:
        scope = await _subject(session)
    operations = _operations(rdb_session_manager)
    created = await operations.create(scope=scope, content=_content(), owner=None)
    records = RoutineWorkRecordRepository()
    started_at = datetime.datetime(2026, 10, 18, tzinfo=datetime.UTC)
    execution_ids: list[str] = []
    async with rdb_session_manager() as session:
        for index in range(101):
            execution_id = uuid7().hex
            execution_ids.append(execution_id)
            appended = await records.append(
                session,
                scope=scope,
                routine_id=created.id,
                execution_id=execution_id,
                started_at=started_at,
                work=RoutineWorkResult(
                    objective_outcome=RoutineObjectiveOutcome.FINISHED,
                    result=f"Observed official news item {index}.",
                    next_hint="Check for a later announcement.",
                    notify=False,
                    message=None,
                ),
            )
            assert appended.created
            assert appended.record is not None
            assert (
                appended.record.delivery_status is RoutineDeliveryStatus.NOT_REQUESTED
            )
        recent = await records.list_recent(
            session, scope=scope, routine_id=created.id, limit=100
        )
        assert len(recent) == 100
        assert [record.execution_id for record in recent] == execution_ids[:0:-1]
        duplicate = await records.append(
            session,
            scope=scope,
            routine_id=created.id,
            execution_id=execution_ids[-1],
            started_at=started_at,
            work=recent[0].work,
        )
        assert not duplicate.created
        assert duplicate.record == recent[0]
        latest = await records.list_recent(
            session, scope=scope, routine_id=created.id, limit=1
        )
        assert latest == [recent[0]]


async def test_deleted_definition_cannot_be_resurrected_by_late_record(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    async with rdb_session_manager() as session:
        scope = await _subject(session)
    operations = _operations(rdb_session_manager)
    created = await operations.create(scope=scope, content=_content(), owner=None)
    await operations.delete(scope=scope, slug=created.slug, owner=None)
    async with rdb_session_manager() as session:
        records = RoutineWorkRecordRepository()
        late = await records.append(
            session,
            scope=scope,
            routine_id=created.id,
            execution_id=uuid7().hex,
            started_at=datetime.datetime(2026, 10, 18, tzinfo=datetime.UTC),
            work=RoutineWorkResult(
                objective_outcome=RoutineObjectiveOutcome.FAILED,
                result="The upstream source was unavailable.",
                next_hint="Try again at a later eligible opportunity.",
                notify=False,
                message=None,
            ),
        )
        assert late.record is None
        assert not late.created
        assert (
            await records.list_recent(
                session, scope=scope, routine_id=created.id, limit=100
            )
            == []
        )
    assert await operations.list_routines(scope=scope) == []


async def _binding_values(
    session: WriteSession, scope: RoutineScope
) -> ExternalChannelBindingCreate:
    """Seed exact connected owners without provider I/O or selecting Primary."""
    connection = RDBExternalChannelConnection(
        workspace_id=scope.workspace_id,
        provider=ExternalChannelProvider.SLACK,
        transport=ExternalChannelTransport.HTTP,
        status=ExternalChannelConnectionStatus.ACTIVE,
        app_mode=ExternalChannelAppMode.SINGLE,
        encrypted_credentials="encrypted-test-value",
        provider_app_id=f"app-{uuid7().hex}",
        provider_tenant_id="test-tenant",
    )
    session.write_session.add(connection)
    await session.write_session.flush()
    route = RDBExternalChannelAgentRoute(
        connection_id=connection.id,
        agent_id=scope.agent_id,
        agent_id_snapshot=scope.agent_id,
        route_mode=ExternalChannelRouteMode.DEDICATED,
        connection_app_mode=ExternalChannelAppMode.SINGLE,
        catalog_status=ExternalChannelRouteCatalogStatus.AVAILABLE,
    )
    resource = RDBExternalChannelResource(
        connection_id=connection.id,
        resource_type=ExternalChannelResourceType.THREAD,
        provider_resource_key=f"thread-{uuid7().hex}",
        status=ExternalChannelResourceStatus.ACTIVE,
    )
    session.write_session.add_all([route, resource])
    await session.write_session.flush()
    return ExternalChannelBindingCreate(
        resource_id=resource.id,
        route_id=route.id,
        agent_session_id=scope.session_id,
        response_mode=ExternalChannelResponseMode.ALL_MESSAGES,
        disconnected_at=None,
        disconnect_reason=None,
    )


async def _legacy_binding(
    session: WriteSession, scope: RoutineScope
) -> RDBExternalChannelBinding:
    """Represent pre-migration data that has no Primary designation yet."""
    values = await _binding_values(session, scope)
    binding = RDBExternalChannelBinding(**values.model_dump())
    session.write_session.add(binding)
    await session.write_session.flush()
    return binding


async def test_channel_creation_designates_origin_idempotently(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    async with rdb_session_manager() as session:
        scope = await _subject(session)
        await session.write_session.execute(
            sa.update(RDBAgentSession)
            .where(RDBAgentSession.id == scope.session_id)
            .values(start_reason=AgentSessionStartReason.EXTERNAL_CHANNEL)
        )
        values = await _binding_values(session, scope)
        bindings = ExternalChannelRepository()
        created = await bindings.create_binding_idempotent(
            session, values, expected_access_request_id=None
        )
        primaries = SessionPrimaryChannelRepository()
        assert (
            await primaries.get_current(
                session,
                workspace_id=scope.workspace_id,
                agent_id=scope.agent_id,
                session_id=scope.session_id,
            )
            == created.id
        )
        repeated = await bindings.create_binding_idempotent(
            session, values, expected_access_request_id=None
        )
        assert repeated.id == created.id


async def test_primary_backfill_preserves_unambiguous_bindings(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    async with rdb_session_manager() as session:
        empty = await _subject(session)
        scope = await _subject(session)
        binding = await _legacy_binding(session, scope)
        primaries = SessionPrimaryChannelRepository()
        assert (
            await primaries.get_current(
                session,
                workspace_id=empty.workspace_id,
                agent_id=empty.agent_id,
                session_id=empty.session_id,
            )
            is None
        )
        applied = await primaries.backfill(session)
        assert len(applied) == 1
        assert applied[0].binding_id == binding.id
        assert applied[0].session_id == scope.session_id
        assert await session.write_session.get(RDBExternalChannelBinding, binding.id)
        assert await primaries.backfill(session) == ()


async def test_ambiguous_backfill_changes_no_primary_and_deletes_no_binding(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    async with rdb_session_manager() as session:
        one = await _subject(session)
        two = await _subject(session)
        bindings = [
            await _legacy_binding(session, one),
            await _legacy_binding(session, two),
            await _legacy_binding(session, two),
        ]
        primaries = SessionPrimaryChannelRepository()
        with pytest.raises(SessionPrimaryChannelAmbiguous):
            await primaries.backfill(session)
        for scope in (one, two):
            assert (
                await primaries.get_current(
                    session,
                    workspace_id=scope.workspace_id,
                    agent_id=scope.agent_id,
                    session_id=scope.session_id,
                )
                is None
            )
        for binding in bindings:
            assert (
                await session.write_session.get(RDBExternalChannelBinding, binding.id)
                is not None
            )


async def test_disconnected_primary_is_not_silently_a_web_destination(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    async with rdb_session_manager() as session:
        scope = await _subject(session)
        binding = await _legacy_binding(session, scope)
        primaries = SessionPrimaryChannelRepository()
        await primaries.backfill(session)
        binding.disconnected_at = datetime.datetime.now(datetime.UTC)
        await session.write_session.flush()
        with pytest.raises(SessionPrimaryChannelUnavailable):
            await primaries.get_current(
                session,
                workspace_id=scope.workspace_id,
                agent_id=scope.agent_id,
                session_id=scope.session_id,
            )
        await primaries.clear_for_binding(
            session, session_id=scope.session_id, binding_id=binding.id
        )
        assert (
            await primaries.get_current(
                session,
                workspace_id=scope.workspace_id,
                agent_id=scope.agent_id,
                session_id=scope.session_id,
            )
            is None
        )


async def test_foreign_primary_reference_never_grants_delivery_authority(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    async with rdb_session_manager() as session:
        scope = await _subject(session)
        other = await _subject(session)
        foreign = await _legacy_binding(session, other)
        await session.write_session.execute(
            sa.update(RDBAgentSession)
            .where(RDBAgentSession.id == scope.session_id)
            .values(primary_channel_binding_id=foreign.id)
        )
        with pytest.raises(SessionPrimaryChannelUnavailable):
            await SessionPrimaryChannelRepository().get_current(
                session,
                workspace_id=scope.workspace_id,
                agent_id=scope.agent_id,
                session_id=scope.session_id,
            )


async def test_binding_deletion_clears_primary_without_deleting_session(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    async with rdb_session_manager() as session:
        scope = await _subject(session)
        binding = await _legacy_binding(session, scope)
        primaries = SessionPrimaryChannelRepository()
        await primaries.backfill(session)
        await session.write_session.delete(binding)
        await session.write_session.flush()
        assert (
            await primaries.get_current(
                session,
                workspace_id=scope.workspace_id,
                agent_id=scope.agent_id,
                session_id=scope.session_id,
            )
            is None
        )
        assert await session.write_session.get(RDBAgentSession, scope.session_id)


async def test_stale_execution_owner_cannot_register_routine(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    async with rdb_session_manager() as session:
        scope = await _subject(session)
        generation = await session.write_session.scalar(
            sa.select(RDBAgentSession.owner_generation).where(
                RDBAgentSession.id == scope.session_id
            )
        )
        assert generation is not None
    operations = _operations(rdb_session_manager)
    with pytest.raises(CanonicalExecutionOwnerGenerationStaleError):
        await operations.create(
            scope=scope,
            content=_content(),
            owner=SessionExecutionOwner(scope.session_id, generation + 1),
        )
    assert await operations.list_routines(scope=scope) == []
    await operations.create(
        scope=scope,
        content=_content(),
        owner=SessionExecutionOwner(scope.session_id, generation),
    )
    assert len(await operations.list_routines(scope=scope)) == 1


async def test_binding_termination_clears_primary_in_existing_owner_operation(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    async with rdb_session_manager() as session:
        scope = await _subject(session)
        binding = await _legacy_binding(session, scope)
        primaries = SessionPrimaryChannelRepository()
        await primaries.backfill(session)
        resource = await session.write_session.get(
            RDBExternalChannelResource, binding.resource_id
        )
        assert resource is not None
        repository = ExternalChannelRepository()
        await terminate_binding_with_plans(
            session,
            binding=binding,
            resource=resource,
            work_state_store=repository.work_state_store,
            scheduled_task_lifecycle_repository=(
                repository.scheduled_task_lifecycle_repository
            ),
            now=datetime.datetime.now(datetime.UTC),
            reason="test_binding_disconnected",
            emit_leave_presence=False,
        )
        assert binding.disconnected_at is not None
        assert (
            await primaries.get_current(
                session,
                workspace_id=scope.workspace_id,
                agent_id=scope.agent_id,
                session_id=scope.session_id,
            )
            is None
        )


async def test_primary_does_not_impose_one_binding_per_session(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    async with rdb_session_manager() as session:
        scope = await _subject(session)
        first = await _legacy_binding(session, scope)
        primaries = SessionPrimaryChannelRepository()
        await primaries.backfill(session)
        second = await _legacy_binding(session, scope)
        assert first.id != second.id
        assert (
            await primaries.get_current(
                session,
                workspace_id=scope.workspace_id,
                agent_id=scope.agent_id,
                session_id=scope.session_id,
            )
            == first.id
        )
        assert await primaries.backfill(session) == ()


async def test_notification_observation_is_not_a_retry_queue(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    async with rdb_session_manager() as session:
        scope = await _subject(session)
    created = await _operations(rdb_session_manager).create(
        scope=scope, content=_content(), owner=None
    )
    async with rdb_session_manager() as session:
        records = RoutineWorkRecordRepository()
        appended = await records.append(
            session,
            scope=scope,
            routine_id=created.id,
            execution_id=uuid7().hex,
            started_at=datetime.datetime.now(datetime.UTC),
            work=RoutineWorkResult(
                objective_outcome=RoutineObjectiveOutcome.FINISHED,
                result="An official announcement was confirmed.",
                next_hint="Watch for revisions.",
                notify=True,
                message="The release date has been officially confirmed.",
            ),
        )
        assert appended.record is not None
        assert appended.record.delivery_status is RoutineDeliveryStatus.UNOBSERVED
        assert await records.observe_delivery(
            session,
            scope=scope,
            record_id=appended.record.id,
            status=RoutineDeliveryStatus.FAILED,
            error="Provider rejected the request.",
        )
        assert not await records.observe_delivery(
            session,
            scope=scope,
            record_id=appended.record.id,
            status=RoutineDeliveryStatus.DELIVERED,
            error=None,
        )
        latest = await records.list_recent(
            session, scope=scope, routine_id=created.id, limit=1
        )
        assert latest[0].work.objective_outcome is RoutineObjectiveOutcome.FINISHED
        assert latest[0].delivery_status is RoutineDeliveryStatus.FAILED


async def test_primary_rejects_connection_from_another_workspace(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    async with rdb_session_manager() as session:
        scope = await _subject(session)
        other = await _subject(session)
        binding = await _legacy_binding(session, scope)
        primaries = SessionPrimaryChannelRepository()
        await primaries.backfill(session)
        resource = await session.write_session.get(
            RDBExternalChannelResource, binding.resource_id
        )
        assert resource is not None
        await session.write_session.execute(
            sa.update(RDBExternalChannelConnection)
            .where(RDBExternalChannelConnection.id == resource.connection_id)
            .values(workspace_id=other.workspace_id)
        )
        with pytest.raises(SessionPrimaryChannelUnavailable):
            await primaries.get_current(
                session,
                workspace_id=scope.workspace_id,
                agent_id=scope.agent_id,
                session_id=scope.session_id,
            )
