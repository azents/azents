"""Public archive composes pure Scheduled/Routine exceptions without laundering."""

import datetime
from typing import Literal

import pytest
import sqlalchemy as sa
from azcommon.result import Failure, Success
from azcommon.uuid import uuid7

from azents.core.chat_data import RunningSessionArchiveBlocked
from azents.core.enums import AgentRunStatus, MailboxItemKind, MailboxSchedulingMode
from azents.core.mailbox_data import (
    MailboxItemCreate,
    MailboxPresentationItem,
    RoutineContinuationMailboxPayload,
)
from azents.core.routine_presentation import routine_execution_ref
from azents.core.work_context import WorkContext
from azents.rdb.models.agent_run import RDBAgentRun
from azents.rdb.models.toolkit_state import RDBToolkitState
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import WriteSession
from azents.repos.mailbox import MailboxRepository
from azents.repos.routine.completion_test import fixture
from azents.repos.routine.lifecycle_test import _attach_routine_input
from azents.repos.scheduled_task.lifecycle_test import _create_task_cycle, _Subject
from azents.services.chat.team_session_test import _service
from azents.services.scheduled_task.terminal_test import _cycle


@pytest.mark.parametrize(
    ("mixed", "boundary"),
    [
        ("none", "idle"),
        ("none", "routine_mailbox"),
        ("scheduled", "idle"),
        ("ordinary", "idle"),
        ("scheduled", "routine_mailbox"),
        ("ordinary", "routine_mailbox"),
        ("scheduled", "idle_with_fresh_trigger"),
        ("ordinary", "idle_with_fresh_trigger"),
    ],
)
async def test_public_archive_rejects_mixed_idle_and_continuation_sources(
    rdb_session_manager: SessionManager[WriteSession],
    mixed: Literal["none", "scheduled", "ordinary"],
    boundary: Literal["idle", "routine_mailbox", "idle_with_fresh_trigger"],
) -> None:
    f = await fixture(rdb_session_manager)
    await _attach_routine_input(rdb_session_manager, f)
    cycle_id = uuid7().hex
    async with rdb_session_manager() as session:
        run = await session.read_session.get(RDBAgentRun, f.authority.run_id)
        assert run is not None
        context = WorkContext.model_validate(run.work_context).model_copy(
            update={
                "scheduled_cycle_ids": (cycle_id,) if mixed == "scheduled" else (),
                "unrelated_input": mixed == "ordinary",
            }
        )
        run.work_context = context.model_dump(mode="json")
        if mixed == "scheduled":
            state = _cycle().state.model_copy(
                update={
                    "cycle_id": cycle_id,
                    "workspace_id": f.scope.workspace_id,
                    "agent_id": f.scope.agent_id,
                    "session_id": f.scope.session_id,
                }
            )
            session.write_session.add(
                RDBToolkitState(
                    agent_id=f.scope.agent_id,
                    session_id=f.scope.session_id,
                    toolkit_namespace="scheduled",
                    state_name=f"cycle:{cycle_id}",
                    state_json=state.model_dump(mode="json"),
                    schema_version=1,
                )
            )
        await f.repository.runs.mark_terminal(
            session,
            run.id,
            AgentRunStatus.COMPLETED,
            ended_at=datetime.datetime.now(datetime.UTC),
        )
        if boundary == "routine_mailbox":
            # Consume the idle pointer as the normal worker would before enqueue.
            await session.write_session.execute(
                sa.text(
                    "UPDATE conversations SET pending_idle_continuation_run_id=NULL "
                    "WHERE session_id=:id"
                ),
                {"id": f.scope.session_id},
            )
            await MailboxRepository().create(
                session,
                MailboxItemCreate(
                    session_id=f.scope.session_id,
                    kind=MailboxItemKind.ROUTINE_CONTINUATION,
                    scheduling_mode=MailboxSchedulingMode.WAKE_SESSION,
                    requested_model_target_label=None,
                    requested_reasoning_effort=None,
                    requested_enabled_execution_options=[],
                    sender_user_id=None,
                    order_group=None,
                    order_sequence=0,
                    content="",
                    metadata={},
                    idempotency_key=f"idle_continuation:{run.id}:routine:0",
                    action=None,
                    attachments=[],
                    file_parts=[],
                    payload=RoutineContinuationMailboxPayload(
                        type="routine_continuation",
                        source_run_id=run.id,
                        executions=tuple(routine_execution_ref(s) for s in f.states),
                        items=[
                            MailboxPresentationItem(
                                item_key="routine_continuation:0",
                                presentation_kind="routine_continuation",
                                content="Continue the admitted Routine work.",
                            )
                        ],
                    ),
                ),
            )
        elif boundary == "idle_with_fresh_trigger":
            await _create_task_cycle(
                session,
                subject=_Subject(
                    workspace_id=f.scope.workspace_id,
                    agent_id=f.scope.agent_id,
                    session_id=f.scope.session_id,
                ),
                title="New unrelated scheduled trigger",
                started=False,
            )
    result = await _service(rdb_session_manager).operations.archive_agent_session(
        agent_id=f.scope.agent_id,
        session_id=f.scope.session_id,
        user_id=None,
    )
    if mixed == "none":
        assert isinstance(result, Success), result
    else:
        assert isinstance(result, Failure)
        assert isinstance(result.error, RunningSessionArchiveBlocked)
        async with rdb_session_manager() as session:
            states = await f.repository.states.list_executions(session, scope=f.scope)
            assert len(states) == 2
            assert all(item.state.phase == "started" for item in states)
