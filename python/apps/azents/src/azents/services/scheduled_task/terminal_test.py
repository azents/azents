"""Scheduled Task terminal transaction tests."""

import datetime
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import cast

from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    AgentRunStatus,
    EventKind,
    ExternalChannelWorkProjectionStatus,
    ScheduledTaskScheduleType,
)
from azents.engine.events.types import Event, ScheduledTaskResultPayload
from azents.rdb.session import SessionManager
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

from .terminal import (
    ScheduledTaskTerminalEffectSnapshot,
    ScheduledTaskTerminalService,
)

_NOW = datetime.datetime(2026, 8, 16, 12, 0, tzinfo=datetime.UTC)
_RUN_ID = "r" * 32
_CYCLE_ID = "c" * 32


@asynccontextmanager
async def _session_manager() -> AsyncIterator[AsyncSession]:
    """Yield one transaction-shaped session double."""
    yield cast(AsyncSession, object())


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
        session: AsyncSession,
        run_id: str,
    ) -> SimpleNamespace:
        del session
        assert run_id == _RUN_ID
        self.order.append("lock_run")
        return self.run

    async def update(
        self,
        session: AsyncSession,
        run_id: str,
        patch: AgentRunPatch,
    ) -> SimpleNamespace:
        del session
        assert run_id == _RUN_ID
        self.order.append("update_run")
        self.patches.append(patch)
        self.run.terminal_result_event_id = patch.terminal_result_event_id
        self.run.terminal_result_message = patch.terminal_result_message
        return self.run


class _EventRepository:
    """Event repository double with deterministic external identity."""

    def __init__(self, order: list[str], existing: Event | None = None) -> None:
        self.order = order
        self.existing = existing
        self.creates: list[EventCreate] = []

    async def get_by_external_id(
        self,
        session: AsyncSession,
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
        session: AsyncSession,
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
        session: AsyncSession,
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
        session: AsyncSession,
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
        session: AsyncSession,
        task_id: str,
    ) -> ScheduledTask | None:
        del session
        assert task_id == "t" * 32
        self.order.append("lock_task")
        return self.task

    async def delete_completed_once(
        self,
        session: AsyncSession,
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
        session: AsyncSession,
        *,
        task_id: str,
        cycle_id: str,
    ) -> bool:
        del session
        assert (task_id, cycle_id) == ("t" * 32, _CYCLE_ID)
        self.order.append("release_task")
        self.released = True
        return True


def _service(
    *,
    order: list[str],
    task: ScheduledTask | None,
    existing_event: Event | None = None,
    binding_id: str | None = None,
) -> tuple[
    ScheduledTaskTerminalService,
    _RunRepository,
    _EventRepository,
    _CycleRepository,
    _TaskRepository,
]:
    """Compose the terminal service from assertion-visible doubles."""
    run_repository = _RunRepository(order)
    event_repository = _EventRepository(order, existing_event)
    cycle_repository = _CycleRepository(order, binding_id=binding_id)
    task_repository = _TaskRepository(order, task)
    service = ScheduledTaskTerminalService(
        session_manager=cast(SessionManager[AsyncSession], _session_manager),
        run_repository=cast(AgentRunRepository, run_repository),
        event_repository=cast(EventTranscriptRepository, event_repository),
        task_repository=cast(ScheduledTaskRepository, task_repository),
        cycle_repository=cast(ScheduledTaskCycleRepository, cycle_repository),
    )
    return (
        service,
        run_repository,
        event_repository,
        cycle_repository,
        task_repository,
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
