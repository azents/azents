"""Completed database operations for the Engine Scheduled Toolkit."""

import dataclasses
import datetime
from typing import Literal

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    AgentLifecycleStatus,
    AgentSessionStatus,
    ExternalChannelConnectionStatus,
    ExternalChannelResourceStatus,
    ExternalChannelRouteCatalogStatus,
    MailboxItemKind,
)
from azents.core.scheduled_task import MAX_SCHEDULED_TASK_OBJECTIVE_LENGTH
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.agent_session import RDBAgentSession
from azents.rdb.models.external_channel import (
    RDBExternalChannelAgentRoute,
    RDBExternalChannelBinding,
    RDBExternalChannelConnection,
    RDBExternalChannelResource,
)
from azents.rdb.session import SessionManager
from azents.repos.agent_execution import AgentRunRepository
from azents.repos.mailbox import MailboxRepository
from azents.repos.scheduled_task.data import ScheduledTask, ScheduledTaskCreate
from azents.repos.scheduled_task.repository import ScheduledTaskRepository
from azents.repos.scheduled_task.schedule import validate_schedule
from azents.repos.scheduled_task_cycle import ScheduledTaskCycleRepository
from azents.repos.scheduled_task_cycle.data import (
    ScheduledTaskCycleRecord,
    ScheduledTaskCycleState,
)

ScheduledTaskExecutionState = Literal[
    "idle",
    "admitted",
    "running",
    "running_with_pending",
]


@dataclasses.dataclass(frozen=True)
class ScheduledTaskToolProjection:
    """One detached Task and its derived execution state."""

    task: ScheduledTask
    execution_state: ScheduledTaskExecutionState


@dataclasses.dataclass(frozen=True)
class _ScheduledTaskMutationTarget:
    """Rows locked in the shared Mailbox -> cycle -> Task order."""

    task: ScheduledTask
    cycle: ScheduledTaskCycleRecord | None
    trigger_id: str | None


@dataclasses.dataclass
class ScheduledTaskToolOperationRepository:
    """Own complete Scheduled Toolkit database transactions."""

    session_manager: SessionManager[AsyncSession]
    task_repository: ScheduledTaskRepository
    cycle_repository: ScheduledTaskCycleRepository
    mailbox_repository: MailboxRepository
    run_repository: AgentRunRepository

    async def active_cycle(
        self,
        *,
        workspace_id: str,
        agent_id: str,
        session_id: str,
        run_id: str,
    ) -> ScheduledTaskCycleRecord | None:
        """Resolve the current Run's exact started cycle in one transaction."""
        async with self.session_manager() as session:
            run = await self.run_repository.get_by_id(session, run_id)
            if (
                run is None
                or run.session_id != session_id
                or run.scheduled_task_cycle_id is None
            ):
                return None
            cycle = await self.cycle_repository.get_started(
                session,
                agent_id=agent_id,
                session_id=session_id,
                cycle_id=run.scheduled_task_cycle_id,
            )
            if (
                cycle is None
                or cycle.state.workspace_id != workspace_id
                or cycle.state.current_run_id != run_id
            ):
                return None
            return cycle

    async def list_started_cycle_states(
        self,
        *,
        agent_id: str,
        session_id: str,
    ) -> list[ScheduledTaskCycleState]:
        """Return current started cycle states after the transaction closes."""
        async with self.session_manager() as session:
            records = await self.cycle_repository.list_started(
                session,
                agent_id=agent_id,
                session_id=session_id,
            )
            return [record.state for record in records]

    async def create(
        self,
        *,
        workspace_id: str,
        agent_id: str,
        session_id: str,
        title: str,
        objective: str,
        at: str | None,
        cron: str | None,
        timezone: str | None,
        binding_id: str | None,
        now: datetime.datetime | None = None,
    ) -> ScheduledTask:
        """Validate authority and create one Task in a completed transaction."""
        schedule = validate_schedule(
            at=at,
            cron_expression=cron,
            timezone=timezone,
            now=now,
        )
        async with self.session_manager() as session:
            await self._validate_target(
                session,
                workspace_id=workspace_id,
                agent_id=agent_id,
                session_id=session_id,
                binding_id=binding_id,
            )
            return await self.task_repository.create(
                session,
                ScheduledTaskCreate(
                    workspace_id=workspace_id,
                    agent_id=agent_id,
                    session_id=session_id,
                    title=_required_text(title, "title", max_length=120),
                    objective=_required_text(
                        objective,
                        "objective",
                        max_length=MAX_SCHEDULED_TASK_OBJECTIVE_LENGTH,
                    ),
                    schedule_type=schedule.schedule_type,
                    next_eligible_at=schedule.next_eligible_at,
                    binding_id=binding_id,
                    scheduled_at=schedule.scheduled_at,
                    cron_expression=schedule.cron_expression,
                    timezone=schedule.timezone,
                ),
            )

    async def list_tasks(
        self,
        *,
        agent_id: str,
        session_id: str,
    ) -> list[ScheduledTaskToolProjection]:
        """List Session Tasks and derive execution state in one transaction."""
        async with self.session_manager() as session:
            tasks = await self.task_repository.list_by_session_id(session, session_id)
            return [
                await self._task_projection(
                    session,
                    agent_id=agent_id,
                    session_id=session_id,
                    task=task,
                )
                for task in tasks
            ]

    async def delete(
        self,
        *,
        session_id: str,
        task_id: str,
    ) -> ScheduledTask | None:
        """Delete one Session-owned Task and return its committed snapshot."""
        async with self.session_manager() as session:
            target = await self._lock_mutation_target(
                session,
                session_id=session_id,
                task_id=task_id,
            )
            if target is None:
                return None
            current = target.task
            await self._validate_target(
                session,
                workspace_id=current.workspace_id,
                agent_id=current.agent_id,
                session_id=current.session_id,
                binding_id=current.binding_id,
            )
            cycle = target.cycle
            if cycle is not None and cycle.state.phase == "admitted":
                if target.trigger_id is not None:
                    await self.mailbox_repository.delete_by_session_and_id(
                        session,
                        current.session_id,
                        target.trigger_id,
                    )
                deleted_cycle = await self.cycle_repository.delete_if_admitted(
                    session,
                    agent_id=current.agent_id,
                    session_id=current.session_id,
                    cycle_id=cycle.state.cycle_id,
                )
                if not deleted_cycle:
                    raise RuntimeError(
                        "Scheduled Task admitted cycle changed during deletion."
                    )
            deleted = await self.task_repository.delete_by_session_and_id(
                session,
                session_id=current.session_id,
                task_id=current.id,
            )
            return current if deleted else None

    async def _task_projection(
        self,
        session: AsyncSession,
        *,
        agent_id: str,
        session_id: str,
        task: ScheduledTask,
    ) -> ScheduledTaskToolProjection:
        execution_state: ScheduledTaskExecutionState = "idle"
        if task.active_cycle_id is not None:
            cycle = await self.cycle_repository.get(
                session,
                agent_id=agent_id,
                session_id=session_id,
                cycle_id=task.active_cycle_id,
            )
            if cycle is None:
                raise RuntimeError("Scheduled Task active cycle state is missing.")
            if cycle.state.phase == "admitted":
                execution_state = "admitted"
            elif task.pending_scheduled_for is not None:
                execution_state = "running_with_pending"
            else:
                execution_state = "running"
        return ScheduledTaskToolProjection(
            task=task,
            execution_state=execution_state,
        )

    async def _lock_mutation_target(
        self,
        session: AsyncSession,
        *,
        session_id: str,
        task_id: str,
    ) -> _ScheduledTaskMutationTarget | None:
        candidate = await self.task_repository.get_by_session_and_id(
            session,
            session_id=session_id,
            task_id=task_id,
        )
        if candidate is None:
            return None
        cycle = (
            None
            if candidate.active_cycle_id is None
            else await self.cycle_repository.get(
                session,
                agent_id=candidate.agent_id,
                session_id=session_id,
                cycle_id=candidate.active_cycle_id,
            )
        )
        trigger_id: str | None = None
        if cycle is not None:
            trigger = await self.mailbox_repository.get_by_idempotency_key(
                session,
                session_id=session_id,
                kind=MailboxItemKind.SCHEDULED_TASK_TRIGGER,
                idempotency_key=f"scheduled-task-trigger:{cycle.state.cycle_id}",
            )
            if trigger is not None:
                locked_trigger = await self.mailbox_repository.lock_by_session_and_id(
                    session,
                    session_id=session_id,
                    buffer_id=trigger.id,
                )
                if locked_trigger is None:
                    raise RuntimeError(
                        "Scheduled Task trigger changed during mutation."
                    )
                trigger_id = locked_trigger.id
            locked_cycle = await self.cycle_repository.lock(
                session,
                agent_id=candidate.agent_id,
                session_id=session_id,
                cycle_id=cycle.state.cycle_id,
            )
            if locked_cycle is None:
                raise RuntimeError("Scheduled Task cycle changed during mutation.")
            cycle = locked_cycle
        locked_task = await self.task_repository.get_by_session_and_id(
            session,
            session_id=session_id,
            task_id=task_id,
            lock=True,
        )
        if locked_task is None:
            raise RuntimeError("Scheduled Task changed during mutation.")
        if locked_task.active_cycle_id != candidate.active_cycle_id:
            raise RuntimeError("Scheduled Task cycle fence changed during mutation.")
        return _ScheduledTaskMutationTarget(
            task=locked_task,
            cycle=cycle,
            trigger_id=trigger_id,
        )

    @staticmethod
    async def _validate_target(
        session: AsyncSession,
        *,
        workspace_id: str,
        agent_id: str,
        session_id: str,
        binding_id: str | None,
    ) -> None:
        target = await session.scalar(
            sa.select(RDBAgentSession).where(
                RDBAgentSession.id == session_id,
                RDBAgentSession.workspace_id == workspace_id,
                RDBAgentSession.agent_id == agent_id,
                RDBAgentSession.status == AgentSessionStatus.ACTIVE,
            )
        )
        if target is None:
            raise ValueError(
                "Scheduled Task target Session is not active or owned by its Agent."
            )
        if binding_id is None:
            return
        binding = await session.scalar(
            sa.select(RDBExternalChannelBinding)
            .join(
                RDBExternalChannelResource,
                RDBExternalChannelResource.id == RDBExternalChannelBinding.resource_id,
            )
            .join(
                RDBExternalChannelAgentRoute,
                RDBExternalChannelAgentRoute.id == RDBExternalChannelBinding.route_id,
            )
            .join(
                RDBExternalChannelConnection,
                RDBExternalChannelConnection.id
                == RDBExternalChannelAgentRoute.connection_id,
            )
            .join(
                RDBAgent,
                RDBAgent.id == RDBExternalChannelAgentRoute.agent_id,
            )
            .where(
                RDBExternalChannelBinding.id == binding_id,
                RDBExternalChannelBinding.agent_session_id == session_id,
                RDBExternalChannelBinding.disconnected_at.is_(None),
                RDBExternalChannelResource.connection_id
                == RDBExternalChannelConnection.id,
                RDBExternalChannelResource.status
                == ExternalChannelResourceStatus.ACTIVE,
                RDBExternalChannelAgentRoute.agent_id == agent_id,
                RDBExternalChannelAgentRoute.catalog_status
                == ExternalChannelRouteCatalogStatus.AVAILABLE,
                RDBExternalChannelConnection.disconnected_at.is_(None),
                RDBExternalChannelConnection.status.in_(
                    (
                        ExternalChannelConnectionStatus.ACTIVE,
                        ExternalChannelConnectionStatus.DEGRADED,
                    )
                ),
                RDBAgent.lifecycle_status == AgentLifecycleStatus.ACTIVE,
            )
        )
        if binding is None:
            raise ValueError(
                "Scheduled Task Binding is not connected to its target Session."
            )


def _required_text(value: str, field: str, *, max_length: int | None = None) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field} must not be empty.")
    if max_length is not None and len(normalized) > max_length:
        raise ValueError(f"{field} exceeds its maximum length.")
    return normalized
