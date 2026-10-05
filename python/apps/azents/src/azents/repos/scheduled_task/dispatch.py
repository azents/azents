"""Completed leased Scheduled Task claims and atomic admissions."""

from __future__ import annotations

import datetime
from collections.abc import Callable
from dataclasses import dataclass
from typing import NamedTuple

from azcommon.uuid import uuid7

from azents.core.enums import (
    MailboxItemKind,
    MailboxSchedulingMode,
    ScheduledTaskScheduleType,
)
from azents.core.mailbox_data import (
    MailboxItemCreate,
    ScheduledTaskTriggerMailboxPayload,
)
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import WriteSession
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.mailbox import MailboxRepository
from azents.repos.scheduled_task.data import (
    ScheduledTask,
)
from azents.repos.scheduled_task.definition import RDBScheduledTaskAuthorityValidator
from azents.repos.scheduled_task.presentation import (
    render_scheduled_task_runtime_message,
)
from azents.repos.scheduled_task.repository import ScheduledTaskRepository
from azents.repos.scheduled_task.schedule import (
    InvalidScheduledTaskSchedule,
    advance_cron_cursor,
)
from azents.repos.scheduled_task_cycle import ScheduledTaskCycleRepository
from azents.repos.scheduled_task_cycle.data import (
    ScheduledTaskCycleSnapshot,
)


class _CronScheduleValues(NamedTuple):
    """Validated cron expression and timezone."""

    cron_expression: str
    timezone: str


_DEFAULT_LEASE = datetime.timedelta(seconds=60)


@dataclass(frozen=True)
class ScheduledTaskDispatchOutcome:
    """Outcome of one claimed Task admission transaction."""

    admitted: bool = False
    coalesced: bool = False
    skipped: bool = False


class ScheduledTaskDispatchRepository:
    """Completed PostgreSQL due claims and atomic Task admission."""

    def __init__(
        self,
        session_manager: SessionManager[WriteSession],
        *,
        agent_session_repository: AgentSessionRepository,
        cycle_repository: ScheduledTaskCycleRepository,
        mailbox_repository: MailboxRepository,
        authority_validator: RDBScheduledTaskAuthorityValidator,
        task_repository: ScheduledTaskRepository,
        clock: Callable[[], datetime.datetime],
        lease_duration: datetime.timedelta = _DEFAULT_LEASE,
    ) -> None:
        self.session_manager = session_manager
        self.agent_session_repository = agent_session_repository
        self.cycle_repository = cycle_repository
        self.mailbox_repository = mailbox_repository
        self.authority_validator = authority_validator
        self.task_repository = task_repository
        self.clock = clock
        self.lease_duration = lease_duration

    async def claim_due(
        self, *, now: datetime.datetime, lease_owner: str
    ) -> ScheduledTask | None:
        """Return one detached due claim after its lease transaction closes."""
        async with self.session_manager() as session:
            claimed = await self.task_repository.claim_due(
                session,
                now=now,
                lease_owner=lease_owner,
                lease_until=now + self.lease_duration,
                limit=1,
            )
            return claimed[0] if claimed else None

    async def admit_claimed(
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
                cursor_advance = advance_cron_cursor(
                    expression=cron_expression,
                    timezone=timezone,
                    cursor=task.next_eligible_at,
                    now=now,
                )
                future = cursor_advance.first_future
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
                cursor_advance = advance_cron_cursor(
                    expression=cron_expression,
                    timezone=timezone,
                    cursor=task.next_eligible_at,
                    now=now,
                )
                scheduled_for = cursor_advance.first_due
                next_eligible_at = cursor_advance.first_future
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
                    requested_enabled_execution_options=[],
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
        session: WriteSession,
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


def _cron_values(task: ScheduledTask) -> _CronScheduleValues:
    if task.cron_expression is None or task.timezone is None:
        raise InvalidScheduledTaskSchedule("Persisted cron schedule is incomplete.")
    return _CronScheduleValues(
        cron_expression=task.cron_expression,
        timezone=task.timezone,
    )


def _utc(value: datetime.datetime) -> datetime.datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Datetime values must be timezone-aware.")
    return value.astimezone(datetime.UTC)
