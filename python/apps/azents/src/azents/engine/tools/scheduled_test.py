"""Scheduled Task Toolkit tests."""

import datetime
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock

from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import EventKind, ScheduledTaskScheduleType
from azents.core.tools import TurnContext
from azents.engine.events.types import Event, ScheduledTaskResultPayload
from azents.engine.hooks.types import (
    CompactionSummaryHookContext,
    CompactionSummaryReplace,
    ScheduledTaskSessionContinuationInput,
    SessionIdleHookContext,
)
from azents.engine.run.types import FunctionToolResult
from azents.rdb.session import SessionManager
from azents.repos.agent_execution import AgentRunRepository
from azents.repos.scheduled_task.data import ScheduledTask
from azents.repos.scheduled_task_cycle import ScheduledTaskCycleRepository
from azents.repos.scheduled_task_cycle.data import (
    ScheduledTaskCycleRecord,
    ScheduledTaskCycleState,
)
from azents.services.scheduled_task.channel import ScheduledTaskChannelService
from azents.services.scheduled_task.service import ScheduledTaskService
from azents.services.scheduled_task.terminal import (
    ScheduledTaskTerminalOutcome,
    ScheduledTaskTerminalService,
)

from .scheduled import ScheduledToolkit

_NOW = datetime.datetime(2026, 8, 16, 12, 0, tzinfo=datetime.UTC)
_RUN_ID = "r" * 32
_CYCLE_ID = "c" * 32


@asynccontextmanager
async def _session_manager() -> AsyncIterator[AsyncSession]:
    """Yield one non-persistent Toolkit test session."""
    yield cast(AsyncSession, object())


def _cycle(
    *,
    cycle_id: str = _CYCLE_ID,
    run_id: str = _RUN_ID,
    scheduled_for: datetime.datetime = _NOW,
) -> ScheduledTaskCycleRecord:
    """Build one started cycle record."""
    return ScheduledTaskCycleRecord(
        state=ScheduledTaskCycleState(
            cycle_id=cycle_id,
            task_id="t" * 32,
            phase="started",
            workspace_id="w" * 32,
            agent_id="a" * 32,
            session_id="s" * 32,
            binding_id=None,
            title="Daily report",
            objective="Prepare the report.",
            schedule_type=ScheduledTaskScheduleType.ONCE,
            scheduled_at=_NOW,
            cron_expression=None,
            timezone=None,
            scheduled_for=scheduled_for,
            current_run_id=run_id,
            started_at=_NOW,
            progress_title=None,
        ),
        version=2,
        toolkit_state_id="k" * 32,
    )


def _task(*, active_cycle_id: str | None = None) -> ScheduledTask:
    """Build one Task management projection fixture."""
    return ScheduledTask(
        id="t" * 32,
        workspace_id="w" * 32,
        agent_id="a" * 32,
        session_id="s" * 32,
        binding_id=None,
        title="Daily report",
        objective="Prepare the report.",
        schedule_type=ScheduledTaskScheduleType.ONCE,
        scheduled_at=_NOW,
        cron_expression=None,
        timezone=None,
        next_eligible_at=_NOW,
        active_cycle_id=active_cycle_id,
        active_scheduled_for=_NOW if active_cycle_id else None,
        pending_scheduled_for=None,
        lease_owner=None,
        lease_until=None,
        created_at=_NOW,
        updated_at=_NOW,
    )


def _toolkit(
    *,
    active_cycle: ScheduledTaskCycleRecord | None,
) -> tuple[ScheduledToolkit, AsyncMock, AsyncMock, AsyncMock, AsyncMock]:
    """Compose one Toolkit with assertion-visible collaborators."""
    service = AsyncMock()
    terminal_service = AsyncMock()
    channel_service = AsyncMock()
    channel_service.execute_registration.return_value = None
    channel_service.execute_terminal.return_value = ()
    cycle_repository = AsyncMock()
    run_repository = AsyncMock()
    run_repository.get_by_id.return_value = SimpleNamespace(
        session_id="s" * 32,
        scheduled_task_cycle_id=(
            active_cycle.state.cycle_id if active_cycle is not None else None
        ),
    )
    cycle_repository.get_started.return_value = active_cycle
    toolkit = ScheduledToolkit(
        session_manager=cast(SessionManager[AsyncSession], _session_manager),
        service=cast(ScheduledTaskService, service),
        terminal_service=cast(ScheduledTaskTerminalService, terminal_service),
        channel_service=cast(ScheduledTaskChannelService, channel_service),
        cycle_repository=cast(ScheduledTaskCycleRepository, cycle_repository),
        run_repository=cast(AgentRunRepository, run_repository),
        workspace_id="w" * 32,
        agent_id="a" * 32,
        session_id="s" * 32,
    )
    return (
        toolkit,
        service,
        terminal_service,
        cycle_repository,
        run_repository,
    )


def _turn_context(publish_event: AsyncMock | None = None) -> TurnContext:
    """Build one run-bound Toolkit context."""
    return TurnContext(
        workspace_id="w" * 32,
        model="model",
        run_id=_RUN_ID,
        session_id="s" * 32,
        publish_event=publish_event or AsyncMock(),
    )


async def test_toolkit_exposes_management_tools_and_valid_cycle_terminal_tool() -> None:
    """The terminal action is bound only to the current started cycle."""
    management, *_ = _toolkit(active_cycle=None)
    management_state = await management.update_context(_turn_context())
    active, *_ = _toolkit(active_cycle=_cycle())
    active_state = await active.update_context(_turn_context())

    assert [tool.spec.name for tool in management_state.tools] == [
        "add_scheduled_task",
        "list_scheduled_tasks",
        "delete_scheduled_task",
    ]
    assert [tool.spec.name for tool in active_state.tools] == [
        "add_scheduled_task",
        "list_scheduled_tasks",
        "delete_scheduled_task",
        "submit_scheduled_task_result",
    ]
    assert await management.get_dynamic_prompt(_turn_context()) == ""
    assert "Active Scheduled Task Work Cycle" in await active.get_dynamic_prompt(
        _turn_context()
    )

    add_schema_json = json.dumps(management_state.tools[0].spec.input_schema)
    assert "Set cron and timezone to null" in add_schema_json
    assert "requires at to be null" in add_schema_json
    assert "Must be null when at is supplied" in add_schema_json


async def test_management_tools_derive_scope_and_project_execution_state() -> None:
    """Management actions use exact current Workspace, Agent, and Session scope."""
    toolkit, service, _, cycle_repository, _ = _toolkit(active_cycle=None)
    created = _task()
    running = _task(active_cycle_id=_CYCLE_ID)
    service.create.return_value = created
    service.list_tasks.return_value = [running]
    service.delete.return_value = True
    cycle_repository.get.return_value = _cycle()
    state = await toolkit.update_context(_turn_context())
    tools = {tool.spec.name: tool for tool in state.tools}

    added_result = await tools["add_scheduled_task"].handler(
        json.dumps(
            {
                "title": "Daily report",
                "objective": "Prepare the report.",
                "at": "2026-08-16T12:00:00Z",
                "cron": None,
                "timezone": None,
                "channel_id": None,
            }
        )
    )
    listed_result = await tools["list_scheduled_tasks"].handler("{}")
    deleted_result = await tools["delete_scheduled_task"].handler(
        json.dumps({"task_id": "t" * 32})
    )
    assert isinstance(added_result, str)
    assert isinstance(listed_result, str)
    assert isinstance(deleted_result, str)
    added = json.loads(added_result)
    listed = json.loads(listed_result)
    deleted = json.loads(deleted_result)

    assert added["created"] is True
    assert added["registration"] is None
    service.create.assert_awaited_once()
    _, create_kwargs = service.create.await_args
    assert create_kwargs["workspace_id"] == "w" * 32
    assert create_kwargs["agent_id"] == "a" * 32
    assert create_kwargs["session_id"] == "s" * 32
    assert listed["tasks"][0]["execution_state"] == "running"
    service.list_tasks.assert_awaited_once()
    assert deleted == {"deleted": True, "task_id": "t" * 32}
    service.delete.assert_awaited_once()
    _, delete_kwargs = service.delete.await_args
    assert delete_kwargs == {
        "session_id": "s" * 32,
        "task_id": "t" * 32,
    }


async def test_terminal_tool_publishes_new_event_and_requests_run_completion() -> None:
    """A canonical terminal outcome becomes an engine-terminal tool result."""
    toolkit, _, terminal_service, _, _ = _toolkit(active_cycle=_cycle())
    publish_event = AsyncMock()
    event = Event(
        id="e" * 32,
        session_id="s" * 32,
        kind=EventKind.SCHEDULED_TASK_RESULT,
        payload=ScheduledTaskResultPayload(
            title="Daily report",
            scheduled_for=_NOW,
            status="finished",
            result="Completed.",
        ),
        external_id=f"scheduled-task-result:{_CYCLE_ID}",
        created_at=_NOW,
    )
    terminal_service.submit.return_value = ScheduledTaskTerminalOutcome(
        event=event,
        created=True,
        effect_snapshot=None,
    )
    state = await toolkit.update_context(_turn_context(publish_event))
    terminal_tool = state.tools[-1]

    result = await terminal_tool.handler(
        json.dumps({"status": "finished", "result": "Completed."})
    )

    assert isinstance(result, FunctionToolResult)
    assert result.terminal_run is True
    assert json.loads(cast(str, result.output)) == {
        "outcomes": [],
        "recovered": False,
        "result": "Completed.",
        "status": "finished",
    }
    publish_event.assert_awaited_once_with(event)
    terminal_service.submit.assert_awaited_once_with(
        workspace_id="w" * 32,
        agent_id="a" * 32,
        session_id="s" * 32,
        run_id=_RUN_ID,
        status="finished",
        result="Completed.",
    )


async def test_idle_and_compaction_hooks_use_all_started_cycles_in_order() -> None:
    """Toolkit continuity hooks project every current started cycle."""
    toolkit, _, _, cycle_repository, _ = _toolkit(active_cycle=None)
    first = _cycle(cycle_id="a" * 32, scheduled_for=_NOW)
    second = _cycle(
        cycle_id="b" * 32,
        scheduled_for=_NOW + datetime.timedelta(minutes=1),
    )
    cycle_repository.list_started.return_value = [first, second]
    hooks = toolkit.hooks()
    idle_hook = hooks["on_session_idle"]
    compaction_hook = hooks["on_compaction_summary"]

    idle = await idle_hook(
        SessionIdleHookContext(
            workspace_id="w" * 32,
            agent_id="a" * 32,
            session_id="s" * 32,
            run_id=_RUN_ID,
            reason="completed",
        )
    )
    compaction = await compaction_hook(
        CompactionSummaryHookContext(
            workspace_id="w" * 32,
            agent_id="a" * 32,
            session_id="s" * 32,
            run_id=_RUN_ID,
            compaction_id="p" * 32,
            reason="threshold",
            covered_until_event_id="e" * 32,
            summary="Existing summary",
            continuity_history="",
        )
    )

    assert idle is not None
    assert all(
        isinstance(item, ScheduledTaskSessionContinuationInput)
        for item in idle.continuations
    )
    scheduled_continuations = [
        item
        for item in idle.continuations
        if isinstance(item, ScheduledTaskSessionContinuationInput)
    ]
    assert [item.cycle_id for item in scheduled_continuations] == [
        "a" * 32,
        "b" * 32,
    ]
    assert all("cycle_id" not in item.content for item in idle.continuations)
    assert isinstance(compaction, CompactionSummaryReplace)
    assert compaction.summary.count("### Cycle ") == 2
    assert "a" * 32 not in compaction.summary
    assert "b" * 32 not in compaction.summary
