"""Scheduled Task service and dispatcher tests."""

import datetime
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from azents.broker.types import SessionBroker, SessionWakeUp
from azents.core.enums import (
    MailboxItemKind,
    MailboxSchedulingMode,
    ScheduledTaskScheduleType,
)
from azents.engine.events.types import ScheduledTaskTriggerPayload
from azents.rdb.session import SessionManager
from azents.repos.mailbox import MailboxRepository
from azents.repos.mailbox.data import MailboxItem, MailboxItemCreate
from azents.repos.scheduled_task.data import ScheduledTask
from azents.repos.scheduled_task.repository import ScheduledTaskRepository
from azents.repos.scheduled_task_cycle import ScheduledTaskCycleRepository
from azents.repos.scheduled_task_cycle.data import ScheduledTaskCycleSnapshot
from azents.services.chat.live_events import mailbox_item_to_live_event

from .service import (
    RDBScheduledTaskAuthorityValidator,
    ScheduledTaskDispatcher,
)

_NOW = datetime.datetime(2026, 8, 16, 0, 0, tzinfo=datetime.UTC)


class _TransactionSession:
    """Record writes that become visible only when the context commits."""

    def __init__(self) -> None:
        self.staged: list[str] = []


class _SessionManager:
    """Minimal transaction manager with commit/rollback observation."""

    def __init__(self) -> None:
        self.committed: list[str] = []

    @asynccontextmanager
    async def __call__(self) -> AsyncIterator[AsyncSession]:
        session = _TransactionSession()
        try:
            yield cast(AsyncSession, session)
        except Exception:
            raise
        else:
            self.committed.extend(session.staged)


class _TaskRepository:
    """Deterministic lease-aware dispatcher repository double."""

    def __init__(
        self,
        *,
        claimed: ScheduledTask,
        locked: ScheduledTask | None,
    ) -> None:
        self.claimed = claimed
        self.locked = locked
        self.claim_calls = 0
        self.lock_calls: list[dict[str, object]] = []
        self.complete_calls: list[dict[str, object]] = []

    async def claim_due(
        self,
        session: AsyncSession,
        *,
        now: datetime.datetime,
        lease_owner: str,
        lease_until: datetime.datetime,
        limit: int,
    ) -> list[ScheduledTask]:
        del session, now, lease_owner, lease_until, limit
        self.claim_calls += 1
        return [self.claimed] if self.claim_calls == 1 else []

    async def lock_claimed_by_id(
        self,
        session: AsyncSession,
        *,
        task_id: str,
        lease_owner: str,
        lease_token: datetime.datetime,
        now: datetime.datetime,
    ) -> ScheduledTask | None:
        del session
        self.lock_calls.append(
            {
                "task_id": task_id,
                "lease_owner": lease_owner,
                "lease_token": lease_token,
                "now": now,
            }
        )
        task = self.locked
        lease_until = None if task is None else task.lease_until
        if (
            task is None
            or task.id != task_id
            or task.lease_owner != lease_owner
            or lease_until != lease_token
            or lease_until is None
            or lease_until <= now
        ):
            return None
        return task

    async def complete_claim(
        self,
        session: AsyncSession,
        **kwargs: object,
    ) -> bool:
        del session
        self.complete_calls.append(kwargs)
        lease_token = kwargs["lease_token"]
        lease_now = kwargs["lease_now"]
        assert isinstance(lease_token, datetime.datetime)
        assert isinstance(lease_now, datetime.datetime)
        return lease_token > lease_now


class _CycleRepository:
    """Stage admitted cycle creation inside the fake transaction."""

    def __init__(self) -> None:
        self.snapshots: list[ScheduledTaskCycleSnapshot] = []

    async def create_admitted(
        self,
        session: AsyncSession,
        snapshot: ScheduledTaskCycleSnapshot,
    ) -> object:
        tx = cast(_TransactionSession, session)
        tx.staged.append("cycle")
        self.snapshots.append(snapshot)
        return object()


class _MailboxRepository:
    """Stage one idempotent trigger inside the fake transaction."""

    def __init__(self) -> None:
        self.creates: list[MailboxItemCreate] = []

    async def create_idempotent(
        self,
        session: AsyncSession,
        create: MailboxItemCreate,
        *,
        idempotency_key: str,
    ) -> object:
        tx = cast(_TransactionSession, session)
        tx.staged.append("mailbox")
        assert create.idempotency_key == idempotency_key
        self.creates.append(create)
        return object()


class _AuthorityValidator:
    """Accept every test Task authority target."""

    async def validate(
        self,
        session: AsyncSession,
        task: ScheduledTask,
    ) -> None:
        del session, task


class _Broker:
    """Record or fail post-commit Session wake delivery."""

    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.messages: list[SessionWakeUp] = []

    async def send_message(self, message: SessionWakeUp) -> None:
        self.messages.append(message)
        if self.fail:
            raise RuntimeError("wake unavailable")


def _task(
    *,
    schedule_type: ScheduledTaskScheduleType = ScheduledTaskScheduleType.ONCE,
    lease_until: datetime.datetime = _NOW + datetime.timedelta(minutes=1),
    active_cycle_id: str | None = None,
    pending_scheduled_for: datetime.datetime | None = None,
) -> ScheduledTask:
    """Build one claimed Task fixture."""
    cron = schedule_type is ScheduledTaskScheduleType.CRON
    return ScheduledTask(
        id="t" * 32,
        workspace_id="w" * 32,
        agent_id="a" * 32,
        session_id="s" * 32,
        binding_id=None,
        title="Daily report",
        objective="Prepare the daily report.",
        schedule_type=schedule_type,
        scheduled_at=None if cron else _NOW,
        cron_expression="* * * * *" if cron else None,
        timezone="UTC" if cron else None,
        next_eligible_at=_NOW,
        active_cycle_id=active_cycle_id,
        active_scheduled_for=_NOW if active_cycle_id is not None else None,
        pending_scheduled_for=pending_scheduled_for,
        lease_owner="scheduler-1",
        lease_until=lease_until,
        created_at=_NOW,
        updated_at=_NOW,
    )


def _clock(*values: datetime.datetime) -> Callable[[], datetime.datetime]:
    """Return a clock that advances through exact test instants."""
    iterator = iter(values)
    return lambda: next(iterator)


def _dispatcher(
    *,
    manager: _SessionManager,
    repository: _TaskRepository,
    cycle_repository: _CycleRepository,
    mailbox_repository: _MailboxRepository,
    broker: _Broker,
    clock: Callable[[], datetime.datetime],
) -> ScheduledTaskDispatcher:
    """Compose a dispatcher from deterministic fakes."""
    return ScheduledTaskDispatcher(
        session_manager=cast(SessionManager[AsyncSession], manager),
        cycle_repository=cast(ScheduledTaskCycleRepository, cycle_repository),
        mailbox_repository=cast(MailboxRepository, mailbox_repository),
        broker=cast(SessionBroker, broker),
        authority_validator=cast(
            RDBScheduledTaskAuthorityValidator,
            _AuthorityValidator(),
        ),
        task_repository=cast(ScheduledTaskRepository, repository),
        clock=clock,
        batch_size=1,
        lease_duration=datetime.timedelta(minutes=1),
    )


@pytest.mark.asyncio
async def test_dispatch_rejects_same_owner_newer_lease_token() -> None:
    """A stale claimant cannot adopt a newer claim with the same owner identity."""
    original = _task(lease_until=_NOW + datetime.timedelta(minutes=1))
    newer = _task(lease_until=_NOW + datetime.timedelta(minutes=2))
    manager = _SessionManager()
    repository = _TaskRepository(claimed=original, locked=newer)
    cycle_repository = _CycleRepository()
    mailbox_repository = _MailboxRepository()
    broker = _Broker()
    dispatcher = _dispatcher(
        manager=manager,
        repository=repository,
        cycle_repository=cycle_repository,
        mailbox_repository=mailbox_repository,
        broker=broker,
        clock=_clock(_NOW + datetime.timedelta(seconds=10)),
    )

    with pytest.raises(RuntimeError, match="claim fence was lost"):
        await dispatcher.dispatch_once(lease_owner="scheduler-1", now=_NOW)

    assert repository.lock_calls[0]["lease_token"] == original.lease_until
    assert cycle_repository.snapshots == []
    assert mailbox_repository.creates == []
    assert manager.committed == []
    assert broker.messages == []


@pytest.mark.asyncio
async def test_dispatch_rolls_back_when_lease_expires_during_admission() -> None:
    """Roll back cycle and Mailbox writes when admission outlives its lease."""
    task = _task(lease_until=_NOW + datetime.timedelta(minutes=1))
    manager = _SessionManager()
    repository = _TaskRepository(claimed=task, locked=task)
    cycle_repository = _CycleRepository()
    mailbox_repository = _MailboxRepository()
    broker = _Broker()
    dispatcher = _dispatcher(
        manager=manager,
        repository=repository,
        cycle_repository=cycle_repository,
        mailbox_repository=mailbox_repository,
        broker=broker,
        clock=_clock(
            _NOW + datetime.timedelta(seconds=30),
            _NOW + datetime.timedelta(minutes=1, seconds=1),
        ),
    )

    with pytest.raises(RuntimeError, match="claim fence was lost"):
        await dispatcher.dispatch_once(lease_owner="scheduler-1", now=_NOW)

    assert len(cycle_repository.snapshots) == 1
    assert len(mailbox_repository.creates) == 1
    assert manager.committed == []
    assert broker.messages == []


@pytest.mark.asyncio
async def test_dispatch_coalesces_active_recurring_occurrence_without_wake() -> None:
    """An active recurring cycle keeps one earliest pending occurrence."""
    task = _task(
        schedule_type=ScheduledTaskScheduleType.CRON,
        lease_until=_NOW + datetime.timedelta(minutes=10),
        active_cycle_id="c" * 32,
    )
    manager = _SessionManager()
    repository = _TaskRepository(claimed=task, locked=task)
    cycle_repository = _CycleRepository()
    mailbox_repository = _MailboxRepository()
    broker = _Broker()
    dispatcher = _dispatcher(
        manager=manager,
        repository=repository,
        cycle_repository=cycle_repository,
        mailbox_repository=mailbox_repository,
        broker=broker,
        clock=_clock(
            _NOW + datetime.timedelta(minutes=5),
            _NOW + datetime.timedelta(minutes=5, seconds=1),
        ),
    )

    summary = await dispatcher.dispatch_once(
        lease_owner="scheduler-1",
        now=_NOW + datetime.timedelta(minutes=5),
    )

    assert summary.claimed == 1
    assert summary.coalesced == 1
    assert summary.admitted == 0
    assert repository.complete_calls[0]["pending_scheduled_for"] == _NOW
    assert cycle_repository.snapshots == []
    assert mailbox_repository.creates == []
    assert broker.messages == []


@pytest.mark.asyncio
async def test_dispatch_commits_trigger_before_counting_wake_failure() -> None:
    """Wake failure is diagnostic and never rolls back canonical admission."""
    task = _task()
    manager = _SessionManager()
    repository = _TaskRepository(claimed=task, locked=task)
    cycle_repository = _CycleRepository()
    mailbox_repository = _MailboxRepository()
    broker = _Broker(fail=True)
    dispatcher = _dispatcher(
        manager=manager,
        repository=repository,
        cycle_repository=cycle_repository,
        mailbox_repository=mailbox_repository,
        broker=broker,
        clock=_clock(
            _NOW + datetime.timedelta(seconds=10),
            _NOW + datetime.timedelta(seconds=20),
        ),
    )

    summary = await dispatcher.dispatch_once(lease_owner="scheduler-1", now=_NOW)

    assert summary.claimed == 1
    assert summary.admitted == 1
    assert summary.wake_failed == 1
    assert manager.committed == ["cycle", "mailbox"]
    assert len(cycle_repository.snapshots) == 1
    trigger = mailbox_repository.creates[0]
    assert trigger.kind is MailboxItemKind.SCHEDULED_TASK_TRIGGER
    assert trigger.scheduling_mode is MailboxSchedulingMode.WAKE_SESSION
    assert trigger.session_id == task.session_id
    assert trigger.idempotency_key is not None
    assert trigger.payload is not None
    assert trigger.payload.items[0].metadata["title"] == task.title
    event = mailbox_item_to_live_event(
        MailboxItem(
            id="m" * 32,
            session_id=trigger.session_id,
            kind=trigger.kind,
            scheduling_mode=trigger.scheduling_mode,
            requested_model_target_label=trigger.requested_model_target_label,
            requested_reasoning_effort=trigger.requested_reasoning_effort,
            sender_user_id=trigger.sender_user_id,
            order_group="m" * 32,
            order_sequence=trigger.order_sequence,
            content=trigger.content,
            idempotency_key=trigger.idempotency_key,
            metadata=trigger.metadata,
            action=trigger.action,
            attachments=trigger.attachments,
            file_parts=trigger.file_parts,
            payload=trigger.payload,
            created_at=_NOW,
        )
    )
    assert event is not None
    assert isinstance(event.payload, ScheduledTaskTriggerPayload)
    assert event.payload.title == task.title
    assert "Schedule: 2026-08-16T00:00:00Z" in event.payload.content
    assert "Scheduled for: 2026-08-16T00:00:00Z" in event.payload.content
    assert "submit a failed result explaining what is missing" in event.payload.content
    assert broker.messages == [SessionWakeUp(session_id=task.session_id)]
