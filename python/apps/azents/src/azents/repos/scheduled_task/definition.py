"""Database-only Scheduled Task definition composition primitives."""

from __future__ import annotations

import datetime
from dataclasses import dataclass
from typing import Protocol

import sqlalchemy as sa

from azents.core.enums import (
    AgentLifecycleStatus,
    AgentSessionStatus,
    ExternalChannelConnectionStatus,
    ExternalChannelResourceStatus,
    ExternalChannelRouteCatalogStatus,
    MailboxItemKind,
    ScheduledTaskScheduleType,
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
from azents.rdb.session_capabilities import ReadSession, WriteSession
from azents.repos.mailbox import MailboxRepository
from azents.repos.scheduled_task.data import (
    ScheduledTask,
    ScheduledTaskCreate,
    ScheduledTaskReplace,
)
from azents.repos.scheduled_task.repository import ScheduledTaskRepository
from azents.repos.scheduled_task.schedule import (
    InvalidScheduledTaskSchedule,
    validate_schedule,
)
from azents.repos.scheduled_task_cycle import ScheduledTaskCycleRepository
from azents.repos.scheduled_task_cycle.data import (
    ScheduledTaskCycleRecord,
)


class ScheduledTaskAuthorityValidator(Protocol):
    """Validate the current Session, Agent, and optional Binding authority."""

    async def validate(
        self,
        session: WriteSession,
        task: ScheduledTask,
    ) -> None: ...

    async def validate_target(
        self,
        session: WriteSession,
        *,
        workspace_id: str,
        agent_id: str,
        session_id: str,
        binding_id: str | None,
    ) -> None: ...


class RDBScheduledTaskAuthorityValidator:
    """Validate Session-owned Task targets against current RDB authority."""

    async def validate(
        self,
        session: WriteSession,
        task: ScheduledTask,
    ) -> None:
        await self.validate_target(
            session,
            workspace_id=task.workspace_id,
            agent_id=task.agent_id,
            session_id=task.session_id,
            binding_id=task.binding_id,
        )

    async def validate_target(
        self,
        session: WriteSession,
        *,
        workspace_id: str,
        agent_id: str,
        session_id: str,
        binding_id: str | None,
    ) -> None:
        target = await session.write_session.scalar(
            sa.select(RDBAgentSession).where(
                RDBAgentSession.id == session_id,
                RDBAgentSession.workspace_id == workspace_id,
                RDBAgentSession.agent_id == agent_id,
                RDBAgentSession.status == AgentSessionStatus.ACTIVE,
            )
        )
        if target is None:
            raise InvalidScheduledTaskSchedule(
                "Scheduled Task target Session is not active or owned by its Agent."
            )
        if binding_id is None:
            return
        binding = await session.write_session.scalar(
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
            raise InvalidScheduledTaskSchedule(
                "Scheduled Task Binding is not connected to its target Session."
            )


@dataclass(frozen=True)
class ScheduledTaskMutationTarget:
    """Rows locked in the shared Mailbox -> cycle -> Task order."""

    task: ScheduledTask
    cycle: ScheduledTaskCycleRecord | None
    trigger_id: str | None


class ScheduledTaskDefinitionRepository:
    """Database-only Scheduled Task primitives for atomic owner compositions."""

    def __init__(
        self,
        repository: ScheduledTaskRepository,
        cycle_repository: ScheduledTaskCycleRepository,
        mailbox_repository: MailboxRepository,
        authority_validator: ScheduledTaskAuthorityValidator,
    ) -> None:
        self.repository = repository
        self.cycle_repository = cycle_repository
        self.mailbox_repository = mailbox_repository
        self.authority_validator = authority_validator

    async def create(
        self,
        session: WriteSession,
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
        """Validate and persist one exact Session-owned Task definition."""
        schedule = validate_schedule(
            at=at,
            cron_expression=cron,
            timezone=timezone,
            now=now,
        )
        await self.authority_validator.validate_target(
            session,
            workspace_id=workspace_id,
            agent_id=agent_id,
            session_id=session_id,
            binding_id=binding_id,
        )
        return await self.repository.create(
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
        session: ReadSession,
        *,
        session_id: str,
    ) -> list[ScheduledTask]:
        """List every Task owned by one exact Session."""
        return await self.repository.list_by_session_id(session, session_id)

    async def replace(
        self,
        session: WriteSession,
        *,
        session_id: str,
        task_id: str,
        title: str,
        objective: str,
        at: str | None,
        cron: str | None,
        timezone: str | None,
        binding_id: str | None,
        now: datetime.datetime | None = None,
    ) -> ScheduledTask | None:
        """Replace future Task definition fields with a new canonical schedule."""
        target = await self._lock_mutation_target(
            session,
            session_id=session_id,
            task_id=task_id,
        )
        if target is None:
            return None
        return await self.replace_locked_provider_target(
            session,
            target=target,
            expected_binding_id=None,
            title=title,
            objective=objective,
            at=at,
            cron=cron,
            timezone=timezone,
            binding_id=binding_id,
            now=now,
        )

    async def lock_provider_mutation_target(
        self,
        session: WriteSession,
        *,
        task_id: str,
        expected_binding_id: str,
    ) -> ScheduledTaskMutationTarget | None:
        """Lock one provider control target in the canonical mutation order."""
        candidate = await self.repository.get_by_id(session, task_id)
        if candidate is None:
            return None
        target = await self._lock_mutation_target(
            session,
            session_id=candidate.session_id,
            task_id=task_id,
        )
        if target is None or target.task.binding_id != expected_binding_id:
            return None
        return target

    async def lock_management_mutation_target(
        self,
        session: WriteSession,
        *,
        task_id: str,
        expected_binding_id: str | None,
    ) -> ScheduledTaskMutationTarget | None:
        """Lock one management target after its Binding authority locks."""
        candidate = await self.repository.get_by_id(session, task_id)
        if candidate is None or candidate.binding_id != expected_binding_id:
            return None
        target = await self._lock_mutation_target(
            session,
            session_id=candidate.session_id,
            task_id=task_id,
        )
        if target is None or target.task != candidate:
            return None
        return target

    async def replace_locked_provider_target(
        self,
        session: WriteSession,
        *,
        target: ScheduledTaskMutationTarget,
        expected_binding_id: str | None,
        title: str,
        objective: str,
        at: str | None,
        cron: str | None,
        timezone: str | None,
        binding_id: str | None,
        now: datetime.datetime | None = None,
    ) -> ScheduledTask | None:
        """Replace a Task already locked by the shared provider mutation path."""
        current = target.task
        if (
            expected_binding_id is not None
            and current.binding_id != expected_binding_id
        ):
            return None
        cycle = target.cycle
        await self.authority_validator.validate_target(
            session,
            workspace_id=current.workspace_id,
            agent_id=current.agent_id,
            session_id=current.session_id,
            binding_id=binding_id,
        )
        if cycle is not None and cycle.state.phase == "admitted":
            await self._delete_admitted_cycle(
                session, current, cycle, target.trigger_id
            )
        schedule = validate_schedule(
            at=at,
            cron_expression=cron,
            timezone=timezone,
            now=now,
            allow_past_once=cycle is not None and cycle.state.phase == "started",
        )
        if (
            current.active_cycle_id is not None
            and current.schedule_type is ScheduledTaskScheduleType.ONCE
            and cycle is not None
            and cycle.state.phase == "started"
        ):
            raise InvalidScheduledTaskSchedule(
                "A one-time Task with an active cycle cannot be edited."
            )
        return await self.repository.replace(
            session,
            session_id=current.session_id,
            task_id=current.id,
            replace=ScheduledTaskReplace(
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
            preserve_active_cycle=cycle is not None and cycle.state.phase == "started",
        )

    async def delete(
        self,
        session: WriteSession,
        *,
        session_id: str,
        task_id: str,
    ) -> bool:
        """Delete one exact Session-owned Task definition."""
        return (
            await self.delete_with_snapshot(
                session,
                session_id=session_id,
                task_id=task_id,
            )
            is not None
        )

    async def delete_with_snapshot(
        self,
        session: WriteSession,
        *,
        session_id: str,
        task_id: str,
    ) -> ScheduledTask | None:
        """Delete one exact Session-owned Task and return its deleted snapshot."""
        target = await self._lock_mutation_target(
            session,
            session_id=session_id,
            task_id=task_id,
        )
        if target is None:
            return None
        deleted = await self.delete_locked_provider_target(
            session,
            target=target,
            expected_binding_id=None,
        )
        return target.task if deleted else None

    async def delete_locked_provider_target(
        self,
        session: WriteSession,
        *,
        target: ScheduledTaskMutationTarget,
        expected_binding_id: str | None,
    ) -> bool:
        """Delete a Task already locked by the shared provider mutation path."""
        current = target.task
        if (
            expected_binding_id is not None
            and current.binding_id != expected_binding_id
        ):
            return False
        cycle = target.cycle
        await self.authority_validator.validate(session, current)
        if cycle is not None and cycle.state.phase == "admitted":
            await self._delete_admitted_cycle(
                session, current, cycle, target.trigger_id
            )
        return await self.repository.delete_by_session_and_id(
            session,
            session_id=current.session_id,
            task_id=current.id,
        )

    async def _lock_mutation_target(
        self,
        session: WriteSession,
        *,
        session_id: str,
        task_id: str,
    ) -> ScheduledTaskMutationTarget | None:
        """Lock Mailbox, cycle, and Task in the shared admission order."""
        candidate = await self.repository.get_by_session_and_id(
            session,
            session_id=session_id,
            task_id=task_id,
        )
        if candidate is None:
            return None
        cycle = await self._cycle(session, candidate)
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
        locked_task = await self.repository.get_by_session_and_id(
            session,
            session_id=session_id,
            task_id=task_id,
            lock=True,
        )
        if locked_task is None:
            raise RuntimeError("Scheduled Task changed during mutation.")
        if locked_task.active_cycle_id != candidate.active_cycle_id:
            raise RuntimeError("Scheduled Task cycle fence changed during mutation.")
        return ScheduledTaskMutationTarget(
            task=locked_task,
            cycle=cycle,
            trigger_id=trigger_id,
        )

    async def _cycle(
        self,
        session: ReadSession,
        task: ScheduledTask,
    ) -> ScheduledTaskCycleRecord | None:
        if task.active_cycle_id is None:
            return None
        return await self.cycle_repository.get(
            session,
            agent_id=task.agent_id,
            session_id=task.session_id,
            cycle_id=task.active_cycle_id,
        )

    async def _delete_admitted_cycle(
        self,
        session: WriteSession,
        task: ScheduledTask,
        cycle: ScheduledTaskCycleRecord,
        trigger_id: str | None,
    ) -> None:
        if trigger_id is not None:
            await self.mailbox_repository.delete_by_session_and_id(
                session,
                task.session_id,
                trigger_id,
            )
        deleted = await self.cycle_repository.delete_if_admitted(
            session,
            agent_id=task.agent_id,
            session_id=task.session_id,
            cycle_id=cycle.state.cycle_id,
        )
        if not deleted:
            raise RuntimeError("Scheduled Task admitted cycle changed during deletion.")


def _required_text(value: str, field: str, *, max_length: int | None = None) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field} must not be empty.")
    if max_length is not None and len(normalized) > max_length:
        raise ValueError(f"{field} exceeds its maximum length.")
    return normalized
