"""Scheduled Task terminal transaction tests."""

import datetime
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import NamedTuple
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    AgentRunStatus,
    EventKind,
    ExternalChannelWorkProjectionStatus,
    ScheduledTaskScheduleType,
)
from azents.engine.events.types import Event, ScheduledTaskResultPayload
from azents.rdb.session_capabilities import ReadSession, ReadWriteSession, WriteSession
from azents.repos.agent_execution import AgentRunRepository, EventTranscriptRepository
from azents.repos.agent_execution.data import AgentRunPatch, EventCreate
from azents.repos.scheduled_task.data import ScheduledTask
from azents.repos.scheduled_task.repository import ScheduledTaskRepository
from azents.repos.scheduled_task_cycle import ScheduledTaskCycleRepository
from azents.repos.scheduled_task_cycle.data import (
    ScheduledTaskCycleRecord,
    ScheduledTaskCycleState,
    ScheduledTrackerProjectionPart,
)
from azents.repos.scheduled_task_terminal_operations import (
    ScheduledTaskTerminalEffectSnapshot,
    ScheduledTaskTerminalOperations,
)
from azents.testing.types import require_instance

from .terminal import ScheduledTaskTerminalService

_NOW = datetime.datetime(2026, 8, 16, 12, 0, tzinfo=datetime.UTC)
_RUN_ID = "r" * 32
_CYCLE_ID = "c" * 32


@asynccontextmanager
async def _session_manager() -> AsyncIterator[WriteSession]:
    """Yield one transaction-shaped session double."""
    yield ReadWriteSession(require_instance(AsyncMock(spec=AsyncSession), AsyncSession))


def _cycle(*, binding_id: str | None = None) -> ScheduledTaskCycleRecord:
    """Build one started cycle record."""
    return ScheduledTaskCycleRecord(
        state=ScheduledTaskCycleState(
            cycle_id=_CYCLE_ID,
            task_id="t" * 32,
            phase="started",
            workspace_id="w" * 32,
            agent_id="a" * 32,
            session_id="s" * 32,
            binding_id=binding_id,
            title="Daily report",
            objective="Prepare the report.",
            schedule_type=ScheduledTaskScheduleType.ONCE,
            scheduled_at=_NOW,
            cron_expression=None,
            timezone=None,
            scheduled_for=_NOW,
            current_run_id=_RUN_ID,
            started_at=_NOW,
            progress_title="Preparing report…",
            ordered_tasks=["Collect data", "Write summary"],
            tracker_desired_revision=2,
            tracker_current_projection_parts=[
                ScheduledTrackerProjectionPart(
                    part_ordinal=0,
                    desired_revision=2,
                    status=ExternalChannelWorkProjectionStatus.PRESENT,
                    provider_message_key="slack:T1:C1:1.000001",
                )
            ],
        ),
        version=2,
        toolkit_state_id="k" * 32,
    )


def _task(
    schedule_type: ScheduledTaskScheduleType = ScheduledTaskScheduleType.ONCE,
) -> ScheduledTask:
    """Build one active Task fixture."""
    recurring = schedule_type is ScheduledTaskScheduleType.CRON
    return ScheduledTask(
        id="t" * 32,
        workspace_id="w" * 32,
        agent_id="a" * 32,
        session_id="s" * 32,
        binding_id=None,
        title="Daily report",
        objective="Prepare the report.",
        schedule_type=schedule_type,
        scheduled_at=None if recurring else _NOW,
        cron_expression="0 9 * * *" if recurring else None,
        timezone="UTC" if recurring else None,
        next_eligible_at=_NOW + datetime.timedelta(days=1),
        active_cycle_id=_CYCLE_ID,
        active_scheduled_for=_NOW,
        pending_scheduled_for=(
            _NOW + datetime.timedelta(hours=1) if recurring else None
        ),
        lease_owner=None,
        lease_until=None,
        created_at=_NOW,
        updated_at=_NOW,
    )


class _RunRepository:
    """Run repository double preserving terminal recovery fields."""

    def __init__(self, order: list[str]) -> None:
        self.order = order
        self.run = SimpleNamespace(
            session_id="s" * 32,
            status=AgentRunStatus.RUNNING,
            scheduled_task_cycle_id=_CYCLE_ID,
            terminal_result_event_id=None,
            terminal_result_message=None,
        )
        self.patches: list[AgentRunPatch] = []

    async def lock_by_id(
        self,
        session: ReadSession,
        run_id: str,
    ) -> SimpleNamespace:
        del session
        assert run_id == _RUN_ID
        self.order.append("lock_run")
        return self.run

    async def update(
        self,
        session: ReadSession,
        run_id: str,
        patch: AgentRunPatch,
    ) -> SimpleNamespace:
        del session
        assert run_id == _RUN_ID
        self.order.append("update_run")
        self.patches.append(patch)
        self.run.terminal_result_event_id = patch["terminal_result_event_id"]
        self.run.terminal_result_message = patch["terminal_result_message"]
        return self.run


class _EventRepository:
    """Event repository double with deterministic external identity."""

    def __init__(self, order: list[str], existing: Event | None = None) -> None:
        self.order = order
        self.existing = existing
        self.creates: list[EventCreate] = []

    async def get_by_external_id(
        self,
        session: ReadSession,
        session_id: str,
        external_id: str,
    ) -> Event | None:
        del session
        assert session_id == "s" * 32
        assert external_id == f"scheduled-task-result:{_CYCLE_ID}"
        self.order.append("get_event")
        return self.existing

    async def append(
        self,
        session: ReadSession,
        create: EventCreate,
    ) -> Event:
        del session
        self.order.append("append_event")
        self.creates.append(create)
        return Event(
            id="e" * 32,
            session_id=create.session_id,
            kind=create.kind,
            payload=ScheduledTaskResultPayload.model_validate(create.payload),
            external_id=create.external_id,
            created_at=_NOW,
        )


class _CycleRepository:
    """Cycle repository double enforcing the started snapshot."""

    def __init__(self, order: list[str], *, binding_id: str | None) -> None:
        self.order = order
        self.record = _cycle(binding_id=binding_id)
        self.deleted: list[ScheduledTaskCycleRecord] = []

    async def lock(
        self,
        session: ReadSession,
        *,
        agent_id: str,
        session_id: str,
        cycle_id: str,
    ) -> ScheduledTaskCycleRecord:
        del session
        assert (agent_id, session_id, cycle_id) == (
            "a" * 32,
            "s" * 32,
            _CYCLE_ID,
        )
        self.order.append("lock_cycle")
        return self.record

    async def delete_started(
        self,
        session: ReadSession,
        *,
        record: ScheduledTaskCycleRecord,
    ) -> bool:
        del session
        self.order.append("delete_cycle")
        self.deleted.append(record)
        return True


class _TaskRepository:
    """Task repository double recording one-time or recurring transition."""

    def __init__(self, order: list[str], task: ScheduledTask | None) -> None:
        self.order = order
        self.task = task
        self.deleted = False
        self.released = False

    async def lock_by_id(
        self,
        session: ReadSession,
        task_id: str,
    ) -> ScheduledTask | None:
        del session
        assert task_id == "t" * 32
        self.order.append("lock_task")
        return self.task

    async def delete_completed_once(
        self,
        session: ReadSession,
        *,
        task_id: str,
        cycle_id: str,
    ) -> bool:
        del session
        assert (task_id, cycle_id) == ("t" * 32, _CYCLE_ID)
        self.order.append("delete_task")
        self.deleted = True
        return True

    async def release_completed_recurring(
        self,
        session: ReadSession,
        *,
        task_id: str,
        cycle_id: str,
    ) -> bool:
        del session
        assert (task_id, cycle_id) == ("t" * 32, _CYCLE_ID)
        self.order.append("release_task")
        self.released = True
        return True


class _TerminalFixture(NamedTuple):
    """Terminal validation and observable repository collaborators."""

    service: ScheduledTaskTerminalService
    run_repository: _RunRepository
    event_repository: _EventRepository
    cycle_repository: _CycleRepository
    task_repository: _TaskRepository


def _service(
    *,
    order: list[str],
    task: ScheduledTask | None,
    existing_event: Event | None = None,
    binding_id: str | None = None,
) -> _TerminalFixture:
    """Compose complete operations from runtime-validated repository spec doubles."""
    run_repository = _RunRepository(order)
    event_repository = _EventRepository(order, existing_event)
    cycle_repository = _CycleRepository(order, binding_id=binding_id)
    task_repository = _TaskRepository(order, task)
    run_proxy = MagicMock(spec=AgentRunRepository)
    run_proxy.lock_by_id = AsyncMock(side_effect=run_repository.lock_by_id)
    run_proxy.update = AsyncMock(side_effect=run_repository.update)
    event_proxy = MagicMock(spec=EventTranscriptRepository)
    event_proxy.get_by_external_id = AsyncMock(
        side_effect=event_repository.get_by_external_id
    )
    event_proxy.append = AsyncMock(side_effect=event_repository.append)
    cycle_proxy = MagicMock(spec=ScheduledTaskCycleRepository)
    cycle_proxy.lock = AsyncMock(side_effect=cycle_repository.lock)
    cycle_proxy.delete_started = AsyncMock(side_effect=cycle_repository.delete_started)
    task_proxy = MagicMock(spec=ScheduledTaskRepository)
    task_proxy.lock_by_id = AsyncMock(side_effect=task_repository.lock_by_id)
    task_proxy.delete_completed_once = AsyncMock(
        side_effect=task_repository.delete_completed_once
    )
    task_proxy.release_completed_recurring = AsyncMock(
        side_effect=task_repository.release_completed_recurring
    )
    service = ScheduledTaskTerminalService(
        operations=ScheduledTaskTerminalOperations(
            session_manager=_session_manager,
            run_repository=require_instance(run_proxy, AgentRunRepository),
            event_repository=require_instance(event_proxy, EventTranscriptRepository),
            task_repository=require_instance(task_proxy, ScheduledTaskRepository),
            cycle_repository=require_instance(
                cycle_proxy, ScheduledTaskCycleRepository
            ),
        )
    )
    return _TerminalFixture(
        service, run_repository, event_repository, cycle_repository, task_repository
    )


async def test_submit_commits_event_cycle_and_once_task_before_run_completion() -> None:
    """One-time terminalization removes active state and stores recovery fields."""
    order: list[str] = []
    service, run_repository, event_repository, cycle_repository, task_repository = (
        _service(order=order, task=_task())
    )

    outcome = await service.submit(
        workspace_id="w" * 32,
        agent_id="a" * 32,
        session_id="s" * 32,
        run_id=_RUN_ID,
        status="finished",
        result="  Completed successfully.  ",
    )

    assert outcome.created is True
    assert outcome.effect_snapshot is None
    assert outcome.event.kind is EventKind.SCHEDULED_TASK_RESULT
    assert outcome.event.external_id == f"scheduled-task-result:{_CYCLE_ID}"
    assert outcome.event.payload == ScheduledTaskResultPayload(
        title="Daily report",
        scheduled_for=_NOW,
        status="finished",
        result="Completed successfully.",
    )
    assert order == [
        "lock_run",
        "get_event",
        "lock_cycle",
        "append_event",
        "delete_cycle",
        "lock_task",
        "delete_task",
        "update_run",
    ]
    assert len(event_repository.creates) == 1
    assert cycle_repository.deleted == [_cycle()]
    assert task_repository.deleted is True
    assert task_repository.released is False
    assert run_repository.run.terminal_result_event_id == "e" * 32
    assert run_repository.run.terminal_result_message == "Completed successfully."


async def test_submit_releases_recurring_task_for_pending_or_future_work() -> None:
    """Recurring terminalization clears the active fence through its repository."""
    order: list[str] = []
    service, _, _, _, task_repository = _service(
        order=order,
        task=_task(ScheduledTaskScheduleType.CRON),
    )

    await service.submit(
        workspace_id="w" * 32,
        agent_id="a" * 32,
        session_id="s" * 32,
        run_id=_RUN_ID,
        status="failed",
        result="Required authority is unavailable.",
    )

    assert task_repository.released is True
    assert task_repository.deleted is False
    assert "release_task" in order


async def test_submit_captures_channel_effect_snapshot_before_cycle_deletion() -> None:
    """A newly committed channel result retains one ordered process-local effect."""
    order: list[str] = []
    service, _, _, cycle_repository, _ = _service(
        order=order,
        task=None,
        binding_id="b" * 32,
    )

    outcome = await service.submit(
        workspace_id="w" * 32,
        agent_id="a" * 32,
        session_id="s" * 32,
        run_id=_RUN_ID,
        status="failed",
        result="  Provider authority is unavailable.  ",
    )

    assert outcome.effect_snapshot == ScheduledTaskTerminalEffectSnapshot(
        cycle_id=_CYCLE_ID,
        task_id="t" * 32,
        workspace_id="w" * 32,
        agent_id="a" * 32,
        session_id="s" * 32,
        binding_id="b" * 32,
        status="failed",
        result="Provider authority is unavailable.",
        tracker_desired_revision=2,
        tracker_projection_parts=(
            ScheduledTrackerProjectionPart(
                part_ordinal=0,
                desired_revision=2,
                status=ExternalChannelWorkProjectionStatus.PRESENT,
                provider_message_key="slack:T1:C1:1.000001",
            ),
        ),
    )
    assert cycle_repository.deleted == [_cycle(binding_id="b" * 32)]


async def test_submit_recovers_existing_canonical_event_without_retransition() -> None:
    """A crash-replayed terminal call returns the committed Event idempotently."""
    existing = Event(
        id="e" * 32,
        session_id="s" * 32,
        kind=EventKind.SCHEDULED_TASK_RESULT,
        payload=ScheduledTaskResultPayload(
            title="Daily report",
            scheduled_for=_NOW,
            status="finished",
            result="Canonical result.",
        ),
        external_id=f"scheduled-task-result:{_CYCLE_ID}",
        created_at=_NOW,
    )
    order: list[str] = []
    service, run_repository, event_repository, cycle_repository, task_repository = (
        _service(order=order, task=None, existing_event=existing)
    )

    outcome = await service.submit(
        workspace_id="w" * 32,
        agent_id="a" * 32,
        session_id="s" * 32,
        run_id=_RUN_ID,
        status="failed",
        result="A different replayed value.",
    )

    assert outcome.created is False
    assert outcome.event == existing
    assert outcome.effect_snapshot is None
    assert order == ["lock_run", "get_event", "update_run"]
    assert event_repository.creates == []
    assert cycle_repository.deleted == []
    assert task_repository.deleted is False
    assert task_repository.released is False
    assert run_repository.run.terminal_result_event_id == existing.id
    assert run_repository.run.terminal_result_message == "Canonical result."


@pytest.mark.parametrize("result", ["", "  ", "\n\t"])
async def test_empty_result_does_not_enter_terminal_transaction(result: str) -> None:
    """Text validation completes before any terminal persistence operation."""
    order: list[str] = []
    fixture = _service(order=order, task=_task())
    with pytest.raises(ValueError, match="result must not be empty"):
        await fixture.service.submit(
            workspace_id="w" * 32,
            agent_id="a" * 32,
            session_id="s" * 32,
            run_id=_RUN_ID,
            status="finished",
            result=result,
        )
    assert order == []


async def test_transaction_completion_precedes_caller_dispatch() -> None:
    """Canonical terminal mutation completes before outward caller publication."""
    order: list[str] = []
    fixture = _service(order=order, task=_task())

    @asynccontextmanager
    async def manager() -> AsyncIterator[WriteSession]:
        order.append("begin")
        yield ReadWriteSession(
            require_instance(AsyncMock(spec=AsyncSession), AsyncSession)
        )
        order.append("commit")

    fixture.service.operations.session_manager = manager
    outcome = await fixture.service.submit(
        workspace_id="w" * 32,
        agent_id="a" * 32,
        session_id="s" * 32,
        run_id=_RUN_ID,
        status="finished",
        result="Finished",
    )
    assert outcome.created
    order.append("provider_dispatch")
    assert order[0] == "begin"
    assert order[-2:] == ["commit", "provider_dispatch"]
