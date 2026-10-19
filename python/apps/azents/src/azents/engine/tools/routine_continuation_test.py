"""Routine hooks reuse normal idle admission and subsequent Run promotion."""

import datetime
from unittest.mock import AsyncMock

import pytest
import sqlalchemy as sa

from azents.core.enums import AgentRunStatus, EventKind, MailboxItemKind
from azents.core.mailbox_data import RoutineContinuationMailboxPayload
from azents.core.routine_presentation import routine_execution_ref
from azents.engine.events.types import RoutineInputPayload
from azents.engine.hooks.types import (
    CompactionSummaryHookContext,
    RoutineSessionContinuationInput,
    SessionIdleHookContext,
)
from azents.engine.tools.routine_test import _context, _toolkit
from azents.rdb.models.agent_run import RDBAgentRun
from azents.rdb.models.conversation import RDBConversation
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import WriteSession
from azents.repos.agent_execution.data import AgentRunCreate
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.idle_continuation import IdleContinuationRepository
from azents.repos.mailbox import MailboxRepository
from azents.repos.mailbox.promotion import MailboxPromotionEvent, MailboxPromotionPlan
from azents.repos.routine.completion_test import fixture
from azents.repos.routine.lifecycle_test import _archive, _attach_routine_input
from azents.repos.scheduled_task_cycle import ScheduledTaskCycleRepository
from azents.repos.session_execution import SessionExecutionRepository
from azents.repos.toolkit_state import ToolkitStateRepository
from azents.testing.turn_action import make_test_mailbox_promotion_repository
from azents.worker.session.idle_continuation import IdleContinuationService


@pytest.mark.parametrize("archived", [False, True])
async def test_normal_idle_continuation_rebinds_original_context_to_next_run(
    rdb_session_manager: SessionManager[WriteSession],
    *,
    archived: bool,
) -> None:
    f = await fixture(rdb_session_manager)
    if archived:
        await _attach_routine_input(rdb_session_manager, f)
        await _archive(rdb_session_manager, f)
    toolkit = _toolkit(rdb_session_manager, f)
    toolkit.bind_execution_owner(f.authority.execution_owner)
    await toolkit.update_context(_context(f, AsyncMock()))
    context = SessionIdleHookContext(
        workspace_id=f.scope.workspace_id,
        agent_id=f.scope.agent_id,
        session_id=f.scope.session_id,
        run_id=f.authority.run_id,
        reason="completed",
    )
    assert await toolkit._on_session_idle(context) is None
    async with rdb_session_manager() as session:
        await session.write_session.execute(
            sa.update(RDBAgentRun)
            .where(
                RDBAgentRun.id == f.authority.run_id,
            )
            .values(
                status=AgentRunStatus.COMPLETED,
                ended_at=datetime.datetime.now(datetime.UTC),
            )
        )
        await session.write_session.execute(
            sa.update(RDBConversation)
            .where(
                RDBConversation.session_id == f.scope.session_id,
            )
            .values(pending_idle_continuation_run_id=f.authority.run_id)
        )
    result = await toolkit._on_session_idle(context)
    assert result is not None and len(result.continuations) == 1
    continuation = result.continuations[0]
    assert isinstance(continuation, RoutineSessionContinuationInput)
    assert len(continuation.executions) == 2
    # A continuation includes just the first complete objective, then references.
    assert continuation.content.count('"objective"') == 1
    service = IdleContinuationService(
        repository=AsyncMock(),
        event_publisher=AsyncMock(),
        broker=AsyncMock(),
    )
    prepared = service._continuation_input(
        f.scope.session_id, f.authority.run_id, continuation
    )
    assert prepared.kind is MailboxItemKind.ROUTINE_CONTINUATION
    assert isinstance(prepared.payload, RoutineContinuationMailboxPayload)
    repository = IdleContinuationRepository(
        session_manager=rdb_session_manager,
        routine_authority=f.repository.execution_authority,
        agent_session_repository=AgentSessionRepository(),
        agent_run_repository=f.repository.runs,
        mailbox_repository=MailboxRepository(),
        scheduled_task_cycle_repository=ScheduledTaskCycleRepository(
            toolkit_state_repository=ToolkitStateRepository()
        ),
    )
    finalization = await repository.finalize(
        session_id=f.scope.session_id,
        run_id=f.authority.run_id,
        owner_generation=f.authority.owner_generation,
        inputs=[prepared],
    )
    assert finalization.consumed and finalization.continuation_count == 1
    mailbox = finalization.admissions[0].mailbox_item
    async with rdb_session_manager() as session:
        if archived:
            snapshot = await SessionExecutionRepository().load_canonical_snapshot(
                session,
                session_id=f.scope.session_id,
                owner_generation=f.authority.owner_generation,
            )
            assert snapshot.session_id == f.scope.session_id
        next_run = await f.repository.runs.create(
            session,
            AgentRunCreate(
                session_id=f.scope.session_id,
                scheduled_task_cycle_id=None,
                parent_agent_run_id=None,
            ),
        )
    promoted = await make_test_mailbox_promotion_repository(
        rdb_session_manager
    ).promote(
        MailboxPromotionPlan(
            session_id=f.scope.session_id,
            owner_generation=f.authority.owner_generation,
            expected_buffer_id=mailbox.id,
            active_run_id=next_run.id,
            consume_buffer=True,
            success_events=[
                MailboxPromotionEvent(
                    kind=EventKind.ROUTINE_CONTINUATION,
                    payload=RoutineInputPayload(
                        executions=continuation.executions, content=continuation.content
                    ).model_dump(mode="json"),
                    external_id=f"{mailbox.id}:routine",
                    item_key="routine_continuation:0",
                    initial_title_candidate=None,
                )
            ],
            failure_events=[],
            goal_create=None,
            skill_revalidation=None,
            action_execution=None,
            continuation_predecessor_run_id=None,
        )
    )
    assert len(promoted.events) == 1
    for original in f.states:
        async with rdb_session_manager() as session:
            state = await f.repository.states.get_occurrence(
                session,
                scope=f.scope,
                slug=original.context.candidate.slug,
                execution_id=original.context.execution_id,
            )
            assert state is not None
            assert state.state.context == original.context
            assert state.state.current_run_id == next_run.id
            assert state.state.started_at == original.started_at
    assert isinstance(promoted.events[0].payload, RoutineInputPayload)
    assert promoted.events[0].payload.content.count('"objective"') == 1


@pytest.mark.parametrize("status", [AgentRunStatus.FAILED, AgentRunStatus.STOPPED])
async def test_failed_or_stopped_host_does_not_force_routine_continuation(
    rdb_session_manager: SessionManager[WriteSession],
    status: AgentRunStatus,
) -> None:
    f = await fixture(rdb_session_manager)
    async with rdb_session_manager() as session:
        await session.write_session.execute(
            sa.update(RDBAgentRun)
            .where(
                RDBAgentRun.id == f.authority.run_id,
            )
            .values(status=status)
        )
    assert (
        await f.repository.list_for_idle(
            scope=f.scope,
            owner=f.authority.execution_owner,
            run_id=f.authority.run_id,
        )
        == ()
    )


async def test_compaction_hook_preserves_exact_admitted_context_without_mutation(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    f = await fixture(rdb_session_manager)
    toolkit = _toolkit(rdb_session_manager, f)
    toolkit.bind_execution_owner(f.authority.execution_owner)
    await toolkit.update_context(_context(f, AsyncMock()))
    context = CompactionSummaryHookContext(
        workspace_id=f.scope.workspace_id,
        agent_id=f.scope.agent_id,
        session_id=f.scope.session_id,
        run_id=f.authority.run_id,
        compaction_id="compaction-a",
        reason=None,
        covered_until_event_id="event-a",
        summary="Existing user summary.",
        continuity_history="",
    )
    result = await toolkit._on_compaction_summary(context)
    assert result is not None
    assert result.summary.startswith(context.summary)
    assert result.summary.count('"objective"') == 1
    for original in f.states:
        assert routine_execution_ref(original).execution_id in result.summary
        current = await f.repository.context(
            scope=f.scope,
            authority=f.authority,
            slug=original.context.candidate.slug,
            execution_id=original.context.execution_id,
        )
        assert current == original
