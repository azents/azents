"""Exact Session critical commit fencing, without generic root/Agent read gates."""

import asyncio
import dataclasses
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import NamedTuple
from uuid import uuid4

import pytest
import pytest_asyncio
import sqlalchemy as sa
from azcommon.result import Success
from psycopg.errors import LockNotAvailable
from sqlalchemy import event
from sqlalchemy.engine import ExceptionContext
from sqlalchemy.ext.asyncio import AsyncEngine

from azents.core.agent_session_data import (
    AgentSession,
    AgentSessionCreate,
    SessionAgent,
)
from azents.core.chat_write_data import AcceptedStopRequest
from azents.core.enums import (
    AgentRunStatus,
    AgentSessionProductMode,
    AgentSessionStatus,
    EventKind,
    WorkspaceUserRole,
)
from azents.core.session_resource_authority import SessionExecutionOwner
from azents.engine.events.types import SystemErrorPayload
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.agent_runtime import RDBAgentRuntime
from azents.rdb.models.agent_session import RDBAgentSession
from azents.rdb.models.llm_provider_integration import RDBLLMProviderIntegration
from azents.rdb.models.session_agent import RDBSessionAgent
from azents.rdb.models.session_agent_context import RDBSessionAgentContext
from azents.rdb.models.workspace import RDBWorkspace
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import (
    ReadSession,
    WriteSession,
    create_read_only_session_manager,
    create_read_write_session_manager,
)
from azents.repos.agent_execution import AgentRunRepository, EventTranscriptRepository
from azents.repos.agent_execution.data import AgentRunCreate, EventCreate
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.agent_session.repository_test import _create_agent, _create_workspace
from azents.repos.engine_model_input_operation import (
    EngineModelInputOperationRepository,
)
from azents.repos.engine_tool_result_operation import (
    EngineToolResultOperationRepository,
)
from azents.repos.session_execution import CanonicalExecutionOwnerGenerationStaleError
from azents.repos.session_execution.ownership import (
    fence_owned_session_mutation,
    validate_session_execution_owner,
)
from azents.repos.terminal_finalization_data import (
    TerminalDeliveryDisposition,
    TerminalFinalizationOutcome,
)
from azents.repos.user import UserRepository
from azents.repos.user.data import UserCreate
from azents.repos.worker_session_test import worker_repository
from azents.repos.workspace_user import WorkspaceUserRepository
from azents.repos.workspace_user.data import WorkspaceUserCreate
from azents.services.chat_write_test import _service as chat_write_service


class _OwnerFixture(NamedTuple):
    workspace_id: str
    agent_id: str
    session_id: str
    root_id: str
    generation: int


@dataclasses.dataclass(frozen=True)
class _SessionHeadRepository:
    """Use real Session data through the head protocol's parameter identity."""

    sessions: AgentSessionRepository

    async def get_by_id(
        self, session: ReadSession, session_id: str
    ) -> AgentSession | None:
        return await self.sessions.get_by_id(session, session_id)


@pytest_asyncio.fixture
async def owned_session(
    rdb_engine: AsyncEngine, latest_db_schema: None
) -> AsyncIterator[_OwnerFixture]:
    writes = create_read_write_session_manager(rdb_engine)
    sessions = AgentSessionRepository()
    suffix = uuid4().hex[:8]
    async with writes() as setup:
        workspace = await _create_workspace(setup, f"narrow-owner-{suffix}")
        agent = await _create_agent(setup, workspace, f"narrow-owner-{suffix}")
        current = await sessions.create(
            setup,
            AgentSessionCreate(
                workspace_id=workspace,
                product_mode=AgentSessionProductMode.TEAM,
                associated_user_id=None,
                agent_id=agent,
                title=None,
            ),
        )
        generation = await sessions.claim_owner_generation(setup, current.id)
        root = await sessions.get_session_agent_by_session_id(setup, current.id)
        assert root is not None
    try:
        yield _OwnerFixture(
            workspace, agent, current.id, root.root_session_agent_id, generation
        )
    finally:
        async with writes() as cleanup:
            await cleanup.write_session.execute(
                sa.update(RDBSessionAgentContext)
                .where(RDBSessionAgentContext.agent_id == agent)
                .values(root_session_agent_id=None)
            )
            await cleanup.write_session.execute(
                sa.delete(RDBSessionAgent).where(
                    RDBSessionAgent.context_id.in_(
                        sa.select(RDBSessionAgentContext.id).where(
                            RDBSessionAgentContext.agent_id == agent
                        )
                    )
                )
            )
            await cleanup.write_session.execute(
                sa.delete(RDBAgentSession).where(RDBAgentSession.agent_id == agent)
            )
            await cleanup.write_session.execute(
                sa.delete(RDBSessionAgentContext).where(
                    RDBSessionAgentContext.agent_id == agent
                )
            )
            await cleanup.write_session.execute(
                sa.delete(RDBAgentRuntime).where(RDBAgentRuntime.agent_id == agent)
            )
            await cleanup.write_session.execute(
                sa.delete(RDBAgent).where(RDBAgent.id == agent)
            )
            await cleanup.write_session.execute(
                sa.delete(RDBLLMProviderIntegration).where(
                    RDBLLMProviderIntegration.workspace_id == workspace
                )
            )
            await cleanup.write_session.execute(
                sa.delete(RDBWorkspace).where(RDBWorkspace.id == workspace)
            )


async def test_old_owner_cannot_write_any_member_after_handover(
    rdb_engine: AsyncEngine, owned_session: _OwnerFixture
) -> None:
    writes = create_read_write_session_manager(rdb_engine)
    reads = create_read_only_session_manager(rdb_engine)
    fixture = owned_session
    owner = SessionExecutionOwner(fixture.session_id, fixture.generation)
    async with writes() as takeover:
        generation = await AgentSessionRepository().claim_owner_generation(
            takeover, fixture.session_id
        )
    assert generation == owner.owner_generation + 1
    event_id = f"obsolete-output:{uuid4().hex}"
    with pytest.raises(CanonicalExecutionOwnerGenerationStaleError):
        async with writes() as old:
            # Entire dependent group follows one actual Session mutation fence.
            await fence_owned_session_mutation(old, owner)
            await EventTranscriptRepository().append(
                old,
                EventCreate(
                    session_id=fixture.session_id,
                    kind=EventKind.SYSTEM_ERROR,
                    external_id=event_id,
                    payload=SystemErrorPayload(
                        content="Old result", severity="error", recoverable=True
                    ).model_dump(mode="json"),
                ),
            )
    async with reads() as reader:
        assert (
            await EventTranscriptRepository().get_by_external_id(
                reader, fixture.session_id, event_id
            )
            is None
        )
        current = await validate_session_execution_owner(
            reader, SessionExecutionOwner(fixture.session_id, generation)
        )
        assert current.owner_generation == generation
    with pytest.raises(CanonicalExecutionOwnerGenerationStaleError):
        async with reads() as reader:
            await validate_session_execution_owner(reader, owner)


async def test_critical_group_retains_exact_session_fence_until_commit(
    rdb_engine: AsyncEngine, owned_session: _OwnerFixture
) -> None:
    writes = create_read_write_session_manager(rdb_engine)
    reads = create_read_only_session_manager(rdb_engine)
    fixture = owned_session
    owner = SessionExecutionOwner(fixture.session_id, fixture.generation)
    started = asyncio.Event()
    application = f"owner-claim-{uuid4().hex[:8]}"

    async def claim() -> int:
        async with writes() as claimant:
            await claimant.write_session.execute(
                sa.text("SELECT set_config('application_name', :name, true)"),
                {"name": application},
            )
            started.set()
            return await AgentSessionRepository().claim_owner_generation(
                claimant, fixture.session_id
            )

    task: asyncio.Task[int] | None = None
    try:
        async with writes() as mutation:
            await fence_owned_session_mutation(mutation, owner)
            task = asyncio.create_task(claim())
            await started.wait()
            async with asyncio.timeout(5):
                while True:
                    async with reads() as observer:
                        blocked = await observer.read_session.scalar(
                            sa.text("""
                            SELECT EXISTS(SELECT 1 FROM pg_stat_activity
                            WHERE application_name=:name AND wait_event_type='Lock'
                            AND query LIKE 'UPDATE agent_sessions%')
                        """),
                            {"name": application},
                        )
                    if blocked:
                        break
            await EventTranscriptRepository().append(
                mutation,
                EventCreate(
                    session_id=fixture.session_id,
                    kind=EventKind.SYSTEM_ERROR,
                    external_id="current-critical-output",
                    payload=SystemErrorPayload(
                        content="Current result", severity="error", recoverable=True
                    ).model_dump(mode="json"),
                ),
            )
        async with asyncio.timeout(5):
            assert await task == fixture.generation + 1
        async with reads() as reader:
            assert (
                await EventTranscriptRepository().get_by_external_id(
                    reader, fixture.session_id, "current-critical-output"
                )
                is not None
            )
    finally:
        if task is not None and not task.done():
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task


@pytest.mark.parametrize("held", ["agent", "root"], ids=["agent-parent", "root-tree"])
async def test_owner_description_and_claim_ignore_unrelated_parent_locks(
    rdb_engine: AsyncEngine, owned_session: _OwnerFixture, held: str
) -> None:
    writes = create_read_write_session_manager(rdb_engine)
    reads = create_read_only_session_manager(rdb_engine)
    fixture = owned_session
    async with writes() as unrelated:
        model = RDBAgent if held == "agent" else RDBSessionAgent
        identity = fixture.agent_id if held == "agent" else fixture.root_id
        await unrelated.write_session.execute(
            sa.select(model).where(model.id == identity).with_for_update()
        )
        async with asyncio.timeout(5):
            async with reads() as reader:
                current = await validate_session_execution_owner(
                    reader,
                    SessionExecutionOwner(fixture.session_id, fixture.generation),
                )
                assert current.id == fixture.session_id
            async with writes() as claimant:
                generation = await AgentSessionRepository().claim_owner_generation(
                    claimant, fixture.session_id
                )
                assert generation == fixture.generation + 1


async def test_mutation_fence_preserves_session_metadata_timestamp(
    rdb_engine: AsyncEngine, owned_session: _OwnerFixture
) -> None:
    writes = create_read_write_session_manager(rdb_engine)
    async with writes() as mutation:
        before = await AgentSessionRepository().get_by_id(
            mutation, owned_session.session_id
        )
        assert before is not None
        fenced = await fence_owned_session_mutation(
            mutation,
            SessionExecutionOwner(owned_session.session_id, owned_session.generation),
        )
        assert fenced.updated_at == before.updated_at


@pytest.mark.parametrize("operation", ["prepare", "recover"])
async def test_input_and_running_recovery_ignore_held_session_writer(
    rdb_engine: AsyncEngine, owned_session: _OwnerFixture, operation: str
) -> None:
    writes = create_read_write_session_manager(rdb_engine)
    runs = AgentRunRepository()
    transcript = EventTranscriptRepository()
    owner = SessionExecutionOwner(owned_session.session_id, owned_session.generation)
    async with writes() as setup:
        run = await runs.create(
            setup,
            AgentRunCreate(
                session_id=owner.session_id,
                parent_agent_run_id=None,
                scheduled_task_cycle_id=None,
            ),
        )
    async with writes() as held:
        await held.write_session.execute(
            sa.select(RDBAgentSession)
            .where(RDBAgentSession.id == owner.session_id)
            .with_for_update()
        )
        async with asyncio.timeout(5):
            if operation == "recover":
                recovered = await worker_repository(writes).claim_recoverable_agent_run(
                    owner.session_id, owner_generation=owner.owner_generation
                )
                assert recovered is not None and recovered.id == run.id
            else:
                repository = EngineModelInputOperationRepository(
                    owner=owner,
                    session_manager=writes,
                    run_repository=runs,
                    transcript_repository=transcript,
                    session_head_repository=_SessionHeadRepository(
                        AgentSessionRepository()
                    ),
                    tool_result_repository=EngineToolResultOperationRepository(
                        owner=owner,
                        session_manager=writes,
                        run_repository=runs,
                        transcript_repository=transcript,
                    ),
                    input_projection_repository=None,
                )
                prepared = await repository.prepare_input(
                    run_id=run.id,
                    session_id=owner.session_id,
                    owner_generation=owner.owner_generation,
                )
                assert prepared.transcript == [] and prepared.repaired_events == []


async def test_missing_owner_is_not_a_mutation_scope(rdb_engine: AsyncEngine) -> None:
    async with create_read_write_session_manager(rdb_engine)() as session:
        with pytest.raises(ValueError, match="AgentSession not found"):
            await fence_owned_session_mutation(
                session, SessionExecutionOwner("0" * 32, 1)
            )


async def test_competing_terminal_deliveries_commit_one_mailbox_and_disposition(
    rdb_engine: AsyncEngine, owned_session: _OwnerFixture
) -> None:
    writes = create_read_write_session_manager(rdb_engine)
    reads = create_read_only_session_manager(rdb_engine)
    runs = AgentRunRepository()
    async with writes() as setup:
        child = await AgentSessionRepository().create_child_session_agent(
            setup,
            parent_session_agent_id=owned_session.root_id,
            name="terminal-child",
            agent_type="default",
            title=None,
            last_task_message=None,
        )
        run = await runs.create(
            setup,
            AgentRunCreate(
                session_id=child.agent_session_id,
                parent_agent_run_id=None,
                scheduled_task_cycle_id=None,
            ),
        )
        await runs.mark_terminal(
            setup, run.id, AgentRunStatus.COMPLETED, ended_at=run.created_at
        )
    prefix = f"terminal-delivery-{uuid4().hex[:8]}"

    def named_manager(name: str) -> SessionManager[WriteSession]:
        @asynccontextmanager
        async def manager() -> AsyncIterator[WriteSession]:
            async with writes() as session:
                await session.write_session.execute(
                    sa.text("SELECT set_config('application_name', :name, true)"),
                    {"name": name},
                )
                yield session

        return manager

    terminal = worker_repository(writes).terminal_finalization_repository
    tasks: list[asyncio.Task[TerminalFinalizationOutcome]] = []
    try:
        async with writes() as held:
            await runs.lock_by_id(held, run.id)
            tasks = [
                asyncio.create_task(
                    dataclasses.replace(
                        terminal, session_manager=named_manager(f"{prefix}-{index}")
                    ).finalize_run(run.id)
                )
                for index in range(2)
            ]
            async with asyncio.timeout(5):
                while True:
                    async with reads() as observer:
                        blocked = await observer.read_session.scalar(
                            sa.text("""
                                SELECT count(*) FROM pg_stat_activity
                                WHERE application_name LIKE :prefix
                                  AND wait_event_type='Lock'
                            """),
                            {"prefix": f"{prefix}%"},
                        )
                    if blocked == 2:
                        break
        async with asyncio.timeout(5):
            results = await asyncio.gather(*tasks)
        assert {result.disposition for result in results} == {
            TerminalDeliveryDisposition.ENQUEUED,
            TerminalDeliveryDisposition.ALREADY_FINALIZED,
        }
        assert results[0].mailbox_item_id == results[1].mailbox_item_id
        assert results[0].mailbox_item_id is not None
        async with reads() as observer:
            current = await runs.get_by_id(observer, run.id)
            assert current is not None
            assert current.parent_result_mailbox_item_id == results[0].mailbox_item_id
            mailbox = worker_repository(writes).mailbox_item_repository
            items = await mailbox.list_by_session_id(observer, owned_session.session_id)
            assert len(items) == 1 and items[0].id == results[0].mailbox_item_id
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


async def test_parent_archive_before_terminal_admission_commits_suppression(
    rdb_engine: AsyncEngine, owned_session: _OwnerFixture
) -> None:
    writes = create_read_write_session_manager(rdb_engine)
    reads = create_read_only_session_manager(rdb_engine)
    runs = AgentRunRepository()
    async with writes() as setup:
        child = await AgentSessionRepository().create_child_session_agent(
            setup,
            parent_session_agent_id=owned_session.root_id,
            name="archived-parent-child",
            agent_type="default",
            title=None,
            last_task_message=None,
        )
        run = await runs.create(
            setup,
            AgentRunCreate(
                session_id=child.agent_session_id,
                parent_agent_run_id=None,
                scheduled_task_cycle_id=None,
            ),
        )
        await runs.mark_terminal(
            setup, run.id, AgentRunStatus.COMPLETED, ended_at=run.created_at
        )
    observed_parent = asyncio.Event()
    release = asyncio.Event()

    class ObservedSessions(AgentSessionRepository):
        async def get_session_agent_by_id(
            self, session: ReadSession, session_agent_id: str
        ) -> SessionAgent | None:
            parent = await super().get_session_agent_by_id(session, session_agent_id)
            if session_agent_id == owned_session.root_id:
                observed_parent.set()
                await release.wait()
            return parent

    terminal = dataclasses.replace(
        worker_repository(writes).terminal_finalization_repository,
        agent_session_repository=ObservedSessions(),
    )
    task = asyncio.create_task(terminal.finalize_run(run.id))
    try:
        async with asyncio.timeout(5):
            await observed_parent.wait()
            async with writes() as archiver:
                await archiver.write_session.execute(
                    sa.update(RDBAgentSession)
                    .where(RDBAgentSession.id == owned_session.session_id)
                    .values(status=AgentSessionStatus.ARCHIVED)
                )
            release.set()
            result = await task
        assert result.disposition is TerminalDeliveryDisposition.SUPPRESSED
        async with reads() as observer:
            current = await runs.get_by_id(observer, run.id)
            assert current is not None
            assert current.parent_result_mailbox_item_id is None
            assert current.parent_result_delivery_state is not None
            assert current.parent_result_delivery_state.value == "suppressed"
            assert not await worker_repository(
                writes
            ).mailbox_item_repository.list_by_session_id(
                observer, owned_session.session_id
            )
    finally:
        release.set()
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def test_public_stop_releases_all_partial_rows_for_child_terminal_delivery(
    rdb_engine: AsyncEngine, owned_session: _OwnerFixture
) -> None:
    """Actual public Stop cannot retain a parent while retrying a child writer."""
    writes = create_read_write_session_manager(rdb_engine)
    reads = create_read_only_session_manager(rdb_engine)
    users = UserRepository()
    runs = AgentRunRepository()
    async with writes() as setup:
        user = await users.create(
            setup, UserCreate(email=f"chat-stop-{uuid4().hex}@example.com")
        )
        membership = await WorkspaceUserRepository().create(
            setup,
            WorkspaceUserCreate(
                workspace_id=owned_session.workspace_id,
                user_id=user.id,
                name="Stop requester",
                role=WorkspaceUserRole.OWNER,
            ),
        )
        assert isinstance(membership, Success)
        child = await AgentSessionRepository().create_child_session_agent(
            setup,
            parent_session_agent_id=owned_session.root_id,
            name="stop-terminal-child",
            agent_type="default",
            title=None,
            last_task_message=None,
        )
        run = await runs.create(
            setup,
            AgentRunCreate(
                session_id=child.agent_session_id,
                parent_agent_run_id=None,
                scheduled_task_cycle_id=None,
            ),
        )
        for session_id in (owned_session.session_id, child.agent_session_id):
            await AgentSessionRepository().mark_running(setup, session_id)
    collision = asyncio.Event()

    def observe_collision(context: ExceptionContext) -> None:
        if isinstance(context.original_exception, LockNotAvailable):
            collision.set()

    @asynccontextmanager
    async def stop_manager() -> AsyncIterator[WriteSession]:
        async with writes() as scope:
            connection = await scope.write_session.connection()
            sync_connection = connection.sync_connection
            assert sync_connection is not None
            event.listen(sync_connection.engine, "handle_error", observe_collision)
            try:
                yield scope
            finally:
                event.remove(sync_connection.engine, "handle_error", observe_collision)

    terminal = worker_repository(writes).terminal_finalization_repository
    stop = chat_write_service(
        stop_manager, workspace_user_repository=WorkspaceUserRepository()
    )
    task: asyncio.Task[AcceptedStopRequest] | None = None
    try:
        async with writes() as child_scope:
            await fence_owned_session_mutation(
                child_scope, SessionExecutionOwner(child.agent_session_id, 0)
            )
            await runs.mark_terminal(
                child_scope,
                run.id,
                AgentRunStatus.COMPLETED,
                ended_at=run.created_at,
                terminal_result_message="Child result before Stop.",
            )
            task = asyncio.create_task(
                stop.request_session_stop(
                    agent_id=owned_session.agent_id,
                    session_id=owned_session.session_id,
                    user_id=user.id,
                )
            )
            try:
                async with asyncio.timeout(5):
                    await collision.wait()
            except TimeoutError:
                if task.done():
                    await task
                raise
            async with asyncio.timeout(5):
                outcome = await terminal.finalize_run_in_session(
                    child_scope, run_id=run.id
                )
            assert outcome.disposition is TerminalDeliveryDisposition.ENQUEUED
        async with asyncio.timeout(5):
            accepted = await task
        assert accepted.stopped_session_ids == [
            owned_session.session_id,
            child.agent_session_id,
        ]
        async with reads() as observer:
            root = await AgentSessionRepository().get_by_id(
                observer, owned_session.session_id
            )
            current_child = await AgentSessionRepository().get_by_id(
                observer, child.agent_session_id
            )
            assert root is not None and current_child is not None
            assert root.stop_requested_at is not None
            assert current_child.stop_requested_at is not None
            mailbox = await worker_repository(
                writes
            ).mailbox_item_repository.list_by_session_id(
                observer, owned_session.session_id
            )
            assert len(mailbox) == 1
        repeated = await terminal.finalize_run(run.id)
        assert repeated.disposition is TerminalDeliveryDisposition.ALREADY_FINALIZED
    finally:
        if task is not None and not task.done():
            task.cancel()
        if task is not None:
            await asyncio.gather(task, return_exceptions=True)
        async with writes() as cleanup:
            await users.delete(cleanup, user.id)
