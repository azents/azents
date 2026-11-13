"""Real predecessor data preserves work through chained action continuations."""

import asyncio
import datetime
import json

import pytest
import sqlalchemy as sa
from alembic import command
from azcommon.uuid import uuid7
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import create_async_engine
from testcontainers.postgres import PostgresContainer

from azents.core.mailbox_data import GoalContinuationMailboxPayload
from azents.core.routine import RoutineScope
from azents.core.routine_execution import RoutineExecutionState
from azents.core.routine_execution_test import execution
from azents.core.routine_presentation import routine_execution_ref
from azents.core.work_context import WorkContext
from azents.rdb.models.toolkit_state import RDBToolkitState
from azents.rdb.session_capabilities import create_read_write_session_manager
from azents.repos.historical_memory_consolidation.execution_migration_test import (
    _create_predecessor_execution_subject,
)
from azents.services.scheduled_task.terminal_test import _cycle
from azents.testing.migration_database import isolated_migration_database


@pytest.mark.parametrize(
    ("ordinary_input", "retained_input", "prune_target", "boundary"),
    [
        (False, False, "none", "pending_goal"),
        (False, True, "none", "pending_goal"),
        (True, False, "none", "pending_goal"),
        (True, True, "none", "pending_goal"),
        (False, True, "latest", "running"),
        (False, True, "intermediate", "running"),
        (False, True, "intermediate", "idle"),
        (False, True, "intermediate", "pending_goal"),
        (False, True, "intermediate", "pending_action"),
        (False, True, "intermediate", "terminal"),
    ],
)
async def test_upgrade_retains_work_in_state_and_action_lineage(
    postgres_container: PostgresContainer,
    ordinary_input: bool,
    retained_input: bool,
    prune_target: str,
    boundary: str,
) -> None:
    with isolated_migration_database(postgres_container, template=None) as database:
        await asyncio.to_thread(command.upgrade, database.config, "2a9be235de5d")
        engine = create_async_engine(database.engine.url)
        manager = create_read_write_session_manager(engine)
        initial, created, removed, cycle_id, pending_id, second_cycle_id = (
            uuid7().hex for _ in range(6)
        )
        try:
            async with manager() as session:
                subject = await _create_predecessor_execution_subject(
                    session, handle=f"context-{uuid7().hex}"
                )
                session_id = subject.agent_session.id
                scope = RoutineScope(
                    workspace_id=subject.agent_session.workspace_id,
                    agent_id=subject.agent_id,
                    session_id=session_id,
                )
                state = execution(scope).model_copy(
                    update={
                        "phase": "started",
                        "started_at": datetime.datetime.now(datetime.UTC),
                    }
                )
                for index, run_id in enumerate((initial, created, removed), start=1):
                    await session.write_session.execute(
                        sa.text("""
                            INSERT INTO agent_runs(
                                id,session_id,run_index,status,phase,
                                scheduled_task_cycle_id
                            ) VALUES (:id,:session,:index,'completed','idle',:cycle)
                        """),
                        {
                            "id": run_id,
                            "session": session_id,
                            "index": index,
                            "cycle": cycle_id if run_id == initial else None,
                        },
                    )
                legacy_state = state.model_dump(mode="json")
                legacy_state["current_run_id"] = initial
                session.write_session.add(
                    RDBToolkitState(
                        agent_id=scope.agent_id,
                        session_id=session_id,
                        toolkit_namespace="routines",
                        state_name=f"execution:{state.context.candidate.routine_id}",
                        state_json=legacy_state,
                        schema_version=1,
                    )
                )
                scheduled_state = _cycle().state.model_dump(mode="json")
                scheduled_state.update(
                    cycle_id=second_cycle_id,
                    current_run_id=initial,
                    workspace_id=scope.workspace_id,
                    agent_id=scope.agent_id,
                    session_id=session_id,
                )
                session.write_session.add(
                    RDBToolkitState(
                        agent_id=scope.agent_id,
                        session_id=session_id,
                        toolkit_namespace="scheduled",
                        state_name=f"cycle:{second_cycle_id}",
                        state_json=scheduled_state,
                        schema_version=1,
                    )
                )
                session.write_session.add(
                    RDBToolkitState(
                        agent_id=scope.agent_id,
                        session_id=session_id,
                        toolkit_namespace="goal",
                        state_name="goal",
                        state_json={
                            "objective": "Preserve this Goal",
                            "status": "active",
                        },
                        schema_version=1,
                    )
                )
                for source, target in ((initial, created), (created, removed)):
                    action_id, event_id, reminder_id = (uuid7().hex for _ in range(3))
                    terminal = {
                        "action_execution": {
                            "execution": {"action": {"originating_run_id": source}}
                        }
                    }
                    for identity, kind, external_id, payload in (
                        (
                            event_id,
                            "action_execution_result",
                            f"action_execution_result:{action_id}",
                            terminal,
                        ),
                        (
                            reminder_id,
                            "system_reminder",
                            f"turn_action_continuation:{action_id}",
                            {"text": "The requested worktree action completed."},
                        ),
                    ):
                        if (
                            prune_target != "none"
                            and target
                            == (created if prune_target == "intermediate" else removed)
                            and kind == "action_execution_result"
                        ):
                            continue
                        await session.write_session.execute(
                            sa.text("""
                                INSERT INTO events(
                                    id,session_id,kind,payload,external_id)
                                VALUES (:id,:session,CAST(:kind AS event_kind),
                                        CAST(:payload AS jsonb),:external)
                            """),
                            {
                                "id": identity,
                                "session": session_id,
                                "kind": kind,
                                "payload": json.dumps(payload),
                                "external": external_id,
                            },
                        )
                    await session.write_session.execute(
                        sa.text("""
                            INSERT INTO agent_run_input_events(
                                agent_run_id,event_id,input_order
                            ) VALUES (:run,:event,0)
                        """),
                        {"run": target, "event": reminder_id},
                    )
                if ordinary_input or retained_input:
                    user_event = uuid7().hex
                    await session.write_session.execute(
                        sa.text("""
                            INSERT INTO events(id,session_id,kind,payload)
                            VALUES (:id,:session,CAST(:kind AS event_kind),'{}'::jsonb)
                        """),
                        {
                            "id": user_event,
                            "session": session_id,
                            "kind": "user_message"
                            if ordinary_input
                            else "routine_trigger",
                        },
                    )
                    await session.write_session.execute(
                        sa.text("""
                            INSERT INTO agent_run_input_events(
                                agent_run_id,event_id,input_order
                            ) VALUES (:run,:event,0)
                        """),
                        {"run": initial, "event": user_event},
                    )
                await session.write_session.execute(
                    sa.text("""
                        INSERT INTO mailbox_items(
                            id,session_id,kind,scheduling_mode,idempotency_key,
                            order_group,order_sequence,payload
                        ) VALUES (:id,:session,'goal_continuation','wake_session',
                                  :key,:id,0,CAST(:payload AS jsonb))
                    """),
                    {
                        "id": pending_id,
                        "session": session_id,
                        "key": f"idle_continuation:{removed}:goal:0",
                        "payload": json.dumps(
                            {
                                "type": "goal_continuation",
                                "items": [
                                    {
                                        "item_key": "goal_continuation:0",
                                        "presentation_kind": "goal_continuation",
                                        "content": "Continue the unfinished Goal.",
                                    }
                                ],
                            }
                        ),
                    },
                )
                if boundary != "pending_goal":
                    await session.write_session.execute(
                        sa.text("DELETE FROM mailbox_items WHERE id=:id"),
                        {"id": pending_id},
                    )
                if boundary == "running":
                    await session.write_session.execute(
                        sa.text("UPDATE agent_runs SET status='running' WHERE id=:id"),
                        {"id": removed},
                    )
                elif boundary == "idle":
                    await session.write_session.execute(
                        sa.text("""
                            UPDATE conversations
                            SET pending_idle_continuation_run_id=:run
                            WHERE session_id=:session
                        """),
                        {"run": removed, "session": session_id},
                    )
                elif boundary == "pending_action":
                    await session.write_session.execute(
                        sa.text("""
                            INSERT INTO mailbox_items(
                                id,session_id,kind,scheduling_mode,
                                order_group,order_sequence,payload
                            ) VALUES (
                                :id,:session,'turn_action_continuation',
                                'wake_session',:id,0,CAST(:payload AS jsonb)
                            )
                        """),
                        {
                            "id": pending_id,
                            "session": session_id,
                            "payload": json.dumps(
                                {
                                    "type": "turn_action_continuation",
                                    "predecessor_run_id": removed,
                                }
                            ),
                        },
                    )
                elif boundary == "terminal":
                    await session.write_session.execute(
                        sa.text(
                            "UPDATE agent_runs SET status='cancelled' WHERE id=:id"
                        ),
                        {"id": removed},
                    )
            if prune_target != "none" and boundary != "terminal":
                with pytest.raises(DBAPIError, match="canonical bridge provenance"):
                    await asyncio.to_thread(
                        command.upgrade, database.config, "090e27a51823"
                    )
                async with manager() as session:
                    columns = await session.read_session.scalars(
                        sa.text(
                            "SELECT column_name FROM information_schema.columns "
                            "WHERE table_name='agent_runs'"
                        )
                    )
                    names = set(columns)
                    assert "scheduled_task_cycle_id" in names
                    assert "work_context" not in names
                    goal = await session.read_session.scalar(
                        sa.select(RDBToolkitState).where(
                            RDBToolkitState.session_id == session_id,
                            RDBToolkitState.toolkit_namespace == "goal",
                        )
                    )
                    assert goal is not None
                    assert "goal_id" not in goal.state_json
                return
            await asyncio.to_thread(command.upgrade, database.config, "090e27a51823")
            async with manager() as session:
                for run_id in (initial, created, removed):
                    value = await session.read_session.scalar(
                        sa.text("SELECT work_context FROM agent_runs WHERE id=:id"),
                        {"id": run_id},
                    )
                    context = WorkContext.model_validate(value)
                    if boundary == "terminal" and run_id != initial:
                        assert context.scheduled_cycle_ids == ()
                        assert context.routine_executions == ()
                        continue
                    assert set(context.scheduled_cycle_ids) == {
                        cycle_id,
                        second_cycle_id,
                    }
                    assert context.routine_executions == (routine_execution_ref(state),)
                    assert context.unrelated_input is (
                        ordinary_input or not retained_input
                    )
                stored = await session.read_session.scalar(
                    sa.select(RDBToolkitState).where(
                        RDBToolkitState.session_id == session_id,
                        RDBToolkitState.toolkit_namespace == "routines",
                    )
                )
                assert stored is not None
                assert RoutineExecutionState.model_validate(stored.state_json) == state
                pending = await session.read_session.scalar(
                    sa.text("SELECT payload FROM mailbox_items WHERE id=:id"),
                    {"id": pending_id},
                )
                if boundary == "pending_goal":
                    assert (
                        GoalContinuationMailboxPayload.model_validate(
                            pending
                        ).source_run_id
                        == removed
                    )
            with pytest.raises(RuntimeError, match="irreversible"):
                await asyncio.to_thread(
                    command.downgrade, database.config, "2a9be235de5d"
                )
        finally:
            await engine.dispose()
