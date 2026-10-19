"""Routine work promotion is atomic with the ordinary consuming Run and FIFO."""

import datetime

from azents.core.enums import (
    AgentRunStatus,
    EventKind,
    MailboxItemKind,
    MailboxSchedulingMode,
)
from azents.core.mailbox_data import (
    MailboxItemCreate,
    MailboxPresentationItem,
    RoutineTriggerMailboxPayload,
)
from azents.core.routine_execution import RoutineAdmittedContext, RoutineExecutionState
from azents.core.routine_execution_test import execution
from azents.core.routine_judgment_test import candidate
from azents.core.routine_presentation import (
    render_routine_execution_input,
    routine_execution_ref,
)
from azents.engine.events.types import RoutineInputPayload
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import WriteSession
from azents.repos.agent_execution import AgentRunRepository
from azents.repos.agent_execution.data import AgentRunCreate
from azents.repos.mailbox import MailboxRepository
from azents.repos.mailbox.promotion import MailboxPromotionEvent, MailboxPromotionPlan
from azents.repos.routine.persistence_test import _subject
from azents.repos.routine.state import RoutineStateRepository
from azents.repos.toolkit_state import ToolkitStateRepository
from azents.testing.turn_action import make_test_mailbox_promotion_repository


async def test_fifo_starts_only_current_occurrences_without_replacing_the_run(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    states = RoutineStateRepository(toolkit_states=ToolkitStateRepository())
    mailboxes = MailboxRepository()
    runs = AgentRunRepository()
    async with rdb_session_manager() as session:
        scope = await _subject(session)
        valid = execution(scope)
        stale = RoutineExecutionState(
            context=RoutineAdmittedContext(
                execution_id="stale-occurrence",
                judgment_id="old-judgment",
                scope=scope,
                candidate=candidate("removed-routine"),
                admitted_at=datetime.datetime(2026, 10, 18, tzinfo=datetime.UTC),
            ),
            phase="admitted",
            current_run_id=None,
            started_at=None,
            completed_at=None,
            work=None,
            delivery_status=None,
            delivery_error=None,
        )
        await states.save_execution(
            session, scope=scope, state=valid, expected_version=None
        )
        run = await runs.create(
            session,
            AgentRunCreate(
                session_id=scope.session_id,
                scheduled_task_cycle_id=None,
                parent_agent_run_id=None,
            ),
        )
        content = render_routine_execution_input((valid, stale), continuation=False)
        refs = (routine_execution_ref(valid), routine_execution_ref(stale))
        mailbox = await mailboxes.create_idempotent(
            session,
            MailboxItemCreate(
                session_id=scope.session_id,
                kind=MailboxItemKind.ROUTINE_TRIGGER,
                scheduling_mode=MailboxSchedulingMode.WAKE_SESSION,
                requested_model_target_label=None,
                requested_reasoning_effort=None,
                requested_enabled_execution_options=[],
                sender_user_id=None,
                order_group=None,
                order_sequence=0,
                content=content,
                idempotency_key="routine-fifo-test",
                metadata={},
                action=None,
                attachments=[],
                file_parts=[],
                payload=RoutineTriggerMailboxPayload(
                    type="routine_trigger",
                    executions=refs,
                    items=[
                        MailboxPresentationItem(
                            item_key="routine_trigger:0",
                            presentation_kind="routine_trigger",
                            content=content,
                        )
                    ],
                ),
            ),
            idempotency_key="routine-fifo-test",
        )
    outcome = await make_test_mailbox_promotion_repository(rdb_session_manager).promote(
        MailboxPromotionPlan(
            session_id=scope.session_id,
            owner_generation=0,
            expected_buffer_id=mailbox.id,
            active_run_id=run.id,
            consume_buffer=True,
            success_events=[
                MailboxPromotionEvent(
                    kind=EventKind.ROUTINE_TRIGGER,
                    payload=RoutineInputPayload(
                        executions=refs, content=content
                    ).model_dump(mode="json"),
                    external_id=f"{mailbox.id}:routine",
                    item_key="routine_trigger:0",
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
    assert outcome.deleted_buffer_ids == [mailbox.id]
    assert len(outcome.events) == 1
    payload = outcome.events[0].payload
    assert isinstance(payload, RoutineInputPayload)
    assert payload.executions == (routine_execution_ref(valid),)
    assert "removed-routine" not in payload.content
    assert valid.context.candidate.content.objective in payload.content
    async with rdb_session_manager() as session:
        restored = await states.get_execution(
            session, scope=scope, routine_id="routine-a"
        )
        assert restored is not None and restored.state.phase == "started"
        assert restored.state.context == valid.context
        assert restored.state.current_run_id == run.id
        assert restored.state.started_at is not None
        same_run = await runs.get_by_id(session, run.id)
        assert same_run is not None and same_run.status is AgentRunStatus.RUNNING
        assert same_run.id == run.id
        assert (
            await runs.get_active_by_session_id(session, session_id=scope.session_id)
            == same_run
        )
