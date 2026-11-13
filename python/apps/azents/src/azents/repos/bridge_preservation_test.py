"""Queued bridge retention uses the same exact sources as continuation promotion."""

from typing import Literal

import pytest
import sqlalchemy as sa
from azcommon.datetime import tznow

from azents.core.enums import AgentRunStatus, MailboxItemKind, MailboxSchedulingMode
from azents.core.mailbox_data import MailboxItemCreate
from azents.core.routine import RoutineScope
from azents.core.routine_execution_test import execution
from azents.core.routine_presentation import routine_execution_ref
from azents.core.work_context import WorkContext
from azents.rdb.models.agent_run import RDBAgentRun
from azents.rdb.models.agent_session import RDBAgentSession
from azents.rdb.models.conversation import RDBConversation
from azents.rdb.models.toolkit_state import RDBToolkitState
from azents.rdb.session_capabilities import WriteSession
from azents.repos.agent_execution import AgentRunRepository
from azents.repos.mailbox import MailboxRepository
from azents.repos.routine.preserved import preserved_routine_work_exists
from azents.repos.scheduled_task.lifecycle import ScheduledTaskLifecycleRepository
from azents.repos.scheduled_task.lifecycle_test import (
    _create_subject,
    _create_task_cycle,
)
from azents.repos.turn_action_work_context_test import _continuation


async def _queue_bridge(
    session: WriteSession, *, session_id: str, origin: str, predecessor: str
) -> None:
    await MailboxRepository().create(
        session,
        MailboxItemCreate(
            session_id=session_id,
            kind=MailboxItemKind.TURN_ACTION_CONTINUATION,
            scheduling_mode=MailboxSchedulingMode.WAKE_SESSION,
            requested_model_target_label=None,
            requested_reasoning_effort=None,
            requested_enabled_execution_options=[],
            sender_user_id=None,
            order_group=None,
            order_sequence=0,
            content="",
            metadata={},
            idempotency_key="bridge-preservation",
            action=None,
            attachments=[],
            file_parts=[],
            payload=_continuation(origin, predecessor),
        ),
    )


@pytest.mark.parametrize("carrier", ["origin", "predecessor"])
@pytest.mark.parametrize("valid", [True, False])
async def test_scheduled_bridge_preserves_both_validated_sources(
    rdb_session: WriteSession,
    carrier: Literal["origin", "predecessor"],
    valid: bool,
) -> None:
    subject = await _create_subject(
        rdb_session, handle=f"bridge-scheduled-{carrier}-{valid}"
    )
    admitted = await _create_task_cycle(
        rdb_session, subject=subject, title="Preserve exact cycle", started=True
    )
    assert admitted.run_id is not None
    origin = await rdb_session.read_session.get(RDBAgentRun, admitted.run_id)
    assert origin is not None
    carried = WorkContext.model_validate(origin.work_context)
    origin.status = AgentRunStatus.COMPLETED if valid else AgentRunStatus.CANCELLED
    if carrier == "predecessor":
        origin.work_context = WorkContext.empty().model_dump(mode="json")
    predecessor = await AgentRunRepository().create_pending(
        rdb_session,
        session_id=subject.session_id,
        parent_agent_run_id=None,
        work_context=carried if carrier == "predecessor" else WorkContext.empty(),
    )
    await AgentRunRepository().mark_terminal(
        rdb_session, predecessor.id, AgentRunStatus.CANCELLED, ended_at=tznow()
    )
    await _queue_bridge(
        rdb_session,
        session_id=subject.session_id,
        origin=origin.id,
        predecessor=predecessor.id,
    )
    await rdb_session.write_session.flush()
    assert (
        await ScheduledTaskLifecycleRepository().has_preservable_started_work(
            rdb_session, session_ids=(subject.session_id,)
        )
        is valid
    )


@pytest.mark.parametrize("carrier", ["origin", "predecessor"])
@pytest.mark.parametrize("other_context", ["empty", "ordinary", "scheduled"])
async def test_routine_bridge_retains_exact_work_without_mixed_archive_authority(
    rdb_session: WriteSession,
    carrier: Literal["origin", "predecessor"],
    other_context: Literal["empty", "ordinary", "scheduled"],
) -> None:
    subject = await _create_subject(
        rdb_session, handle=f"bridge-routine-{carrier}-{other_context}"
    )
    scope = RoutineScope(
        workspace_id=subject.workspace_id,
        agent_id=subject.agent_id,
        session_id=subject.session_id,
    )
    routine = execution(scope).model_copy(
        update={"phase": "started", "started_at": tznow()}
    )
    carried = WorkContext(
        scheduled_cycle_ids=(),
        routine_executions=(routine_execution_ref(routine),),
        unrelated_input=False,
    )
    other = WorkContext(
        scheduled_cycle_ids=("a" * 32,) if other_context == "scheduled" else (),
        routine_executions=(),
        unrelated_input=other_context == "ordinary",
    )
    rdb_session.write_session.add(
        RDBToolkitState(
            agent_id=scope.agent_id,
            session_id=scope.session_id,
            toolkit_namespace="routines",
            state_name=f"execution:{routine.context.candidate.routine_id}",
            state_json=routine.model_dump(mode="json"),
            schema_version=1,
        )
    )
    runs = AgentRunRepository()
    origin = await runs.create_pending(
        rdb_session,
        session_id=scope.session_id,
        parent_agent_run_id=None,
        work_context=carried if carrier == "origin" else other,
    )
    await runs.mark_terminal(
        rdb_session, origin.id, AgentRunStatus.COMPLETED, ended_at=tznow()
    )
    predecessor = await runs.create_pending(
        rdb_session,
        session_id=scope.session_id,
        parent_agent_run_id=None,
        work_context=carried if carrier == "predecessor" else other,
    )
    await runs.mark_terminal(
        rdb_session, predecessor.id, AgentRunStatus.CANCELLED, ended_at=tznow()
    )
    await _queue_bridge(
        rdb_session,
        session_id=scope.session_id,
        origin=origin.id,
        predecessor=predecessor.id,
    )
    conversation = await rdb_session.read_session.get(RDBConversation, scope.session_id)
    assert conversation is not None
    conversation.pending_idle_continuation_run_id = None
    await rdb_session.write_session.flush()
    result = await rdb_session.read_session.scalar(
        sa.select(preserved_routine_work_exists())
        .select_from(RDBAgentSession)
        .where(RDBAgentSession.id == scope.session_id)
    )
    assert result is (other_context == "empty")
