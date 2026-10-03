"""Completed scheduled terminal result database operations."""

import dataclasses
from typing import Annotated, Literal

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import AgentRunStatus, EventKind, ScheduledTaskScheduleType
from azents.core.session_resource_authority import SessionExecutionOwner
from azents.engine.events.types import Event, ScheduledTaskResultPayload
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.agent_execution import AgentRunRepository, EventTranscriptRepository
from azents.repos.agent_execution.data import AgentRunPatch, EventCreate
from azents.repos.scheduled_task.repository import ScheduledTaskRepository
from azents.repos.scheduled_task_cycle import ScheduledTaskCycleRepository
from azents.repos.scheduled_task_cycle.data import ScheduledTrackerProjectionPart
from azents.repos.session_execution.ownership import OwnerBoundSessionManager

ScheduledTaskTerminalStatus = Literal["finished", "failed"]


@dataclasses.dataclass(frozen=True)
class ScheduledTaskTerminalEffectSnapshot:
    """Process-local provider publication authority captured before cycle deletion."""

    cycle_id: str
    task_id: str
    workspace_id: str
    agent_id: str
    session_id: str
    binding_id: str
    status: ScheduledTaskTerminalStatus
    result: str
    tracker_desired_revision: int
    tracker_projection_parts: tuple[ScheduledTrackerProjectionPart, ...]


@dataclasses.dataclass(frozen=True)
class ScheduledTaskTerminalOutcome:
    """Canonical terminal result and whether this call created it."""

    event: Event
    created: bool
    effect_snapshot: ScheduledTaskTerminalEffectSnapshot | None


class ScheduledTaskTerminalOperations:
    """Commit one run-bound Scheduled Task terminal result idempotently."""

    def __init__(
        self,
        *,
        session_manager: SessionManager[AsyncSession],
        run_repository: AgentRunRepository,
        event_repository: EventTranscriptRepository,
        task_repository: ScheduledTaskRepository,
        cycle_repository: ScheduledTaskCycleRepository,
    ) -> None:
        self.session_manager = session_manager
        self.run_repository = run_repository
        self.event_repository = event_repository
        self.task_repository = task_repository
        self.cycle_repository = cycle_repository

    def for_execution(
        self,
        owner: SessionExecutionOwner,
    ) -> "ScheduledTaskTerminalOperations":
        """Bind terminal persistence to one durable Session owner."""
        return ScheduledTaskTerminalOperations(
            session_manager=OwnerBoundSessionManager(
                session_manager=self.session_manager,
                session_id=owner.session_id,
                owner_generation=owner.owner_generation,
            ),
            run_repository=self.run_repository,
            event_repository=self.event_repository,
            task_repository=self.task_repository,
            cycle_repository=self.cycle_repository,
        )

    async def submit(
        self,
        *,
        workspace_id: str,
        agent_id: str,
        session_id: str,
        run_id: str,
        status: ScheduledTaskTerminalStatus,
        result: str,
    ) -> ScheduledTaskTerminalOutcome:
        """Commit the canonical Event and cycle/Task transition once."""
        normalized_result = result

        async with self.session_manager() as session:
            run = await self.run_repository.lock_by_id(session, run_id)
            if (
                run is None
                or run.session_id != session_id
                or run.status is not AgentRunStatus.RUNNING
                or run.scheduled_task_cycle_id is None
            ):
                raise ValueError(
                    "The current AgentRun is not an active Scheduled Task cycle."
                )
            cycle_id = run.scheduled_task_cycle_id
            external_id = _result_external_id(cycle_id)
            existing = await self.event_repository.get_by_external_id(
                session,
                session_id,
                external_id,
            )
            if existing is not None:
                payload = existing.payload
                if not isinstance(payload, ScheduledTaskResultPayload):
                    raise RuntimeError(
                        "Scheduled Task terminal Event identity is inconsistent."
                    )
                if run.terminal_result_event_id is None:
                    await self.run_repository.update(
                        session,
                        run_id,
                        AgentRunPatch(
                            terminal_result_event_id=existing.id,
                            terminal_result_message=payload.result,
                        ),
                    )
                return ScheduledTaskTerminalOutcome(
                    event=existing,
                    created=False,
                    effect_snapshot=None,
                )

            cycle = await self.cycle_repository.lock(
                session,
                agent_id=agent_id,
                session_id=session_id,
                cycle_id=cycle_id,
            )
            if (
                cycle is None
                or cycle.state.phase != "started"
                or cycle.state.workspace_id != workspace_id
                or cycle.state.agent_id != agent_id
                or cycle.state.session_id != session_id
                or cycle.state.current_run_id != run_id
            ):
                raise ValueError(
                    "The current AgentRun has no matching started Scheduled Task cycle."
                )

            payload = ScheduledTaskResultPayload(
                title=cycle.state.title,
                scheduled_for=cycle.state.scheduled_for,
                status=status,
                result=normalized_result,
            )
            effect_snapshot = (
                None
                if cycle.state.binding_id is None
                else ScheduledTaskTerminalEffectSnapshot(
                    cycle_id=cycle.state.cycle_id,
                    task_id=cycle.state.task_id,
                    workspace_id=cycle.state.workspace_id,
                    agent_id=cycle.state.agent_id,
                    session_id=cycle.state.session_id,
                    binding_id=cycle.state.binding_id,
                    status=status,
                    result=normalized_result,
                    tracker_desired_revision=cycle.state.tracker_desired_revision,
                    tracker_projection_parts=tuple(
                        cycle.state.tracker_current_projection_parts
                    ),
                )
            )
            event = await self.event_repository.append(
                session,
                EventCreate(
                    session_id=session_id,
                    kind=EventKind.SCHEDULED_TASK_RESULT,
                    payload=payload.model_dump(mode="json"),
                    external_id=external_id,
                ),
            )
            deleted = await self.cycle_repository.delete_started(
                session,
                record=cycle,
            )
            if not deleted:
                raise RuntimeError(
                    "Scheduled Task cycle changed during terminalization."
                )

            task = await self.task_repository.lock_by_id(
                session,
                cycle.state.task_id,
            )
            if task is not None and task.active_cycle_id == cycle_id:
                if task.schedule_type is ScheduledTaskScheduleType.ONCE:
                    transitioned = await self.task_repository.delete_completed_once(
                        session,
                        task_id=task.id,
                        cycle_id=cycle_id,
                    )
                else:
                    transitioned = (
                        await self.task_repository.release_completed_recurring(
                            session,
                            task_id=task.id,
                            cycle_id=cycle_id,
                        )
                    )
                if not transitioned:
                    raise RuntimeError("Scheduled Task changed during terminalization.")

            await self.run_repository.update(
                session,
                run_id,
                AgentRunPatch(
                    terminal_result_event_id=event.id,
                    terminal_result_message=normalized_result,
                ),
            )
            return ScheduledTaskTerminalOutcome(
                event=event,
                created=True,
                effect_snapshot=effect_snapshot,
            )


def _result_external_id(cycle_id: str) -> str:
    """Return the deterministic terminal Event crash fence."""
    return f"scheduled-task-result:{cycle_id}"


def get_scheduled_task_terminal_operations(
    session_manager: Annotated[
        SessionManager[AsyncSession], Depends(get_session_manager)
    ],
    run_repository: Annotated[AgentRunRepository, Depends(AgentRunRepository)],
    event_repository: Annotated[
        EventTranscriptRepository, Depends(EventTranscriptRepository)
    ],
    task_repository: Annotated[
        ScheduledTaskRepository, Depends(ScheduledTaskRepository)
    ],
    cycle_repository: Annotated[
        ScheduledTaskCycleRepository, Depends(ScheduledTaskCycleRepository)
    ],
) -> ScheduledTaskTerminalOperations:
    """Wire completed terminal operations entirely inside repository composition."""
    return ScheduledTaskTerminalOperations(
        session_manager=session_manager,
        run_repository=run_repository,
        event_repository=event_repository,
        task_repository=task_repository,
        cycle_repository=cycle_repository,
    )
