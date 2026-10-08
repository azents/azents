"""PostgreSQL transaction, owner CAS and external-boundary worktree tests."""

import asyncio
import datetime
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import TypedDict
from unittest.mock import DEFAULT, AsyncMock
from uuid import uuid4

import pytest
import pytest_asyncio
import sqlalchemy as sa
from azcommon.result import Success
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from azents.core.action_execution_data import ActionExecution, ActionExecutionCreate
from azents.core.enums import (
    ActionExecutionEventKind,
    ActionExecutionStatus,
    EventKind,
    MailboxItemKind,
    SessionGitWorktreeBranchCreatedBy,
    SessionGitWorktreeStatus,
)
from azents.core.json_value import JSONValue
from azents.core.session_execution_data import SessionExecutionRecord
from azents.core.session_git_worktree_results import _cleanup_result
from azents.core.session_resource_authority import SessionExecutionOwner
from azents.engine.events.action_messages import (
    AgentCreateGitWorktreeAction,
    CreateGitWorktreeAction,
)
from azents.engine.events.types import Event
from azents.rdb.models.agent_session import RDBAgentSession
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import (
    ReadSession,
    WriteSession,
    create_read_only_session_manager,
    create_read_write_session_manager,
)
from azents.repos.action_execution import ActionExecutionRepository
from azents.repos.agent_execution import EventTranscriptRepository
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.mailbox import MailboxRepository
from azents.repos.session_execution import CanonicalExecutionOwnerGenerationStaleError
from azents.repos.session_git_worktree import operations as operations_module
from azents.repos.session_git_worktree.data import (
    SessionGitWorktree,
    SessionGitWorktreeCreate,
)
from azents.repos.session_git_worktree.operations import (
    SessionGitWorktreeOperationsRepository,
)
from azents.repos.session_working_folder_binding.data import (
    SessionWorkingFolderAuthority,
    SessionWorkingFolderBindingError,
    SessionWorkingFolderTarget,
)
from azents.repos.session_workspace_project import SessionWorkspaceProjectRepository
from azents.services.session_git_worktree.service_test import (
    _AgentCreateSessionFixture,
    _create_agent_worktree_session,
    _RunnerOperations,
)
from azents.testing.committed_fixture_cleanup import committed_fixture_graph


@pytest_asyncio.fixture
async def committed_fixture_metadata(
    rdb_engine: AsyncEngine, latest_db_schema: None
) -> sa.MetaData:
    """Reflect the actual FK graph once for this module's committed test seeds."""
    del latest_db_schema
    metadata = sa.MetaData()
    async with rdb_engine.connect() as connection:
        await connection.run_sync(metadata.reflect)
    return metadata


@pytest_asyncio.fixture(autouse=True)
async def cleanup_committed_fixture_graph(
    rdb_engine: AsyncEngine, committed_fixture_metadata: sa.MetaData
) -> AsyncGenerator[None, None]:
    """Always release only identities created by this committed evidence case."""
    async with committed_fixture_graph(rdb_engine, committed_fixture_metadata):
        yield


@dataclass
class WorktreeOperationsFixture:
    """Committed setup and separately observed native read/write operations."""

    scenario: _AgentCreateSessionFixture
    engine: AsyncEngine
    write_manager: SessionManager[WriteSession]
    read_manager: SessionManager[ReadSession]
    sessions: list[AsyncSession]

    @property
    def repository(self) -> SessionGitWorktreeOperationsRepository:
        return self.scenario.service.repository

    def assert_closed(self) -> None:
        """Check authoritative transaction state rather than lexical call order."""
        assert self.sessions
        assert all(not session.in_transaction() for session in self.sessions)

    async def execution(self, *, bridge: bool) -> ActionExecution:
        """Commit one new operation identity for deterministic repository tests."""
        scenario = self.scenario
        async with self.write_manager() as session:
            session_agent = (
                await AgentSessionRepository().get_session_agent_by_session_id(
                    session, scenario.session_id
                )
            )
            assert session_agent is not None
            project = await SessionWorkspaceProjectRepository().get_project_by_path(
                session,
                session_id=scenario.session_id,
                path=scenario.source_project_path,
            )
            assert project is not None
            action = (
                AgentCreateGitWorktreeAction(
                    bridge_identity=f"bridge-{uuid4().hex}",
                    originating_run_id=uuid4().hex,
                    client_tool_call_id="test-call",
                    session_agent_context_id=session_agent.context_id,
                    originating_agent_session_id=scenario.session_id,
                    source_project_id=project.id,
                    source_project_path=project.path,
                    starting_ref="main",
                    branch_name=None,
                )
                if bridge
                else CreateGitWorktreeAction(
                    source_project_path=scenario.source_project_path,
                    starting_ref="main",
                )
            )
            execution = await ActionExecutionRepository().create(
                session,
                ActionExecutionCreate(
                    id=None,
                    session_id=scenario.session_id,
                    mailbox_item_id=uuid4().hex,
                    sender_user_id=None,
                    action_type=action.type,
                    action=action.model_dump(mode="json"),
                    status=ActionExecutionStatus.PENDING,
                    owner_generation=scenario.owner_generation,
                ),
            )
        self.assert_closed()
        return execution


@pytest_asyncio.fixture
async def worktree_operations(
    rdb_engine: AsyncEngine, latest_db_schema: None
) -> AsyncGenerator[WorktreeOperationsFixture, None]:
    """Use committed fixture workflow and independent PostgreSQL production scopes."""
    del latest_db_schema
    write = create_read_write_session_manager(rdb_engine)
    read = create_read_only_session_manager(rdb_engine)
    sessions: list[AsyncSession] = []

    @asynccontextmanager
    async def observed_write() -> AsyncGenerator[WriteSession, None]:
        async with write() as session:
            sessions.append(session.write_session)
            yield session

    @asynccontextmanager
    async def observed_read() -> AsyncGenerator[ReadSession, None]:
        async with read() as session:
            sessions.append(session.read_session)
            yield session

    scenario = await _create_agent_worktree_session(
        observed_write,
        slug=f"ops-{uuid4().hex}",
        runner=_RunnerOperations(),
        include_skill_store=False,
    )
    repository = scenario.service.repository
    repository.read_session_manager = observed_read
    repository.binding_repository.read_session_manager = observed_read
    fixture = WorktreeOperationsFixture(
        scenario=scenario,
        engine=rdb_engine,
        write_manager=observed_write,
        read_manager=observed_read,
        sessions=sessions,
    )
    # Independent commits remain genuine evidence. The autouse graph fixture
    # releases this test's exact owned rows in FK order after every outcome.
    yield fixture


class TerminalHandoffInput(TypedDict):
    """Explicit complete inputs reused for an identical idempotent handoff."""

    execution: ActionExecution
    actor_generation: int | None
    allocation: SessionGitWorktree | None
    external_id: str
    continuation_idempotency_key: str
    status: ActionExecutionStatus
    failure_summary: str | None
    cancellation_summary: str | None
    predecessor_run_id: str | None
    terminal_at: datetime.datetime


async def test_reads_use_readonly_scopes_without_owner_or_parent_locks(
    worktree_operations: WorktreeOperationsFixture,
) -> None:
    """Retained observations finish while a concurrent owner writer holds its row."""
    fixture = worktree_operations
    execution = await fixture.execution(bridge=False)
    async with fixture.write_manager() as blocker:
        await blocker.write_session.execute(
            sa.select(RDBAgentSession)
            .where(RDBAgentSession.id == execution.session_id)
            .with_for_update()
        )
        async with asyncio.timeout(3):
            session = await fixture.repository.read_session(
                session_id=execution.session_id
            )
            projection = await fixture.repository.read_action_projection(
                execution=execution
            )
            await fixture.repository.assert_actor_current(
                execution=execution, actor_generation=execution.owner_generation
            )
        assert session is not None and projection.execution.id == execution.id
        # Only the deliberate writer remains open; completed observations are closed.
        assert all(
            not session.in_transaction()
            for session in fixture.sessions
            if session is not blocker.write_session
        )
    async with fixture.read_manager() as session:
        result = await session.read_session.execute(
            sa.text("SHOW transaction_read_only")
        )
        assert result.scalar_one() == "on"
    fixture.assert_closed()


async def test_exact_owner_cas_rejects_stale_mutation_without_writes(
    worktree_operations: WorktreeOperationsFixture,
) -> None:
    fixture = worktree_operations
    execution = await fixture.execution(bridge=False)
    async with fixture.write_manager() as session:
        next_generation = await AgentSessionRepository().claim_owner_generation(
            session, execution.session_id
        )
    with pytest.raises(CanonicalExecutionOwnerGenerationStaleError):
        await fixture.repository.update_result(
            execution=execution, actor_generation=None, result={"stale": True}
        )
    with pytest.raises(CanonicalExecutionOwnerGenerationStaleError):
        await fixture.repository.append_action_event(
            execution=execution,
            actor_generation=None,
            kind=ActionExecutionEventKind.STEP_STARTED,
            step_key=None,
            command_argv=None,
            content="stale",
            exit_code=None,
        )
    recovered = await fixture.repository.update_result(
        execution=execution, actor_generation=next_generation, result={"recovery": True}
    )
    assert recovered.result == {"recovery": True}
    fixture.assert_closed()
    async with fixture.read_manager() as session:
        assert (
            await ActionExecutionRepository().list_events(
                session, action_execution_id=execution.id
            )
            == []
        )


@pytest.mark.parametrize("cancel", [False, True])
async def test_terminal_handoff_rolls_back_transcript_and_continuation(
    worktree_operations: WorktreeOperationsFixture,
    monkeypatch: pytest.MonkeyPatch,
    cancel: bool,
) -> None:
    """Final live-row deletion failure rolls back the entire event/mailbox handoff."""
    fixture = worktree_operations
    execution = await fixture.execution(bridge=True)
    repository = fixture.repository

    async def fail_delete(session: WriteSession, *, action_execution_id: str) -> None:
        del session, action_execution_id
        if cancel:
            raise asyncio.CancelledError
        raise RuntimeError("Injected live delete failure")

    original = repository.action_execution_repository.delete_by_id
    monkeypatch.setattr(
        repository.action_execution_repository, "delete_by_id", fail_delete
    )
    external_id = f"action_execution_result:{execution.id}"
    continuation_id = f"turn_action_continuation:{execution.id}"
    args = TerminalHandoffInput(
        execution=execution,
        actor_generation=None,
        allocation=None,
        external_id=external_id,
        continuation_idempotency_key=continuation_id,
        status=ActionExecutionStatus.COMPLETED,
        failure_summary=None,
        cancellation_summary=None,
        predecessor_run_id=uuid4().hex,
        terminal_at=datetime.datetime.now(datetime.UTC),
    )
    with pytest.raises(asyncio.CancelledError if cancel else RuntimeError):
        await repository.commit_terminal_handoff(**args)
    fixture.assert_closed()
    async with fixture.read_manager() as session:
        assert (
            await ActionExecutionRepository().get_by_id(
                session, action_execution_id=execution.id
            )
            is not None
        )
        assert (
            await EventTranscriptRepository().get_by_external_id(
                session, execution.session_id, external_id
            )
            is None
        )
        assert (
            await MailboxRepository().get_by_idempotency_key(
                session,
                session_id=execution.session_id,
                kind=MailboxItemKind.TURN_ACTION_CONTINUATION,
                idempotency_key=continuation_id,
            )
            is None
        )
    monkeypatch.setattr(
        repository.action_execution_repository, "delete_by_id", original
    )
    event = await repository.commit_terminal_handoff(**args)
    replay = await repository.commit_terminal_handoff(**args)
    assert event.id == replay.id and event.kind == EventKind.ACTION_EXECUTION_RESULT
    fixture.assert_closed()
    async with fixture.read_manager() as session:
        assert (
            await ActionExecutionRepository().get_by_id(
                session, action_execution_id=execution.id
            )
            is None
        )
        assert (
            await MailboxRepository().get_by_idempotency_key(
                session,
                session_id=execution.session_id,
                kind=MailboxItemKind.TURN_ACTION_CONTINUATION,
                idempotency_key=continuation_id,
            )
            is not None
        )


async def test_admission_wakeup_failure_rolls_back_mailbox(
    worktree_operations: WorktreeOperationsFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = worktree_operations
    scenario = fixture.scenario
    async with fixture.read_manager() as session:
        session_agent = await AgentSessionRepository().get_session_agent_by_session_id(
            session, scenario.session_id
        )
        assert session_agent is not None

    async def fail_wakeup(session: WriteSession, session_id: str) -> None:
        del session, session_id
        raise RuntimeError("Injected wakeup failure")

    monkeypatch.setattr(
        fixture.repository.agent_session_repository,
        "mark_running_for_input_wakeup",
        fail_wakeup,
    )
    identity = f"admission-{uuid4().hex}"
    with pytest.raises(RuntimeError, match="Injected wakeup"):
        await fixture.repository.admit_create(
            agent_id=scenario.agent_id,
            context_id=session_agent.context_id,
            bridge_identity=identity,
            client_tool_call_id="call",
            originating_run_id=uuid4().hex,
            owner_generation=scenario.owner_generation,
            session_id=scenario.session_id,
            normalized_branch_name=None,
            normalized_source_path=scenario.source_project_path,
            normalized_starting_ref=None,
        )
    fixture.assert_closed()
    async with fixture.read_manager() as session:
        assert (
            await MailboxRepository().get_by_idempotency_key(
                session,
                session_id=scenario.session_id,
                kind=MailboxItemKind.ACTION_MESSAGE,
                idempotency_key=identity,
            )
            is None
        )


async def test_binding_validation_and_project_link_share_one_transaction(
    worktree_operations: WorktreeOperationsFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = worktree_operations
    scenario = fixture.scenario
    execution = await fixture.execution(bridge=False)
    runtime = await scenario.service.runtime_target_resolver.resolve_operation_target(
        scenario.agent_id, start_if_stopped=False
    )
    target = scenario.service.session_working_folder_binding_service.target_evidence(
        runtime
    )
    async with fixture.write_manager() as session:
        allocation = await fixture.repository.session_git_worktree_repository.create(
            session,
            SessionGitWorktreeCreate(
                id=uuid4().hex,
                session_id=scenario.session_id,
                action_execution_id=execution.id,
                session_workspace_project_id=None,
                source_project_path=scenario.source_project_path,
                starting_ref="main",
                worktree_path="/workspace/agent/.azents/sessions/worktree/worktrees/new",
                branch_name=f"azents/rollback-{uuid4().hex}",
                branch_created_by=SessionGitWorktreeBranchCreatedBy.AZENTS,
                status=SessionGitWorktreeStatus.PENDING,
            ),
        )
    repository = fixture.repository
    seen: list[WriteSession] = []
    binding_original = repository.binding_repository.resolve_authority_in_session
    link_original = repository.session_git_worktree_repository.link_workspace_project

    async def binding(
        session: WriteSession,
        *,
        agent_id: str,
        session_id: str,
        target: SessionWorkingFolderTarget,
        bind_pending: bool,
    ) -> SessionWorkingFolderAuthority:
        seen.append(session)
        return await binding_original(
            session,
            agent_id=agent_id,
            session_id=session_id,
            target=target,
            bind_pending=bind_pending,
        )

    async def fail_link(
        session: WriteSession, *, worktree_id: str, session_workspace_project_id: str
    ) -> None:
        assert seen[-1] is session
        del worktree_id, session_workspace_project_id
        raise RuntimeError("Injected link failure")

    monkeypatch.setattr(
        repository.binding_repository, "resolve_authority_in_session", binding
    )
    monkeypatch.setattr(
        repository.session_git_worktree_repository, "link_workspace_project", fail_link
    )
    with pytest.raises(RuntimeError, match="Injected link"):
        await repository.register_project(
            execution=execution,
            agent_id=scenario.agent_id,
            allocation=allocation,
            target=target,
            worktree_path=allocation.worktree_path,
        )
    fixture.assert_closed()
    async with fixture.read_manager() as session:
        assert (
            await SessionWorkspaceProjectRepository().get_project_by_path(
                session, session_id=scenario.session_id, path=allocation.worktree_path
            )
            is None
        )
    monkeypatch.setattr(
        repository.session_git_worktree_repository,
        "link_workspace_project",
        link_original,
    )
    project = await repository.register_project(
        execution=execution,
        agent_id=scenario.agent_id,
        allocation=allocation,
        target=target,
        worktree_path=allocation.worktree_path,
    )
    assert project.path == allocation.worktree_path
    fixture.assert_closed()


async def test_cancellation_and_projection_callbacks_execute_after_commit(
    worktree_operations: WorktreeOperationsFixture,
) -> None:
    fixture = worktree_operations
    execution = await fixture.execution(bridge=False)
    service = fixture.scenario.service

    async def projection_updated(projection: object) -> None:
        del projection
        fixture.assert_closed()
        async with fixture.read_manager() as session:
            result = await ActionExecutionRepository().get_by_id(
                session, action_execution_id=execution.id
            )
            assert (
                result is not None
                and result.result
                == _cleanup_result(phase="discovering", candidates=[]).to_json()
            )
        fixture.assert_closed()

    await service._update_action_result(
        execution=execution,
        result=_cleanup_result(phase="discovering", candidates=[]).to_json(),
        on_projection_updated=projection_updated,
    )

    async def history_appended(event: Event) -> None:
        fixture.assert_closed()
        assert event.kind == EventKind.ACTION_EXECUTION_RESULT
        async with fixture.read_manager() as session:
            assert (
                await ActionExecutionRepository().get_by_id(
                    session, action_execution_id=execution.id
                )
                is None
            )
        fixture.assert_closed()

    await service.cancel_action_execution(
        execution=execution,
        owner_generation=execution.owner_generation,
        reason="handoff",
        on_history_event_appended=history_appended,
        predecessor_run_id=None,
    )
    fixture.assert_closed()


async def test_exact_owner_fence_retained_until_dependent_mutation_commits(
    worktree_operations: WorktreeOperationsFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The owner's row remains write-fenced through the dependent action mutation."""
    fixture = worktree_operations
    execution = await fixture.execution(bridge=False)
    reached_mutation = asyncio.Event()
    release_mutation = asyncio.Event()
    original = fixture.repository.action_execution_repository.update_result

    async def paused_update(
        session: WriteSession,
        *,
        action_execution_id: str,
        result: dict[str, JSONValue],
    ) -> ActionExecution:
        reached_mutation.set()
        await release_mutation.wait()
        return await original(
            session, action_execution_id=action_execution_id, result=result
        )

    monkeypatch.setattr(
        fixture.repository.action_execution_repository, "update_result", paused_update
    )
    task = asyncio.create_task(
        fixture.repository.update_result(
            execution=execution, actor_generation=None, result={"committed": True}
        )
    )
    try:
        async with asyncio.timeout(3):
            await reached_mutation.wait()
        async with fixture.write_manager() as contender:
            with pytest.raises(OperationalError):
                await contender.write_session.execute(
                    sa.select(RDBAgentSession)
                    .where(RDBAgentSession.id == execution.session_id)
                    .with_for_update(nowait=True)
                )
            await contender.write_session.rollback()
        release_mutation.set()
        updated = await task
        assert updated.result == {"committed": True}
        fixture.assert_closed()
        async with fixture.write_manager() as session:
            generation = await AgentSessionRepository().claim_owner_generation(
                session, execution.session_id
            )
        assert generation > execution.owner_generation
    finally:
        release_mutation.set()
        if not task.done():
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task


async def test_allocation_fence_binding_and_path_lock_order(
    worktree_operations: WorktreeOperationsFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Owner, binding and Runtime/path exclusion remain one ordered atomic group."""
    fixture = worktree_operations
    scenario = fixture.scenario
    execution = await fixture.execution(bridge=True)
    action = AgentCreateGitWorktreeAction.model_validate(execution.action)
    runtime = await scenario.service.runtime_target_resolver.resolve_operation_target(
        scenario.agent_id, start_if_stopped=False
    )
    target = scenario.service.session_working_folder_binding_service.target_evidence(
        runtime
    )
    binding_service = scenario.service.session_working_folder_binding_service
    authority = await binding_service.resolve_bound_authority_for_target(
        agent_id=scenario.agent_id,
        session_id=scenario.session_id,
        runtime_target=runtime,
    )
    repository = fixture.repository
    order: list[str] = []
    observed_session: list[WriteSession] = []
    original_fence = operations_module.fence_owned_session_mutation
    original_binding = repository.binding_repository.resolve_authority_in_session
    projects = repository.session_workspace_project_repository
    original_coordination = projects.acquire_runtime_path_coordination_lock
    original_path = projects.acquire_runtime_worktree_path_lock

    def observe(session: WriteSession, stage: str) -> None:
        if observed_session:
            assert observed_session[0] is session
        else:
            observed_session.append(session)
        order.append(stage)

    async def fence(
        session: WriteSession, owner: SessionExecutionOwner
    ) -> SessionExecutionRecord:
        observe(session, "owner")
        return await original_fence(session, owner)

    async def binding(
        session: WriteSession,
        *,
        agent_id: str,
        session_id: str,
        target: SessionWorkingFolderTarget,
        bind_pending: bool,
    ) -> SessionWorkingFolderAuthority:
        observe(session, "binding")
        return await original_binding(
            session,
            agent_id=agent_id,
            session_id=session_id,
            target=target,
            bind_pending=bind_pending,
        )

    async def coordination(session: WriteSession, *, runtime_id: str) -> None:
        observe(session, "runtime")
        await original_coordination(session, runtime_id=runtime_id)

    async def path(
        session: WriteSession, *, runtime_id: str, worktree_path: str
    ) -> None:
        observe(session, "path")
        await original_path(session, runtime_id=runtime_id, worktree_path=worktree_path)

    monkeypatch.setattr(operations_module, "fence_owned_session_mutation", fence)
    monkeypatch.setattr(
        repository.binding_repository, "resolve_authority_in_session", binding
    )
    monkeypatch.setattr(
        projects, "acquire_runtime_path_coordination_lock", coordination
    )
    monkeypatch.setattr(projects, "acquire_runtime_worktree_path_lock", path)
    current = await repository.read_session(session_id=scenario.session_id)
    assert current is not None
    allocation = await repository.allocate_agent_worktree(
        execution=execution,
        agent_id=scenario.agent_id,
        session_id=scenario.session_id,
        target=target,
        source_project_id=action.source_project_id,
        context_id=action.session_agent_context_id,
        normalized_source_path=scenario.source_project_path,
        session_handle=current.handle,
        runtime_id=runtime.id,
        working_folder_path=authority.working_folder_path,
        source_project_path=scenario.source_project_path,
        starting_ref="main",
        requested_branch_name=None,
    )
    assert order == ["owner", "binding", "runtime", "path"]
    assert allocation.action_execution_id == execution.id
    fixture.assert_closed()


async def test_stale_binding_rejects_allocation_before_new_database_state(
    worktree_operations: WorktreeOperationsFixture,
) -> None:
    """A stale Runtime capability cannot split binding validation from allocation."""
    fixture = worktree_operations
    scenario = fixture.scenario
    execution = await fixture.execution(bridge=False)
    runtime = await scenario.service.runtime_target_resolver.resolve_operation_target(
        scenario.agent_id, start_if_stopped=False
    )
    target = scenario.service.session_working_folder_binding_service.target_evidence(
        runtime
    )
    stale = SessionWorkingFolderTarget(
        id=target.id,
        capability_snapshot_version=target.capability_snapshot_version + 1,
        runtime_target_capability_version=target.runtime_target_capability_version,
        workspace_path=target.workspace_path,
    )
    current = await fixture.repository.read_session(session_id=scenario.session_id)
    assert current is not None
    with pytest.raises(SessionWorkingFolderBindingError):
        await fixture.repository.allocate_action_worktree(
            execution=execution,
            agent_id=scenario.agent_id,
            session_id=scenario.session_id,
            target=stale,
            session_handle=current.handle,
            working_folder_path="/workspace/agent/.azents/sessions/test",
            source_project_path=scenario.source_project_path,
            starting_ref="main",
        )
    fixture.assert_closed()
    assert await fixture.repository.read_action_allocation(execution=execution) is None


async def test_runner_git_operations_execute_outside_database_transactions(
    worktree_operations: WorktreeOperationsFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Runner ref lookup and checkout creation observe completed repository scopes."""
    fixture = worktree_operations
    scenario = fixture.scenario
    execution = await fixture.execution(bridge=False)
    runner = scenario.runner

    def external_boundary(*args: object, **kwargs: object) -> object:
        del args, kwargs
        fixture.assert_closed()
        return DEFAULT

    refs = AsyncMock(wraps=runner.list_git_refs, side_effect=external_boundary)
    create = AsyncMock(wraps=runner.create_git_worktree, side_effect=external_boundary)
    monkeypatch.setattr(runner, "list_git_refs", refs)
    monkeypatch.setattr(runner, "create_git_worktree", create)
    service = scenario.service
    # TEAM fixture owns no human association; fetch the real authorized owner.
    async with fixture.read_manager() as session:
        current = await AgentSessionRepository().get_by_id(session, scenario.session_id)
        assert current is not None
        member = (
            await fixture.repository.workspace_user_repository.get_owner_by_workspace(
                session, current.workspace_id
            )
        )
        assert member is not None
    result = await service.preview_git_refs(
        agent_id=scenario.agent_id,
        user_id=member.user_id,
        source_project_path=scenario.source_project_path,
    )
    assert isinstance(result, Success)
    refs.assert_awaited_once()
    outcome = await service.run_git_worktree_action(
        agent_id=scenario.agent_id,
        session_id=scenario.session_id,
        execution=execution,
        action=CreateGitWorktreeAction(
            source_project_path=scenario.source_project_path, starting_ref="main"
        ),
        owner_generation=execution.owner_generation,
    )
    assert outcome.completed
    create.assert_awaited_once()
    fixture.assert_closed()
