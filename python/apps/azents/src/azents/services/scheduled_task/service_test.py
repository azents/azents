"""Scheduled Task service and dispatcher tests."""

import dataclasses
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
from azents.repos.scheduled_task.schedule import InvalidScheduledTaskSchedule
from azents.repos.scheduled_task_cycle import ScheduledTaskCycleRepository
from azents.repos.scheduled_task_cycle.data import ScheduledTaskCycleSnapshot
from azents.services.chat.live_events import mailbox_item_to_live_event

from .service import (
    RDBScheduledTaskAuthorityValidator,
    ScheduledTaskDispatcher,
    ScheduledTaskService,
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
        self.delete_calls: list[dict[str, str]] = []

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

    async def delete_by_session_and_id(
        self,
        session: AsyncSession,
        *,
        session_id: str,
        task_id: str,
    ) -> bool:
        tx = cast(_TransactionSession, session)
        tx.staged.append("task_deleted")
        self.delete_calls.append(
            {
                "session_id": session_id,
                "task_id": task_id,
            }
        )
        return session_id == self.claimed.session_id and task_id == self.claimed.id


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
    """Accept or reject one test Task authority target."""

    def __init__(self, error: InvalidScheduledTaskSchedule | None) -> None:
        self.error = error

    async def validate(
        self,
        session: AsyncSession,
        task: ScheduledTask,
    ) -> None:
        del session, task
        if self.error is not None:
            raise self.error


class _SelectiveAuthorityValidator:
    """Reject one exact Task while accepting later work in the same pass."""

    def __init__(self, invalid_task_id: str) -> None:
        self.invalid_task_id = invalid_task_id

    async def validate(
        self,
        session: AsyncSession,
        task: ScheduledTask,
    ) -> None:
        del session
        if task.id == self.invalid_task_id:
            raise InvalidScheduledTaskSchedule("Session authority is stale.")


class _SequentialTaskRepository(_TaskRepository):
    """Claim exact Tasks in order for one multi-item dispatcher pass."""

    def __init__(self, tasks: list[ScheduledTask]) -> None:
        super().__init__(claimed=tasks[0], locked=tasks[0])
        self.tasks = tasks

    async def claim_due(
        self,
        session: AsyncSession,
        *,
        now: datetime.datetime,
        lease_owner: str,
        lease_until: datetime.datetime,
        limit: int,
    ) -> list[ScheduledTask]:
        del session, now, lease_owner, lease_until
        assert limit == 1
        index = self.claim_calls
        self.claim_calls += 1
        return [self.tasks[index]] if index < len(self.tasks) else []

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
        task = next((item for item in self.tasks if item.id == task_id), None)
        lease_until = None if task is None else task.lease_until
        if (
            task is None
            or task.lease_owner != lease_owner
            or lease_until != lease_token
            or lease_until is None
            or lease_until <= now
        ):
            return None
        return task

    async def delete_by_session_and_id(
        self,
        session: AsyncSession,
        *,
        session_id: str,
        task_id: str,
    ) -> bool:
        tx = cast(_TransactionSession, session)
        tx.staged.append("task_deleted")
        self.delete_calls.append(
            {
                "session_id": session_id,
                "task_id": task_id,
            }
        )
        return any(
            task.id == task_id and task.session_id == session_id for task in self.tasks
        )


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


class _ProviderMutationTaskRepository:
    """Record the shared provider mutation target lookup order."""

    def __init__(
        self,
        *,
        candidate: ScheduledTask,
        locked: ScheduledTask,
    ) -> None:
        self.candidate = candidate
        self.locked = locked
        self.calls: list[str] = []

    async def get_by_id(
        self,
        session: AsyncSession,
        task_id: str,
    ) -> ScheduledTask | None:
        del session
        self.calls.append("get_by_id")
        return self.candidate if task_id == self.candidate.id else None

    async def get_by_session_and_id(
        self,
        session: AsyncSession,
        *,
        session_id: str,
        task_id: str,
        lock: bool = False,
    ) -> ScheduledTask | None:
        del session
        self.calls.append("get_by_session_and_id:lock" if lock else "get_by_session")
        if session_id != self.candidate.session_id or task_id != self.candidate.id:
            return None
        return self.locked if lock else self.candidate

    async def lock_by_id(
        self,
        session: AsyncSession,
        task_id: str,
    ) -> ScheduledTask | None:
        del session, task_id
        self.calls.append("lock_by_id")
        raise AssertionError("Provider mutation must not lock Task before Mailbox.")


def _dispatcher(
    *,
    manager: _SessionManager,
    repository: _TaskRepository,
    cycle_repository: _CycleRepository,
    mailbox_repository: _MailboxRepository,
    broker: _Broker,
    clock: Callable[[], datetime.datetime],
    authority_validator: _AuthorityValidator | _SelectiveAuthorityValidator,
    batch_size: int = 1,
) -> ScheduledTaskDispatcher:
    """Compose a dispatcher from deterministic fakes."""
    return ScheduledTaskDispatcher(
        session_manager=cast(SessionManager[AsyncSession], manager),
        cycle_repository=cast(ScheduledTaskCycleRepository, cycle_repository),
        mailbox_repository=cast(MailboxRepository, mailbox_repository),
        broker=cast(SessionBroker, broker),
        authority_validator=cast(
            RDBScheduledTaskAuthorityValidator,
            authority_validator,
        ),
        task_repository=cast(ScheduledTaskRepository, repository),
        clock=clock,
        batch_size=batch_size,
        lease_duration=datetime.timedelta(minutes=1),
    )


@pytest.mark.asyncio
async def test_provider_mutation_uses_shared_lock_order_and_fences_binding() -> None:
    """A changed Binding is rejected after Mailbox/cycle/Task locking, not before."""
    candidate = dataclasses.replace(
        _task(),
        binding_id="binding-before-lock",
    )
    locked = dataclasses.replace(
        candidate,
        binding_id="binding-after-lock",
    )
    repository = _ProviderMutationTaskRepository(
        candidate=candidate,
        locked=locked,
    )
    service = ScheduledTaskService(
        repository=cast(ScheduledTaskRepository, repository),
        cycle_repository=cast(ScheduledTaskCycleRepository, object()),
        mailbox_repository=cast(MailboxRepository, object()),
        authority_validator=cast(RDBScheduledTaskAuthorityValidator, object()),
    )

    target = await service.lock_provider_mutation_target(
        cast(AsyncSession, object()),
        task_id=candidate.id,
        expected_binding_id="binding-before-lock",
    )

    assert target is None
    assert repository.calls == [
        "get_by_id",
        "get_by_session",
        "get_by_session_and_id:lock",
    ]
    assert "lock_by_id" not in repository.calls


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
        authority_validator=_AuthorityValidator(None),
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
            _NOW,
            _NOW + datetime.timedelta(seconds=30),
            _NOW + datetime.timedelta(minutes=1, seconds=1),
        ),
        authority_validator=_AuthorityValidator(None),
    )

    with pytest.raises(RuntimeError, match="claim fence was lost"):
        await dispatcher.dispatch_once(lease_owner="scheduler-1")

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
        authority_validator=_AuthorityValidator(None),
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
        authority_validator=_AuthorityValidator(None),
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
    assert "Schedule: August 16, 2026 at 12:00 AM UTC" in event.payload.content
    assert "Schedule details: 2026-08-16T00:00:00Z" in event.payload.content
    assert "Scheduled for details: 2026-08-16T00:00:00Z" in event.payload.content
    assert event.payload.content.endswith(f"Prompt:\n{task.objective}")
    assert "submit a failed result explaining what is missing" in event.payload.content
    assert broker.messages == [SessionWakeUp(session_id=task.session_id)]


@pytest.mark.asyncio
async def test_dispatch_controlled_now_drives_recurring_cursor_and_lease() -> None:
    """A test-controlled pass never mixes its instant with the wall clock."""
    controlled_now = _NOW + datetime.timedelta(minutes=5)
    task = _task(
        schedule_type=ScheduledTaskScheduleType.CRON,
        lease_until=controlled_now + datetime.timedelta(minutes=1),
    )
    manager = _SessionManager()
    repository = _TaskRepository(claimed=task, locked=task)
    cycle_repository = _CycleRepository()
    mailbox_repository = _MailboxRepository()
    broker = _Broker()

    def unexpected_clock() -> datetime.datetime:
        raise AssertionError("Controlled dispatch must not read the wall clock.")

    dispatcher = _dispatcher(
        manager=manager,
        repository=repository,
        cycle_repository=cycle_repository,
        mailbox_repository=mailbox_repository,
        broker=broker,
        clock=unexpected_clock,
        authority_validator=_AuthorityValidator(None),
    )

    summary = await dispatcher.dispatch_once(
        lease_owner="scheduler-1",
        now=controlled_now,
    )

    assert summary.admitted == 1
    assert cycle_repository.snapshots[0].scheduled_for == _NOW
    assert repository.complete_calls[0]["lease_now"] == controlled_now
    assert repository.complete_calls[0]["next_eligible_at"] == (
        controlled_now + datetime.timedelta(minutes=1)
    )


@pytest.mark.asyncio
async def test_dispatch_deletes_invalid_authority_and_continues() -> None:
    """Invalid authority fails closed without aborting later work in the pass."""
    invalid = _task()
    valid = dataclasses.replace(
        _task(),
        id="v" * 32,
        session_id="r" * 32,
    )
    manager = _SessionManager()
    repository = _SequentialTaskRepository([invalid, valid])
    cycle_repository = _CycleRepository()
    mailbox_repository = _MailboxRepository()
    broker = _Broker()
    dispatcher = _dispatcher(
        manager=manager,
        repository=repository,
        cycle_repository=cycle_repository,
        mailbox_repository=mailbox_repository,
        broker=broker,
        clock=_clock(),
        authority_validator=_SelectiveAuthorityValidator(invalid.id),
        batch_size=2,
    )

    summary = await dispatcher.dispatch_once(lease_owner="scheduler-1", now=_NOW)

    assert summary.claimed == 2
    assert summary.admitted == 1
    assert summary.skipped == 1
    assert repository.delete_calls == [
        {
            "session_id": invalid.session_id,
            "task_id": invalid.id,
        }
    ]
    assert len(repository.complete_calls) == 1
    assert len(cycle_repository.snapshots) == 1
    assert cycle_repository.snapshots[0].task_id == valid.id
    assert len(mailbox_repository.creates) == 1
    assert manager.committed == ["task_deleted", "cycle", "mailbox"]
    assert broker.messages == [SessionWakeUp(session_id=valid.session_id)]
