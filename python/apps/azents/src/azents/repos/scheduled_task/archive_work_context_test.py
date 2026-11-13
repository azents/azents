"""Scheduled archive exceptions preserve only unmixed admitted work."""

from typing import Literal

import pytest

from azents.core.enums import AgentRunStatus, MailboxItemKind, MailboxSchedulingMode
from azents.core.mailbox_data import (
    MailboxItemCreate,
    MailboxPresentationItem,
    ScheduledTaskContinuationMailboxPayload,
)
from azents.core.routine_execution import RoutineExecutionRef
from azents.core.work_context import WorkContext
from azents.rdb.models.agent_run import RDBAgentRun
from azents.rdb.models.conversation import RDBConversation
from azents.rdb.session_capabilities import WriteSession
from azents.repos.mailbox import MailboxRepository
from azents.repos.scheduled_task.lifecycle import ScheduledTaskLifecycleRepository
from azents.repos.scheduled_task.lifecycle_test import (
    _create_subject,
    _create_task_cycle,
)


@pytest.mark.parametrize("mixed", ["none", "ordinary", "routine"])
@pytest.mark.parametrize("boundary", ["active", "idle", "mailbox"])
async def test_archive_requires_scheduled_only_context_at_every_boundary(
    rdb_session: WriteSession,
    mixed: Literal["none", "ordinary", "routine"],
    boundary: Literal["active", "idle", "mailbox"],
) -> None:
    subject = await _create_subject(rdb_session, handle=f"archive-{boundary}-{mixed}")
    admitted = await _create_task_cycle(
        rdb_session,
        subject=subject,
        title="Preserved Scheduled work",
        started=True,
    )
    assert admitted.run_id is not None
    run = await rdb_session.read_session.get(RDBAgentRun, admitted.run_id)
    assert run is not None
    context = WorkContext(
        scheduled_cycle_ids=(admitted.cycle.state.cycle_id,),
        routine_executions=(
            RoutineExecutionRef(
                routine_id="unrelated-definition",
                execution_id="unrelated-occurrence",
                slug="unrelated",
                title="Independent Routine work",
            ),
        )
        if mixed == "routine"
        else (),
        unrelated_input=mixed == "ordinary",
    )
    run.work_context = context.model_dump(mode="json")
    if boundary != "active":
        run.status = AgentRunStatus.COMPLETED
    if boundary == "idle":
        conversation = await rdb_session.read_session.get(
            RDBConversation, subject.session_id
        )
        assert conversation is not None
        conversation.pending_idle_continuation_run_id = run.id
    elif boundary == "mailbox":
        await MailboxRepository().create(
            rdb_session,
            MailboxItemCreate(
                session_id=subject.session_id,
                kind=MailboxItemKind.SCHEDULED_TASK_CONTINUATION,
                scheduling_mode=MailboxSchedulingMode.WAKE_SESSION,
                requested_model_target_label=None,
                requested_reasoning_effort=None,
                requested_enabled_execution_options=[],
                sender_user_id=None,
                order_group=None,
                order_sequence=0,
                content="",
                metadata={},
                idempotency_key=f"idle_continuation:{run.id}:scheduled:0",
                action=None,
                attachments=[],
                file_parts=[],
                payload=ScheduledTaskContinuationMailboxPayload(
                    type="scheduled_task_continuation",
                    source_run_id=run.id,
                    cycle_id=admitted.cycle.state.cycle_id,
                    items=[
                        MailboxPresentationItem(
                            item_key="scheduled_task_continuation:0",
                            presentation_kind="scheduled_task_continuation",
                            content="Continue exact Scheduled work.",
                            metadata={"title": "Preserved Scheduled work"},
                        )
                    ],
                ),
            ),
        )
    await rdb_session.write_session.flush()
    allowed = await ScheduledTaskLifecycleRepository().archive_allows_active_runs(
        rdb_session,
        session_ids=(subject.session_id,),
        running_session_ids=(subject.session_id,),
    )
    assert allowed is (mixed == "none")
    await rdb_session.write_session.refresh(run)
    assert WorkContext.model_validate(run.work_context) == context
