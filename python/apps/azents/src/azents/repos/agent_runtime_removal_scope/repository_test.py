"""Agent Runtime removal scope repository tests."""

import datetime
from uuid import uuid4

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    ActionExecutionStatus,
    AgentProjectCatalogStatus,
    AgentProjectDefaultItemType,
    AgentRunPhase,
    AgentRunStatus,
    AgentRuntimeCapability,
    AgentSessionKind,
    AgentSessionProductMode,
    AgentSessionRunState,
    AgentSessionStartReason,
    AgentSessionStatus,
    GitWorktreePathClaimOwnerKind,
    GitWorktreePathClaimState,
    SessionGitWorktreeBranchCreatedBy,
    SessionGitWorktreeStatus,
    SessionWorkingFolderBindingState,
    SessionWorkingFolderCleanupStatus,
)
from azents.rdb.models.action_execution import RDBActionExecution
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.agent_automatic_project_item import (
    RDBAgentAutomaticProjectItem,
)
from azents.rdb.models.agent_automatic_project_setting import (
    RDBAgentAutomaticProjectSetting,
)
from azents.rdb.models.agent_project_catalog import RDBAgentProjectCatalogEntry
from azents.rdb.models.agent_project_default import RDBAgentProjectDefault
from azents.rdb.models.agent_project_preset import RDBAgentProjectPreset
from azents.rdb.models.agent_run import RDBAgentRun
from azents.rdb.models.agent_runtime import RDBAgentRuntime
from azents.rdb.models.agent_session import RDBAgentSession
from azents.rdb.models.git_worktree_cleanup_claim import RDBGitWorktreePathClaim
from azents.rdb.models.memory import RDBAgentMemory
from azents.rdb.models.session_agent_context import (
    RDBSessionAgentContext,
    RDBSessionAgentContextGitWorktree,
    RDBSessionAgentContextProject,
)
from azents.rdb.models.toolkit_state import RDBToolkitState
from azents.rdb.models.workspace import RDBWorkspace
from azents.repos.agent_runtime_removal import AgentRuntimeRemovalRepository
from azents.testing.model_selection import make_test_model_selection_dict

from . import AgentRuntimeRemovalScopeRepository


async def _seed_agent(
    session: AsyncSession,
) -> tuple[RDBWorkspace, RDBAgent, RDBAgentRuntime]:
    """Create one Agent and empty logical Runtime."""
    workspace = RDBWorkspace(
        name="Runtime removal scope",
        handle=f"removal-scope-{uuid4().hex[:8]}",
    )
    session.add(workspace)
    await session.flush()
    selection = make_test_model_selection_dict()
    agent = RDBAgent(
        workspace_id=workspace.id,
        name="Runtime removal scope Agent",
        model_selection=selection,
        lightweight_model_selection=selection,
        runtime_capability=AgentRuntimeCapability.REMOVING,
        runtime_capability_version=2,
    )
    session.add(agent)
    await session.flush()
    runtime = RDBAgentRuntime(
        workspace_id=workspace.id,
        agent_id=agent.id,
        runtime_provider_id=None,
        runtime_provider_resource_id=None,
        provider_binding_origin=None,
        provider_binding_evidence=None,
    )
    session.add(runtime)
    await session.flush()
    return workspace, agent, runtime


async def _create_operation(
    session: AsyncSession,
    *,
    workspace: RDBWorkspace,
    agent: RDBAgent,
    runtime: RDBAgentRuntime,
) -> str:
    """Create one removal operation used as invalidation evidence."""
    created = await AgentRuntimeRemovalRepository().create_or_get_active(
        session,
        agent_id=agent.id,
        workspace_id=workspace.id,
        requested_by_workspace_user_id="workspace-user-1",
        idempotency_key=f"remove-{uuid4().hex}",
        expected_capability_version=1,
        committed_capability_version=2,
        agent_runtime_id=runtime.id,
        confirmed_at=datetime.datetime.now(datetime.UTC),
        destructive_scope_version=1,
        active_root_session_count=0,
        active_subagent_count=0,
        active_run_count=0,
        queued_runtime_action_count=0,
    )
    return created.operation.id


async def _insert_session(
    session: AsyncSession,
    *,
    workspace_id: str,
    agent_id: str,
    session_kind: AgentSessionKind,
    run_state: AgentSessionRunState,
) -> str:
    """Insert one Session without exposing it through a public projection."""
    session_id = uuid4().hex
    await session.execute(
        sa.insert(RDBAgentSession).values(
            id=session_id,
            workspace_id=workspace_id,
            agent_id=agent_id,
            handle=f"session-{uuid4().hex[:8]}",
            session_kind=session_kind,
            status=AgentSessionStatus.ACTIVE,
            product_mode=(
                AgentSessionProductMode.TEAM
                if session_kind is AgentSessionKind.ROOT
                else None
            ),
            associated_user_id=None,
            start_reason=AgentSessionStartReason.INITIAL,
            run_state=run_state,
        )
    )
    return session_id


async def test_interruption_stops_all_trees_and_cancels_only_runtime_actions(
    rdb_session: AsyncSession,
) -> None:
    """Durable stop fences cover Agent trees while remote work is retained."""
    workspace, agent, _ = await _seed_agent(rdb_session)
    root_id = await _insert_session(
        rdb_session,
        workspace_id=workspace.id,
        agent_id=agent.id,
        session_kind=AgentSessionKind.ROOT,
        run_state=AgentSessionRunState.RUNNING,
    )
    subagent_id = await _insert_session(
        rdb_session,
        workspace_id=workspace.id,
        agent_id=agent.id,
        session_kind=AgentSessionKind.SUBAGENT,
        run_state=AgentSessionRunState.RUNNING,
    )
    lagged_session_id = await _insert_session(
        rdb_session,
        workspace_id=workspace.id,
        agent_id=agent.id,
        session_kind=AgentSessionKind.SUBAGENT,
        run_state=AgentSessionRunState.IDLE,
    )
    running_run_id = uuid4().hex
    lagged_run_id = uuid4().hex
    await rdb_session.execute(
        sa.insert(RDBAgentRun),
        [
            {
                "id": running_run_id,
                "session_id": subagent_id,
                "run_index": 1,
                "parent_agent_run_id": None,
                "phase": AgentRunPhase.EXECUTING_TOOLS,
                "status": AgentRunStatus.RUNNING,
            },
            {
                "id": lagged_run_id,
                "session_id": lagged_session_id,
                "run_index": 1,
                "parent_agent_run_id": None,
                "phase": AgentRunPhase.IDLE,
                "status": AgentRunStatus.PENDING,
            },
        ],
    )
    runtime_action_id = uuid4().hex
    remote_action_id = uuid4().hex
    await rdb_session.execute(
        sa.insert(RDBActionExecution),
        [
            {
                "id": runtime_action_id,
                "session_id": root_id,
                "mailbox_item_id": uuid4().hex,
                "sender_user_id": None,
                "action_type": "create_session_working_folder",
                "action": {"type": "create_session_working_folder"},
                "owner_generation": 0,
                "status": ActionExecutionStatus.PENDING,
            },
            {
                "id": remote_action_id,
                "session_id": root_id,
                "mailbox_item_id": uuid4().hex,
                "sender_user_id": None,
                "action_type": "skill",
                "action": {"type": "skill", "skill_path": "azents://skill"},
                "owner_generation": 0,
                "status": ActionExecutionStatus.PENDING,
            },
        ],
    )
    repository = AgentRuntimeRemovalScopeRepository()
    now = datetime.datetime.now(datetime.UTC)

    interrupted = await repository.interrupt_work(
        rdb_session,
        agent_id=agent.id,
        operation_id="removal-operation",
        now=now,
    )

    assert set(interrupted.stop_session_ids) == {
        root_id,
        subagent_id,
        lagged_session_id,
    }
    assert interrupted.cancelled_runtime_action_count == 1
    assert interrupted.active_work_remaining is True
    runtime_action = await rdb_session.get(RDBActionExecution, runtime_action_id)
    remote_action = await rdb_session.get(RDBActionExecution, remote_action_id)
    assert runtime_action is not None
    assert remote_action is not None
    assert runtime_action.status is ActionExecutionStatus.CANCELLED
    assert remote_action.status is ActionExecutionStatus.PENDING

    await rdb_session.execute(
        sa.update(RDBAgentSession)
        .where(RDBAgentSession.id.in_((root_id, subagent_id, lagged_session_id)))
        .values(run_state=AgentSessionRunState.IDLE)
    )
    await rdb_session.execute(
        sa.update(RDBAgentRun)
        .where(RDBAgentRun.id.in_((running_run_id, lagged_run_id)))
        .values(
            status=AgentRunStatus.INTERRUPTED,
            phase=AgentRunPhase.IDLE,
            ended_at=now,
        )
    )
    assert not await repository.has_active_work(rdb_session, agent_id=agent.id)


async def test_bounded_cleanup_invalidates_bindings_and_preserves_retained_state(
    rdb_session: AsyncSession,
) -> None:
    """Cleanup removes Runtime-owned metadata without deleting retained roots."""
    workspace, agent, runtime = await _seed_agent(rdb_session)
    operation_id = await _create_operation(
        rdb_session,
        workspace=workspace,
        agent=agent,
        runtime=runtime,
    )
    session_id = await _insert_session(
        rdb_session,
        workspace_id=workspace.id,
        agent_id=agent.id,
        session_kind=AgentSessionKind.ROOT,
        run_state=AgentSessionRunState.IDLE,
    )
    none_context = RDBSessionAgentContext(
        agent_id=agent.id,
        workspace_id=workspace.id,
        working_folder_path=None,
        working_folder_cleanup_status=(SessionWorkingFolderCleanupStatus.NOT_ATTEMPTED),
        working_folder_cleanup_summary=None,
        working_folder_cleanup_completed_at=None,
        working_folder_binding_state=SessionWorkingFolderBindingState.NONE,
        root_session_agent_id=None,
        agent_runtime_id=None,
        working_folder_invalidated_by_removal_id=None,
        working_folder_invalidated_at=None,
    )
    pending_context = RDBSessionAgentContext(
        agent_id=agent.id,
        workspace_id=workspace.id,
        working_folder_path=None,
        working_folder_cleanup_status=SessionWorkingFolderCleanupStatus.PENDING,
        working_folder_cleanup_summary=None,
        working_folder_cleanup_completed_at=None,
        working_folder_binding_state=SessionWorkingFolderBindingState.PENDING,
        root_session_agent_id=None,
        agent_runtime_id=runtime.id,
        working_folder_invalidated_by_removal_id=None,
        working_folder_invalidated_at=None,
    )
    bound_context = RDBSessionAgentContext(
        agent_id=agent.id,
        workspace_id=workspace.id,
        working_folder_path=f"/workspace/{uuid4().hex}",
        working_folder_cleanup_status=(SessionWorkingFolderCleanupStatus.NOT_ATTEMPTED),
        working_folder_cleanup_summary=None,
        working_folder_cleanup_completed_at=None,
        working_folder_binding_state=SessionWorkingFolderBindingState.BOUND,
        root_session_agent_id=None,
        agent_runtime_id=runtime.id,
        working_folder_invalidated_by_removal_id=None,
        working_folder_invalidated_at=None,
    )
    rdb_session.add_all((none_context, pending_context, bound_context))
    await rdb_session.flush()

    project = RDBSessionAgentContextProject(
        session_agent_context_id=bound_context.id,
        path="/workspace/project",
    )
    rdb_session.add(project)
    await rdb_session.flush()
    worktree = RDBSessionAgentContextGitWorktree(
        session_agent_context_id=bound_context.id,
        source_project_path="/workspace/project",
        starting_ref="main",
        worktree_path="/workspace/worktree",
        branch_name="runtime-removal-test",
        branch_created_by=SessionGitWorktreeBranchCreatedBy.AZENTS,
        status=SessionGitWorktreeStatus.READY,
        created_by_session_agent_id=None,
        created_by_agent_session_id=session_id,
        action_execution_id=None,
        session_agent_context_project_id=project.id,
        base_commit=None,
        failure_summary=None,
        cleanup_summary=None,
        ready_at=datetime.datetime.now(datetime.UTC),
        failed_at=None,
        cleaned_at=None,
    )
    rdb_session.add(worktree)
    rdb_session.add(
        RDBGitWorktreePathClaim(
            agent_runtime_id=runtime.id,
            worktree_path="/workspace/worktree",
            owner_kind=GitWorktreePathClaimOwnerKind.MANUAL_ACTION,
            lease_until=datetime.datetime.now(datetime.UTC)
            + datetime.timedelta(minutes=5),
            action_execution_id=None,
            root_session_id=session_id,
            owner_generation=0,
            discovery_fingerprint=None,
            state=GitWorktreePathClaimState.CLAIMED,
            reason_code=None,
            summary=None,
        )
    )
    rdb_session.add(
        RDBAgentAutomaticProjectSetting(
            agent_id=agent.id,
            revision=1,
            updated_by_workspace_user_id=None,
        )
    )
    await rdb_session.flush()
    rdb_session.add_all(
        (
            RDBAgentAutomaticProjectItem(
                agent_id=agent.id,
                path="/workspace/automatic",
                position=0,
            ),
            RDBAgentProjectCatalogEntry(
                agent_id=agent.id,
                path="/workspace/catalog",
                status=AgentProjectCatalogStatus.UNCHECKED,
                status_detail=None,
                checked_at=None,
            ),
            RDBAgentProjectDefault(
                agent_id=agent.id,
                path="/workspace/default",
                position=0,
                item_type=AgentProjectDefaultItemType.EXISTING_PROJECT,
            ),
            RDBAgentProjectPreset(
                agent_id=agent.id,
                path="/workspace/preset",
            ),
            RDBAgentMemory(
                agent_id=agent.id,
                scope="agent",
                type="project",
                name="retained-memory",
                description="Retained",
                content="Retained content",
                user_id=None,
            ),
            RDBToolkitState(
                agent_id=agent.id,
                session_id=session_id,
                toolkit_namespace="remote_toolkit",
                state_name="retained",
                state_json={"value": True},
                schema_version=1,
                version=1,
            ),
            RDBToolkitState(
                agent_id=agent.id,
                session_id=session_id,
                toolkit_namespace="skill",
                state_name="projection",
                state_json={"latest": {}, "active": {}},
                schema_version=1,
                version=1,
            ),
            RDBToolkitState(
                agent_id=agent.id,
                session_id=session_id,
                toolkit_namespace="claude_rules",
                state_name="claude_rules_appendix_dedupe",
                state_json={"appended_paths": ["/workspace/project/AGENTS.md"]},
                schema_version=1,
                version=1,
            ),
        )
    )
    await rdb_session.flush()

    repository = AgentRuntimeRemovalScopeRepository()
    cursor: str | None = None
    completed = False
    scanned = 0
    invalidated = 0
    while not completed:
        batch = await repository.cleanup_batch(
            rdb_session,
            agent_id=agent.id,
            agent_runtime_id=runtime.id,
            operation_id=operation_id,
            after_context_id=cursor,
            limit=1,
            now=datetime.datetime.now(datetime.UTC),
        )
        cursor = batch.cursor_context_id
        scanned += batch.scanned_count
        invalidated += batch.invalidated_count
        completed = batch.completed

    assert scanned == 3
    assert invalidated == 2
    replayed_cleanup = await repository.cleanup_batch(
        rdb_session,
        agent_id=agent.id,
        agent_runtime_id=runtime.id,
        operation_id=operation_id,
        after_context_id=cursor,
        limit=1,
        now=datetime.datetime.now(datetime.UTC),
    )
    assert replayed_cleanup.completed is True
    assert replayed_cleanup.scanned_count == 0
    await repository.require_cleanup_complete(
        rdb_session,
        agent_id=agent.id,
        agent_runtime_id=runtime.id,
    )
    await rdb_session.refresh(none_context)
    await rdb_session.refresh(pending_context)
    await rdb_session.refresh(bound_context)
    assert none_context.working_folder_binding_state is (
        SessionWorkingFolderBindingState.NONE
    )
    assert pending_context.working_folder_binding_state is (
        SessionWorkingFolderBindingState.INVALIDATED
    )
    assert pending_context.working_folder_cleanup_status is (
        SessionWorkingFolderCleanupStatus.FAILED
    )
    assert bound_context.working_folder_binding_state is (
        SessionWorkingFolderBindingState.INVALIDATED
    )
    assert bound_context.working_folder_path is not None
    assert pending_context.working_folder_invalidated_by_removal_id == operation_id
    assert bound_context.working_folder_invalidated_by_removal_id == operation_id
    assert await rdb_session.get(RDBAgent, agent.id) is not None
    assert await rdb_session.get(RDBAgentSession, session_id) is not None
    automatic_project_setting = await rdb_session.get(
        RDBAgentAutomaticProjectSetting,
        agent.id,
    )
    assert automatic_project_setting is not None
    assert automatic_project_setting.revision == 2
    assert not await rdb_session.scalar(
        sa.select(
            sa.exists().where(
                RDBAgentAutomaticProjectItem.agent_id == agent.id,
            )
        )
    )
    assert (
        await rdb_session.scalar(
            sa.select(sa.func.count(RDBAgentMemory.id)).where(
                RDBAgentMemory.agent_id == agent.id
            )
        )
        == 1
    )
    assert (
        await rdb_session.scalar(
            sa.select(sa.func.count(RDBToolkitState.id)).where(
                RDBToolkitState.agent_id == agent.id
            )
        )
        == 1
    )
    retained_toolkit_state = await rdb_session.scalar(
        sa.select(RDBToolkitState).where(RDBToolkitState.agent_id == agent.id)
    )
    assert retained_toolkit_state is not None
    assert retained_toolkit_state.toolkit_namespace == "remote_toolkit"
