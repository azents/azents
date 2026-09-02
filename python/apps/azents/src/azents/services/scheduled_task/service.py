"""Scheduled Task management and due-dispatch services."""

from __future__ import annotations

import datetime
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

import sqlalchemy as sa
from azcommon.uuid import uuid7
from sqlalchemy.ext.asyncio import AsyncSession

from azents.broker.types import SessionBroker, SessionWakeUp
from azents.core.enums import (
    AgentLifecycleStatus,
    AgentSessionStatus,
    ExternalChannelConnectionStatus,
    ExternalChannelResourceStatus,
    ExternalChannelRouteCatalogStatus,
    MailboxItemKind,
    MailboxSchedulingMode,
    ScheduledTaskScheduleType,
)
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.agent_session import RDBAgentSession
from azents.rdb.models.external_channel import (
    RDBExternalChannelAgentRoute,
    RDBExternalChannelBinding,
    RDBExternalChannelConnection,
    RDBExternalChannelResource,
)
from azents.rdb.session import SessionManager
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.mailbox import MailboxRepository
from azents.repos.mailbox.data import (
    MailboxItemCreate,
    ScheduledTaskTriggerMailboxPayload,
)
from azents.repos.scheduled_task.data import (
    MAX_SCHEDULED_TASK_OBJECTIVE_LENGTH,
    ScheduledTask,
    ScheduledTaskCreate,
    ScheduledTaskReplace,
)
from azents.repos.scheduled_task.repository import ScheduledTaskRepository
from azents.repos.scheduled_task.schedule import (
    InvalidScheduledTaskSchedule,
    advance_cron_cursor,
    validate_schedule,
)
from azents.repos.scheduled_task_cycle import ScheduledTaskCycleRepository
from azents.repos.scheduled_task_cycle.data import (
    ScheduledTaskCycleRecord,
    ScheduledTaskCycleSnapshot,
)
from azents.services.scheduled_task.rendering import (
    render_scheduled_task_runtime_message,
)

logger = logging.getLogger(__name__)

_DEFAULT_BATCH_SIZE = 50
_DEFAULT_LEASE = datetime.timedelta(seconds=60)


class ScheduledTaskAuthorityValidator(Protocol):
    """Validate the current Session, Agent, and optional Binding authority."""

    async def validate(
        self,
        session: AsyncSession,
        task: ScheduledTask,
    ) -> None: ...

    async def validate_target(
        self,
        session: AsyncSession,
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
        session: AsyncSession,
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
            raise InvalidScheduledTaskSchedule(
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
            raise InvalidScheduledTaskSchedule(
                "Scheduled Task Binding is not connected to its target Session."
            )


@dataclass(frozen=True)
class ScheduledTaskDispatchSummary:
    """Aggregate outcome returned by one bounded dispatcher pass."""

    claimed: int = 0
    admitted: int = 0
    coalesced: int = 0
    skipped: int = 0
    wake_failed: int = 0

    def plus(
        self, other: "ScheduledTaskDispatchSummary"
    ) -> "ScheduledTaskDispatchSummary":
        """Add two aggregate outcomes."""
        return ScheduledTaskDispatchSummary(
            claimed=self.claimed + other.claimed,
            admitted=self.admitted + other.admitted,
            coalesced=self.coalesced + other.coalesced,
            skipped=self.skipped + other.skipped,
            wake_failed=self.wake_failed + other.wake_failed,
        )


@dataclass(frozen=True)
class ScheduledTaskDispatchOutcome:
    """Outcome of one claimed Task admission transaction."""

    admitted: bool = False
    coalesced: bool = False
    skipped: bool = False


@dataclass(frozen=True)
class ScheduledTaskMutationTarget:
    """Rows locked in the shared Mailbox -> cycle -> Task order."""

    task: ScheduledTask
    cycle: ScheduledTaskCycleRecord | None
    trigger_id: str | None


class ScheduledTaskService:
    """Session-scoped Scheduled Task definition service."""

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
        session: AsyncSession,
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
        session: AsyncSession,
        *,
        session_id: str,
    ) -> list[ScheduledTask]:
        """List every Task owned by one exact Session."""
        return await self.repository.list_by_session_id(session, session_id)

    async def replace(
        self,
        session: AsyncSession,
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
        session: AsyncSession,
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
        session: AsyncSession,
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
        session: AsyncSession,
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
        session: AsyncSession,
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
        session: AsyncSession,
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
        session: AsyncSession,
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
        session: AsyncSession,
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
        session: AsyncSession,
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
        session: AsyncSession,
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


class ScheduledTaskDispatcher:
    """Bounded PostgreSQL due dispatcher for user-defined Scheduled Tasks."""

    def __init__(
        self,
        session_manager: SessionManager[AsyncSession],
        *,
        agent_session_repository: AgentSessionRepository,
        cycle_repository: ScheduledTaskCycleRepository,
        mailbox_repository: MailboxRepository,
        broker: SessionBroker,
        authority_validator: RDBScheduledTaskAuthorityValidator,
        task_repository: ScheduledTaskRepository,
        clock: Callable[[], datetime.datetime],
        batch_size: int = _DEFAULT_BATCH_SIZE,
        lease_duration: datetime.timedelta = _DEFAULT_LEASE,
    ) -> None:
        self.session_manager = session_manager
        self.agent_session_repository = agent_session_repository
        self.cycle_repository = cycle_repository
        self.mailbox_repository = mailbox_repository
        self.broker = broker
        self.authority_validator = authority_validator
        self.task_repository = task_repository
        self.clock = clock
        self.batch_size = batch_size
        self.lease_duration = lease_duration

    async def dispatch_once(
        self,
        *,
        lease_owner: str,
        now: datetime.datetime | None = None,
    ) -> ScheduledTaskDispatchSummary:
        """Claim and admit due Tasks at one optional controlled pass instant."""
        controlled_now = _utc(now) if now is not None else None
        summary = ScheduledTaskDispatchSummary()
        for _ in range(self.batch_size):
            claim_now = (
                controlled_now if controlled_now is not None else _utc(self.clock())
            )
            async with self.session_manager() as session:
                claimed = await self.task_repository.claim_due(
                    session,
                    now=claim_now,
                    lease_owner=lease_owner,
                    lease_until=claim_now + self.lease_duration,
                    limit=1,
                )
            if not claimed:
                break
            task = claimed[0]
            summary = summary.plus(ScheduledTaskDispatchSummary(claimed=1))
            outcome = await self._admit_claimed(
                task_id=task.id,
                lease_owner=lease_owner,
                lease_token=_lease_token(task),
                now=(
                    controlled_now if controlled_now is not None else _utc(self.clock())
                ),
                controlled_now=controlled_now,
            )
            summary = summary.plus(
                ScheduledTaskDispatchSummary(
                    admitted=int(outcome.admitted),
                    coalesced=int(outcome.coalesced),
                    skipped=int(outcome.skipped),
                )
            )
            if outcome.admitted:
                try:
                    await self.broker.send_message(
                        SessionWakeUp(session_id=task.session_id)
                    )
                except Exception:
                    logger.exception(
                        "Scheduled Task Session wake failed",
                        extra={"session_id": task.session_id},
                    )
                    summary = summary.plus(ScheduledTaskDispatchSummary(wake_failed=1))
        return summary

    async def _admit_claimed(
        self,
        *,
        task_id: str,
        lease_owner: str,
        lease_token: datetime.datetime,
        now: datetime.datetime,
        controlled_now: datetime.datetime | None,
    ) -> ScheduledTaskDispatchOutcome:
        async with self.session_manager() as session:
            task = await self.task_repository.lock_claimed_by_id(
                session,
                task_id=task_id,
                lease_owner=lease_owner,
                lease_token=lease_token,
                now=now,
            )
            if task is None:
                raise RuntimeError("Scheduled Task claim fence was lost.")
            try:
                await self.authority_validator.validate(session, task)
            except InvalidScheduledTaskSchedule as error:
                deleted = await self.task_repository.delete_by_session_and_id(
                    session,
                    session_id=task.session_id,
                    task_id=task.id,
                )
                if not deleted:
                    raise RuntimeError(
                        "Scheduled Task authority cleanup lost its claim fence."
                    ) from error
                return ScheduledTaskDispatchOutcome(skipped=True)
            if task.active_cycle_id is not None:
                if task.schedule_type is not ScheduledTaskScheduleType.CRON:
                    await self._complete_claim(
                        session,
                        task,
                        lease_owner=lease_owner,
                        lease_token=_lease_token(task),
                        lease_now=self._lease_now(controlled_now),
                        next_eligible_at=task.next_eligible_at,
                        pending_scheduled_for=task.pending_scheduled_for,
                    )
                    return ScheduledTaskDispatchOutcome(skipped=True)
                cron_expression, timezone = _cron_values(task)
                _, future = advance_cron_cursor(
                    expression=cron_expression,
                    timezone=timezone,
                    cursor=task.next_eligible_at,
                    now=now,
                )
                pending = task.pending_scheduled_for or task.next_eligible_at
                await self._complete_claim(
                    session,
                    task,
                    lease_owner=lease_owner,
                    lease_token=_lease_token(task),
                    lease_now=self._lease_now(controlled_now),
                    next_eligible_at=future,
                    pending_scheduled_for=pending,
                )
                return ScheduledTaskDispatchOutcome(coalesced=True)

            if task.schedule_type is ScheduledTaskScheduleType.ONCE:
                if task.scheduled_at is None:
                    raise InvalidScheduledTaskSchedule(
                        "Persisted one-time schedule is incomplete."
                    )
                scheduled_for = task.scheduled_at
                next_eligible_at = task.next_eligible_at
            else:
                cron_expression, timezone = _cron_values(task)
                scheduled_for, next_eligible_at = advance_cron_cursor(
                    expression=cron_expression,
                    timezone=timezone,
                    cursor=task.next_eligible_at,
                    now=now,
                )
            cycle_id = uuid7().hex
            snapshot = ScheduledTaskCycleSnapshot(
                cycle_id=cycle_id,
                task_id=task.id,
                workspace_id=task.workspace_id,
                agent_id=task.agent_id,
                session_id=task.session_id,
                binding_id=task.binding_id,
                title=task.title,
                objective=task.objective,
                schedule_type=task.schedule_type,
                scheduled_at=task.scheduled_at,
                cron_expression=task.cron_expression,
                timezone=task.timezone,
                scheduled_for=scheduled_for,
            )
            await self.cycle_repository.create_admitted(session, snapshot)
            content = render_scheduled_task_runtime_message(
                title=task.title,
                objective=task.objective,
                schedule_type=task.schedule_type,
                scheduled_at=task.scheduled_at,
                cron_expression=task.cron_expression,
                timezone=task.timezone,
                scheduled_for=scheduled_for,
            )
            payload = ScheduledTaskTriggerMailboxPayload(
                type="scheduled_task_trigger",
                cycle_id=cycle_id,
                items=[
                    {
                        "item_key": "scheduled_task_trigger:0",
                        "presentation_kind": "scheduled_task_trigger",
                        "content": content,
                        "metadata": {"title": task.title},
                    }
                ],
            )
            await self.mailbox_repository.create_idempotent(
                session,
                MailboxItemCreate(
                    session_id=task.session_id,
                    kind=MailboxItemKind.SCHEDULED_TASK_TRIGGER,
                    scheduling_mode=MailboxSchedulingMode.WAKE_SESSION,
                    requested_model_target_label=None,
                    requested_reasoning_effort=None,
                    sender_user_id=None,
                    order_group=None,
                    order_sequence=0,
                    content=content,
                    idempotency_key=f"scheduled-task-trigger:{cycle_id}",
                    metadata={"title": task.title},
                    action=None,
                    attachments=[],
                    file_parts=[],
                    payload=payload,
                ),
                idempotency_key=f"scheduled-task-trigger:{cycle_id}",
            )
            await self.agent_session_repository.mark_running_for_input_wakeup(
                session,
                task.session_id,
            )
            await self._complete_claim(
                session,
                task,
                lease_owner=lease_owner,
                lease_token=_lease_token(task),
                lease_now=self._lease_now(controlled_now),
                next_eligible_at=next_eligible_at,
                active_cycle_id=cycle_id,
                active_scheduled_for=scheduled_for,
                pending_scheduled_for=None,
            )
            return ScheduledTaskDispatchOutcome(admitted=True)

    def _lease_now(
        self,
        controlled_now: datetime.datetime | None,
    ) -> datetime.datetime:
        """Return the controlled pass instant or the current lease-fence time."""
        return controlled_now if controlled_now is not None else _utc(self.clock())

    async def _complete_claim(
        self,
        session: AsyncSession,
        task: ScheduledTask,
        *,
        lease_owner: str,
        lease_token: datetime.datetime,
        lease_now: datetime.datetime,
        next_eligible_at: datetime.datetime,
        pending_scheduled_for: datetime.datetime | None,
        active_cycle_id: str | None = None,
        active_scheduled_for: datetime.datetime | None = None,
    ) -> None:
        updated = await self.task_repository.complete_claim(
            session,
            task_id=task.id,
            lease_owner=lease_owner,
            lease_token=lease_token,
            lease_now=lease_now,
            next_eligible_at=next_eligible_at,
            active_cycle_id=(
                task.active_cycle_id if active_cycle_id is None else active_cycle_id
            ),
            active_scheduled_for=(
                task.active_scheduled_for
                if active_scheduled_for is None
                else active_scheduled_for
            ),
            pending_scheduled_for=pending_scheduled_for,
        )
        if not updated:
            raise RuntimeError("Scheduled Task claim fence was lost.")


def _lease_token(task: ScheduledTask) -> datetime.datetime:
    if task.lease_until is None:
        raise RuntimeError("Scheduled Task claim is missing its lease token.")
    return task.lease_until


def _cron_values(task: ScheduledTask) -> tuple[str, str]:
    if task.cron_expression is None or task.timezone is None:
        raise InvalidScheduledTaskSchedule("Persisted cron schedule is incomplete.")
    return task.cron_expression, task.timezone


def _required_text(value: str, field: str, *, max_length: int | None = None) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field} must not be empty.")
    if max_length is not None and len(normalized) > max_length:
        raise ValueError(f"{field} exceeds its maximum length.")
    return normalized


def _utc(value: datetime.datetime) -> datetime.datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Datetime values must be timezone-aware.")
    return value.astimezone(datetime.UTC)
