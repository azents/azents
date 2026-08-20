"""Scheduled Task management authorization and locking tests."""

import dataclasses
import datetime
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    AgentLifecycleStatus,
    AgentSessionKind,
    AgentSessionProductMode,
    AgentSessionStatus,
    ScheduledTaskScheduleType,
)
from azents.rdb.session import SessionManager
from azents.repos.agent import AgentRepository
from azents.repos.agent_session.repository import AgentSessionRepository
from azents.repos.external_channel.management import (
    ExternalChannelManagementRepository,
)
from azents.repos.external_channel.repository import ExternalChannelRepository
from azents.repos.mailbox import MailboxRepository
from azents.repos.scheduled_task.data import ScheduledTask
from azents.repos.scheduled_task.repository import ScheduledTaskRepository
from azents.repos.scheduled_task.schedule import InvalidScheduledTaskSchedule
from azents.repos.scheduled_task_cycle import ScheduledTaskCycleRepository
from azents.repos.scheduled_task_cycle.data import (
    ScheduledTaskCycleRecord,
    ScheduledTaskCycleState,
)
from azents.services.scheduled_task.channel import ScheduledTaskChannelService
from azents.services.scheduled_task.service import ScheduledTaskAuthorityValidator

from .management import (
    ScheduledTaskManagementService,
    ScheduledTaskManagementUnavailable,
)

_NOW = datetime.datetime(2026, 8, 16, tzinfo=datetime.UTC)
_WORKSPACE_ID = "w" * 32
_AGENT_ID = "a" * 32
_SESSION_ID = "s" * 32
_TASK_ID = "t" * 32
_CURRENT_BINDING_ID = "b" * 32
_REQUESTED_BINDING_ID = "c" * 32


class _Session:
    """Minimal AsyncSession substitute with commit observation."""

    def __init__(self) -> None:
        self.committed = False

    async def commit(self) -> None:
        self.committed = True


class _SessionManager:
    """Yield one stable unit-test session."""

    def __init__(self) -> None:
        self.session = _Session()

    @asynccontextmanager
    async def __call__(self) -> AsyncIterator[AsyncSession]:
        yield cast(AsyncSession, self.session)


class _AgentRepository:
    """Return one active Agent authority."""

    def __init__(
        self,
        events: list[str] | None = None,
        *,
        lifecycle_status: AgentLifecycleStatus = AgentLifecycleStatus.ACTIVE,
    ) -> None:
        self.events = events
        self.lifecycle_status = lifecycle_status

    async def get_by_id(
        self,
        session: AsyncSession,
        agent_id: str,
    ) -> object | None:
        del session
        if agent_id != _AGENT_ID:
            return None
        return SimpleNamespace(
            id=_AGENT_ID,
            workspace_id=_WORKSPACE_ID,
            lifecycle_status=self.lifecycle_status,
            enabled=True,
        )

    async def lock_by_id(
        self,
        session: AsyncSession,
        agent_id: str,
    ) -> object | None:
        if self.events is not None:
            self.events.append("agent-lock")
        return await self.get_by_id(session, agent_id)


class _AgentSessionRepository:
    """Return one authorized root Team Session."""

    def __init__(
        self,
        events: list[str] | None = None,
        *,
        agent_id: str = _AGENT_ID,
        status: AgentSessionStatus = AgentSessionStatus.ACTIVE,
    ) -> None:
        self.events = events
        self.agent_id = agent_id
        self.status = status

    async def get_by_id(
        self,
        session: AsyncSession,
        session_id: str,
    ) -> object | None:
        del session
        if session_id != _SESSION_ID:
            return None
        return SimpleNamespace(
            id=_SESSION_ID,
            workspace_id=_WORKSPACE_ID,
            agent_id=self.agent_id,
            handle="scheduled-session",
            title="Scheduled work",
            session_kind=AgentSessionKind.ROOT,
            status=self.status,
            product_mode=AgentSessionProductMode.TEAM,
            associated_user_id=None,
        )

    async def lock_by_id(
        self,
        session: AsyncSession,
        session_id: str,
    ) -> object | None:
        if self.events is not None:
            self.events.append("session-lock")
        return await self.get_by_id(session, session_id)


class _AuthorityValidator:
    """Record exact target validation and optionally reject a Binding."""

    def __init__(
        self,
        events: list[str],
        *,
        unavailable_binding_id: str | None = None,
    ) -> None:
        self.events = events
        self.unavailable_binding_id = unavailable_binding_id

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
        del session
        assert workspace_id == _WORKSPACE_ID
        assert agent_id == _AGENT_ID
        assert session_id == _SESSION_ID
        self.events.append(f"authority:{binding_id}")
        if binding_id == self.unavailable_binding_id:
            raise InvalidScheduledTaskSchedule("Binding is unavailable.")


class _ExternalChannelRepository:
    """Record deterministic Binding row locks."""

    def __init__(self, events: list[str]) -> None:
        self.events = events

    async def lock_binding(
        self,
        session: AsyncSession,
        *,
        binding_id: str,
    ) -> None:
        del session
        self.events.append(f"binding-lock:{binding_id}")


class _TaskRepository:
    """Exercise the real shared management mutation lock path."""

    def __init__(
        self,
        events: list[str],
        *,
        task: ScheduledTask | None,
        second_snapshot: ScheduledTask | None = None,
    ) -> None:
        self.events = events
        self.task = task
        self.second_snapshot = second_snapshot
        self.get_count = 0
        self.created = False
        self.replaced = False

    async def get_by_id(
        self,
        session: AsyncSession,
        task_id: str,
    ) -> ScheduledTask | None:
        del session
        self.get_count += 1
        self.events.append(f"task-candidate:{self.get_count}")
        if task_id != _TASK_ID:
            return None
        if self.get_count == 2 and self.second_snapshot is not None:
            return self.second_snapshot
        return self.task

    async def get_by_session_and_id(
        self,
        session: AsyncSession,
        *,
        session_id: str,
        task_id: str,
        lock: bool = False,
    ) -> ScheduledTask | None:
        del session
        self.events.append("task-lock" if lock else "task-read")
        if session_id != _SESSION_ID or task_id != _TASK_ID:
            return None
        return self.task

    async def create(self, session: AsyncSession, create: object) -> ScheduledTask:
        del session, create
        self.created = True
        raise AssertionError("Unexpected Task creation.")

    async def replace(self, session: AsyncSession, **kwargs: object) -> ScheduledTask:
        del session, kwargs
        self.replaced = True
        raise AssertionError("Unexpected Task replacement.")


class _CycleRepository:
    """Return one optional cycle while recording shared lock order."""

    def __init__(
        self,
        events: list[str],
        *,
        record: ScheduledTaskCycleRecord | None = None,
    ) -> None:
        self.events = events
        self.record = record

    async def get(self, session: AsyncSession, **kwargs: object) -> object | None:
        del session, kwargs
        self.events.append("cycle-read")
        return self.record

    async def lock(self, session: AsyncSession, **kwargs: object) -> object | None:
        del session, kwargs
        self.events.append("cycle-lock")
        return self.record


class _MailboxRepository:
    """Record the Mailbox phase of shared mutation locking."""

    def __init__(self, events: list[str]) -> None:
        self.events = events

    async def get_by_idempotency_key(
        self,
        session: AsyncSession,
        **kwargs: object,
    ) -> None:
        del session, kwargs
        self.events.append("mailbox-read")
        return None


def _task(
    *,
    binding_id: str | None = None,
    active_cycle_id: str | None = None,
) -> ScheduledTask:
    return ScheduledTask(
        id=_TASK_ID,
        workspace_id=_WORKSPACE_ID,
        agent_id=_AGENT_ID,
        session_id=_SESSION_ID,
        binding_id=binding_id,
        title="Daily report",
        objective="Prepare the daily report.",
        schedule_type=ScheduledTaskScheduleType.ONCE,
        scheduled_at=_NOW,
        cron_expression=None,
        timezone=None,
        next_eligible_at=_NOW,
        active_cycle_id=active_cycle_id,
        active_scheduled_for=_NOW if active_cycle_id is not None else None,
        pending_scheduled_for=None,
        lease_owner=None,
        lease_until=None,
        created_at=_NOW,
        updated_at=_NOW,
    )


def _started_cycle() -> ScheduledTaskCycleRecord:
    cycle_id = "y" * 32
    return ScheduledTaskCycleRecord(
        state=ScheduledTaskCycleState(
            cycle_id=cycle_id,
            task_id=_TASK_ID,
            phase="started",
            workspace_id=_WORKSPACE_ID,
            agent_id=_AGENT_ID,
            session_id=_SESSION_ID,
            binding_id=_CURRENT_BINDING_ID,
            title="Daily report",
            objective="Prepare the daily report.",
            schedule_type=ScheduledTaskScheduleType.ONCE,
            scheduled_at=_NOW,
            cron_expression=None,
            timezone=None,
            scheduled_for=_NOW,
            current_run_id="r" * 32,
            started_at=_NOW,
            progress_title=None,
            ordered_tasks=[],
        ),
        version=1,
        toolkit_state_id="k" * 32,
    )


def _service(
    *,
    events: list[str],
    task_repository: _TaskRepository,
    authority_validator: _AuthorityValidator,
    agent_session_repository: _AgentSessionRepository | None = None,
    agent_repository: _AgentRepository | None = None,
    cycle_repository: _CycleRepository | None = None,
) -> ScheduledTaskManagementService:
    return ScheduledTaskManagementService(
        session_manager=cast(SessionManager[AsyncSession], _SessionManager()),
        agent_repository=cast(
            AgentRepository,
            agent_repository or _AgentRepository(events),
        ),
        agent_session_repository=cast(
            AgentSessionRepository,
            agent_session_repository or _AgentSessionRepository(events),
        ),
        task_repository=cast(ScheduledTaskRepository, task_repository),
        cycle_repository=cast(
            ScheduledTaskCycleRepository,
            cycle_repository or _CycleRepository(events),
        ),
        mailbox_repository=cast(MailboxRepository, _MailboxRepository(events)),
        external_channel_repository=cast(
            ExternalChannelRepository,
            _ExternalChannelRepository(events),
        ),
        external_channel_management_repository=cast(
            ExternalChannelManagementRepository,
            AsyncMock(spec=ExternalChannelManagementRepository),
        ),
        channel_service=AsyncMock(spec=ScheduledTaskChannelService),
        authority_validator=cast(
            ScheduledTaskAuthorityValidator,
            authority_validator,
        ),
    )


@pytest.mark.asyncio
async def test_requested_binding_is_locked_then_hidden_before_create() -> None:
    """Unavailable Binding authority is an opaque not-found before Task mutation."""
    events: list[str] = []
    repository = _TaskRepository(events, task=None)
    service = _service(
        events=events,
        task_repository=repository,
        authority_validator=_AuthorityValidator(
            events,
            unavailable_binding_id=_REQUESTED_BINDING_ID,
        ),
    )

    with pytest.raises(ScheduledTaskManagementUnavailable) as raised:
        await service.create(
            workspace_id=_WORKSPACE_ID,
            agent_id=_AGENT_ID,
            user_id="user-1",
            session_id=_SESSION_ID,
            title="Daily report",
            objective="Prepare the daily report.",
            at="2099-08-17T00:00:00Z",
            cron=None,
            timezone=None,
            channel_id=_REQUESTED_BINDING_ID,
        )

    assert raised.value.code == "not_found"
    assert events == [
        "session-lock",
        "agent-lock",
        f"binding-lock:{_REQUESTED_BINDING_ID}",
        f"authority:{_REQUESTED_BINDING_ID}",
    ]
    assert not repository.created


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("session_status", "agent_status", "expected_events"),
    [
        (
            AgentSessionStatus.ARCHIVED,
            AgentLifecycleStatus.ACTIVE,
            ["session-lock"],
        ),
        (
            AgentSessionStatus.ACTIVE,
            AgentLifecycleStatus.DECOMMISSIONING,
            ["session-lock", "agent-lock"],
        ),
    ],
)
async def test_create_rejects_locked_lifecycle_authority(
    session_status: AgentSessionStatus,
    agent_status: AgentLifecycleStatus,
    expected_events: list[str],
) -> None:
    """Archive and decommission fences win before Binding or Task mutation."""
    events: list[str] = []
    repository = _TaskRepository(events, task=None)
    service = _service(
        events=events,
        task_repository=repository,
        authority_validator=_AuthorityValidator(events),
        agent_session_repository=_AgentSessionRepository(
            events,
            status=session_status,
        ),
        agent_repository=_AgentRepository(
            events,
            lifecycle_status=agent_status,
        ),
    )

    with pytest.raises(ScheduledTaskManagementUnavailable) as raised:
        await service.create(
            workspace_id=_WORKSPACE_ID,
            agent_id=_AGENT_ID,
            user_id="user-1",
            session_id=_SESSION_ID,
            title="Daily report",
            objective="Prepare the daily report.",
            at="2099-08-17T00:00:00Z",
            cron=None,
            timezone=None,
            channel_id=_REQUESTED_BINDING_ID,
        )

    assert raised.value.code == "not_found"
    assert events == expected_events
    assert not repository.created


@pytest.mark.asyncio
async def test_invalid_schedule_remains_distinct_from_binding_unavailability() -> None:
    """Canonical schedule errors remain validation failures."""
    events: list[str] = []
    repository = _TaskRepository(events, task=None)
    service = _service(
        events=events,
        task_repository=repository,
        authority_validator=_AuthorityValidator(events),
    )

    with pytest.raises(ScheduledTaskManagementUnavailable) as raised:
        await service.create(
            workspace_id=_WORKSPACE_ID,
            agent_id=_AGENT_ID,
            user_id="user-1",
            session_id=_SESSION_ID,
            title="Daily report",
            objective="Prepare the daily report.",
            at="2099-08-17T00:00:00Z",
            cron="0 8 * * *",
            timezone="UTC",
            channel_id=None,
        )

    assert raised.value.code == "invalid_schedule"
    assert not repository.created


@pytest.mark.asyncio
async def test_wrong_task_and_wrong_session_are_opaque_not_found() -> None:
    """Foreign Task and Session ownership remain indistinguishable from absence."""
    events: list[str] = []
    missing_service = _service(
        events=events,
        task_repository=_TaskRepository(events, task=None),
        authority_validator=_AuthorityValidator(events),
    )
    with pytest.raises(ScheduledTaskManagementUnavailable) as missing:
        await missing_service.get(
            workspace_id=_WORKSPACE_ID,
            agent_id=_AGENT_ID,
            user_id="user-1",
            task_id=_TASK_ID,
        )
    assert missing.value.code == "not_found"

    wrong_session_service = _service(
        events=events,
        task_repository=_TaskRepository(events, task=_task()),
        authority_validator=_AuthorityValidator(events),
        agent_session_repository=_AgentSessionRepository(agent_id="foreign-agent"),
    )
    with pytest.raises(ScheduledTaskManagementUnavailable) as wrong_session:
        await wrong_session_service.get(
            workspace_id=_WORKSPACE_ID,
            agent_id=_AGENT_ID,
            user_id="user-1",
            task_id=_TASK_ID,
        )
    assert wrong_session.value.code == "not_found"


@pytest.mark.asyncio
async def test_binding_locks_and_authority_precede_shared_mutation_fence() -> None:
    """Current/new Binding locks precede validation and stale Task rejection."""
    events: list[str] = []
    candidate = _task(binding_id=_CURRENT_BINDING_ID)
    changed = dataclasses.replace(candidate, binding_id="d" * 32)
    repository = _TaskRepository(
        events,
        task=candidate,
        second_snapshot=changed,
    )
    service = _service(
        events=events,
        task_repository=repository,
        authority_validator=_AuthorityValidator(events),
    )

    with pytest.raises(ScheduledTaskManagementUnavailable) as raised:
        await service.replace(
            workspace_id=_WORKSPACE_ID,
            agent_id=_AGENT_ID,
            user_id="user-1",
            task_id=_TASK_ID,
            title="Updated report",
            objective="Prepare the updated report.",
            at="2099-08-17T00:00:00Z",
            cron=None,
            timezone=None,
            channel_id=_REQUESTED_BINDING_ID,
        )

    assert raised.value.code == "not_found"
    assert events == [
        "task-candidate:1",
        "session-lock",
        "agent-lock",
        f"binding-lock:{_CURRENT_BINDING_ID}",
        f"binding-lock:{_REQUESTED_BINDING_ID}",
        f"authority:{_CURRENT_BINDING_ID}",
        f"authority:{_REQUESTED_BINDING_ID}",
        "task-candidate:2",
    ]
    assert not repository.replaced


@pytest.mark.asyncio
async def test_delete_revalidates_current_binding_before_shared_mutation() -> None:
    """A disconnected current Binding becomes opaque not-found before Task lock."""
    events: list[str] = []
    repository = _TaskRepository(
        events,
        task=_task(binding_id=_CURRENT_BINDING_ID),
    )
    service = _service(
        events=events,
        task_repository=repository,
        authority_validator=_AuthorityValidator(
            events,
            unavailable_binding_id=_CURRENT_BINDING_ID,
        ),
    )

    with pytest.raises(ScheduledTaskManagementUnavailable) as raised:
        await service.delete(
            workspace_id=_WORKSPACE_ID,
            agent_id=_AGENT_ID,
            user_id="user-1",
            task_id=_TASK_ID,
        )

    assert raised.value.code == "not_found"
    assert events == [
        "task-candidate:1",
        "session-lock",
        "agent-lock",
        f"binding-lock:{_CURRENT_BINDING_ID}",
        f"authority:{_CURRENT_BINDING_ID}",
    ]


@pytest.mark.asyncio
async def test_started_one_time_edit_is_conflict_after_canonical_lock_order() -> None:
    """A started one-time cycle is fenced after Binding, Mailbox, cycle, and Task."""
    events: list[str] = []
    cycle = _started_cycle()
    task = _task(
        binding_id=_CURRENT_BINDING_ID,
        active_cycle_id=cycle.state.cycle_id,
    )
    repository = _TaskRepository(events, task=task)
    service = _service(
        events=events,
        task_repository=repository,
        authority_validator=_AuthorityValidator(events),
        cycle_repository=_CycleRepository(events, record=cycle),
    )

    with pytest.raises(ScheduledTaskManagementUnavailable) as raised:
        await service.replace(
            workspace_id=_WORKSPACE_ID,
            agent_id=_AGENT_ID,
            user_id="user-1",
            task_id=_TASK_ID,
            title="Updated report",
            objective="Prepare the updated report.",
            at="2099-08-17T00:00:00Z",
            cron=None,
            timezone=None,
            channel_id=_CURRENT_BINDING_ID,
        )

    assert raised.value.code == "conflict"
    session_index = events.index("session-lock")
    agent_index = events.index("agent-lock")
    binding_index = events.index(f"binding-lock:{_CURRENT_BINDING_ID}")
    mailbox_index = events.index("mailbox-read")
    cycle_lock_index = events.index("cycle-lock")
    task_lock_index = events.index("task-lock")
    assert (
        session_index
        < agent_index
        < binding_index
        < mailbox_index
        < cycle_lock_index
        < task_lock_index
    )
    assert not repository.replaced
