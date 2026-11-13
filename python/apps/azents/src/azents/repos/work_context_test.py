"""Real action and idle continuations retain exact independently settled work."""

import datetime

import pytest
import sqlalchemy as sa
from azcommon.datetime import tznow
from azcommon.uuid import uuid7

from azents.core.enums import (
    ActionExecutionStatus,
    AgentRunStatus,
    MailboxItemKind,
    MailboxSchedulingMode,
)
from azents.core.mailbox_data import (
    AgentCreateGitWorktreeContinuationResult,
    AgentRemoveGitWorktreeContinuationResult,
    GoalContinuationMailboxPayload,
    MailboxItemCreate,
    MailboxPresentationItem,
    TurnActionContinuationMailboxPayload,
)
from azents.core.routine import RoutineScope
from azents.core.routine_execution_test import execution
from azents.core.routine_presentation import routine_execution_ref
from azents.core.session_resource_authority import SessionExecutionOwner
from azents.core.work_context import WorkContext
from azents.rdb.models.agent_session import RDBAgentSession
from azents.rdb.models.toolkit_state import RDBToolkitState
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import WriteSession
from azents.repos.agent_execution import AgentRunRepository, EventTranscriptRepository
from azents.repos.mailbox import MailboxRepository
from azents.repos.scheduled_task.repository import ScheduledTaskRepository
from azents.repos.scheduled_task_cycle import ScheduledTaskCycleRepository
from azents.repos.scheduled_task_terminal_operations import (
    ScheduledTaskTerminalOperations,
)
from azents.repos.toolkit_state import ToolkitStateRepository
from azents.services.mailbox_test import _create_fixture, _mailbox_item_service
from azents.services.scheduled_task.terminal_test import _cycle


async def test_repeated_cross_domain_continuation_keeps_multiple_work_items(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    session_id, _ = await _create_fixture(rdb_session_manager, "cross-domain-work")
    runs = AgentRunRepository()
    cycles = (uuid7().hex, uuid7().hex)
    async with rdb_session_manager() as session:
        canonical = await session.read_session.get(RDBAgentSession, session_id)
        assert canonical is not None
        scope = RoutineScope(
            workspace_id=canonical.workspace_id,
            agent_id=canonical.agent_id,
            session_id=session_id,
        )
        routine = execution(scope).model_copy(
            update={
                "phase": "started",
                "started_at": datetime.datetime.now(datetime.UTC),
            }
        )
        context = WorkContext(
            scheduled_cycle_ids=cycles,
            routine_executions=(routine_execution_ref(routine),),
            unrelated_input=False,
        )
        for cycle_id in cycles:
            state = _cycle().state.model_copy(
                update={
                    "cycle_id": cycle_id,
                    "workspace_id": scope.workspace_id,
                    "agent_id": scope.agent_id,
                    "session_id": session_id,
                }
            )
            session.write_session.add(
                RDBToolkitState(
                    agent_id=scope.agent_id,
                    session_id=session_id,
                    toolkit_namespace="scheduled",
                    state_name=f"cycle:{cycle_id}",
                    state_json=state.model_dump(mode="json"),
                    schema_version=1,
                )
            )
        session.write_session.add(
            RDBToolkitState(
                agent_id=scope.agent_id,
                session_id=session_id,
                toolkit_namespace="routines",
                state_name=f"execution:{routine.context.candidate.routine_id}",
                state_json=routine.model_dump(mode="json"),
                schema_version=1,
            )
        )
        source = await runs.create_pending(
            session,
            session_id=session_id,
            parent_agent_run_id=None,
            work_context=context,
        )
        await runs.mark_terminal(
            session, source.id, AgentRunStatus.COMPLETED, ended_at=tznow()
        )
    source_id = source.id
    service = _mailbox_item_service(rdb_session_manager)
    for step in range(3):
        async with rdb_session_manager() as session:
            target = await runs.create_pending(
                session,
                session_id=session_id,
                parent_agent_run_id=None,
                work_context=WorkContext.empty(),
            )
            target = await runs.activate_pending(
                session,
                run_id=target.id,
                activated_at=tznow(),
                requested_model_target_label="default",
                requested_reasoning_effort=None,
                requested_enabled_execution_options=[],
            )
            payload: (
                GoalContinuationMailboxPayload | TurnActionContinuationMailboxPayload
            ) = GoalContinuationMailboxPayload(
                type="goal_continuation",
                source_run_id=source_id,
                items=[
                    MailboxPresentationItem(
                        item_key="goal_continuation:0",
                        presentation_kind="goal_continuation",
                        content="Continue the Goal without replacing other work.",
                    )
                ],
            )
            action_id = uuid7().hex
            if step < 2:
                payload = TurnActionContinuationMailboxPayload(
                    type="turn_action_continuation",
                    items=[
                        MailboxPresentationItem(
                            item_key="turn_action_continuation:0",
                            presentation_kind="turn_action_continuation",
                        )
                    ],
                    bridge_identity=f"bridge-{step}",
                    action_execution_id=action_id,
                    originating_run_id=source_id,
                    predecessor_run_id=source_id,
                    terminal_status=ActionExecutionStatus.COMPLETED,
                    reason_code=None,
                    failure_summary=None,
                    cancellation_summary=None,
                    result=(
                        AgentCreateGitWorktreeContinuationResult(
                            type="agent_create_git_worktree",
                            source_project_path="/workspace/agent/repo",
                            generated_worktree_path="/workspace/agent/generated",
                            requested_starting_ref=None,
                            resolved_base_commit="a" * 40,
                            branch_name="agent/generated",
                        )
                        if step == 0
                        else AgentRemoveGitWorktreeContinuationResult(
                            type="agent_remove_git_worktree",
                            worktree_path="/workspace/agent/generated",
                            preserved_branch_name="agent/generated",
                            force=False,
                            dirty_content_discarded=False,
                            retry_guidance=None,
                        )
                    ),
                )
            item = await MailboxRepository().create(
                session,
                MailboxItemCreate(
                    session_id=session_id,
                    kind=(
                        MailboxItemKind.TURN_ACTION_CONTINUATION
                        if step < 2
                        else MailboxItemKind.GOAL_CONTINUATION
                    ),
                    scheduling_mode=MailboxSchedulingMode.WAKE_SESSION,
                    requested_model_target_label=None,
                    requested_reasoning_effort=None,
                    requested_enabled_execution_options=[],
                    sender_user_id=None,
                    order_group=None,
                    order_sequence=0,
                    content="",
                    metadata={},
                    idempotency_key=(
                        f"turn_action_continuation:{action_id}"
                        if step < 2
                        else f"idle_continuation:{source_id}:goal:0"
                    ),
                    attachments=[],
                    file_parts=[],
                    action=None,
                    payload=payload,
                ),
            )
        promoted = await service.flush_session_mailbox_items(
            session_id=session_id,
            owner_generation=0,
            model="gpt-5.4",
            required_inference_profile=None,
            expected_buffer_id=item.id,
            prepared_inference_state=None,
            profile_resolution_failure=None,
            active_run_id=target.id,
        )
        assert promoted.claimed_count == 1
        async with rdb_session_manager() as session:
            stored = await runs.get_by_id(session, target.id)
            assert stored is not None
            assert stored.work_context.scheduled_cycle_ids == cycles
            assert stored.work_context.routine_executions == context.routine_executions
            assert stored.work_context.unrelated_input is (step == 2)
            # Simulate retention: continuing authority is not reconstructed from inputs.
            await session.write_session.execute(
                sa.text("DELETE FROM agent_run_input_events WHERE agent_run_id=:id"),
                {"id": source_id},
            )
            if step < 2:
                await runs.mark_terminal(
                    session, target.id, AgentRunStatus.COMPLETED, ended_at=tznow()
                )
        source_id = target.id
    operations = ScheduledTaskTerminalOperations(
        session_manager=rdb_session_manager,
        run_repository=runs,
        event_repository=EventTranscriptRepository(),
        task_repository=ScheduledTaskRepository(),
        cycle_repository=ScheduledTaskCycleRepository(ToolkitStateRepository()),
        owner=SessionExecutionOwner(session_id=session_id, owner_generation=0),
    )
    for cycle_id in cycles:
        outcome = await operations.submit(
            workspace_id=scope.workspace_id,
            agent_id=scope.agent_id,
            session_id=session_id,
            run_id=source_id,
            cycle_id=cycle_id,
            status="finished",
            result="Verified independently.",
            notify=True,
            suppression_reason=None,
        )
        assert outcome.created
        assert not outcome.finish_run  # The independent Routine is still started.
    with pytest.raises(ValueError, match="not an active Scheduled Task cycle"):
        await operations.submit(
            workspace_id=scope.workspace_id,
            agent_id=scope.agent_id,
            session_id=session_id,
            run_id=source_id,
            cycle_id=uuid7().hex,
            status="finished",
            result="Must not settle unadmitted work.",
            notify=True,
            suppression_reason=None,
        )
