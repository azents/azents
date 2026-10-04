"""Completed Scheduled Toolkit operation tests."""

import datetime
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

from sqlalchemy.ext.asyncio import AsyncSession

from azents.rdb.session_capabilities import ReadWriteSession, WriteSession
from azents.repos.agent_execution import AgentRunRepository
from azents.repos.mailbox import MailboxRepository
from azents.repos.scheduled_task.repository import ScheduledTaskRepository
from azents.repos.scheduled_task.tool_operations import (
    ScheduledTaskToolOperationRepository,
)
from azents.repos.scheduled_task_cycle import ScheduledTaskCycleRepository


async def test_scheduled_tool_operations_close_every_transaction() -> None:
    """Scheduled reads and mutations return only after transaction closure."""
    now = datetime.datetime(2026, 10, 1, tzinfo=datetime.UTC)
    scheduled_at = now + datetime.timedelta(days=1)
    _raw_session = AsyncMock(spec=AsyncSession)
    session = ReadWriteSession(_raw_session)
    transaction_active = False
    transaction_count = 0

    @asynccontextmanager
    async def session_manager() -> AsyncIterator[WriteSession]:
        nonlocal transaction_active, transaction_count
        assert not transaction_active
        transaction_active = True
        transaction_count += 1
        try:
            yield session
        finally:
            transaction_active = False

    tasks = AsyncMock(spec=ScheduledTaskRepository)
    cycles = AsyncMock(spec=ScheduledTaskCycleRepository)
    mailbox = AsyncMock(spec=MailboxRepository)
    runs = AsyncMock(spec=AgentRunRepository)
    cycle = SimpleNamespace(
        state=SimpleNamespace(
            workspace_id="workspace-1",
            current_run_id="run-1",
        )
    )
    runs.get_by_id.return_value = SimpleNamespace(
        session_id="session-1",
        scheduled_task_cycle_id="cycle-1",
    )
    cycles.get_started.return_value = cycle
    cycles.list_started.return_value = [
        SimpleNamespace(state=SimpleNamespace(cycle_id="cycle-1"))
    ]
    tasks.create.return_value = SimpleNamespace(id="task-1")
    tasks.list_by_session_id.return_value = []
    tasks.get_by_session_and_id.return_value = None
    _raw_session.scalar.return_value = object()
    operations = ScheduledTaskToolOperationRepository(
        session_manager=session_manager,
        task_repository=tasks,
        cycle_repository=cycles,
        mailbox_repository=mailbox,
        run_repository=runs,
        owner=None,
    )

    assert (
        await operations.active_cycle(
            workspace_id="workspace-1",
            agent_id="agent-1",
            session_id="session-1",
            run_id="run-1",
        )
        is cycle
    )
    assert not transaction_active

    states = await operations.list_started_cycle_states(
        agent_id="agent-1",
        session_id="session-1",
    )
    assert states[0].cycle_id == "cycle-1"
    assert not transaction_active

    await operations.create(
        workspace_id="workspace-1",
        agent_id="agent-1",
        session_id="session-1",
        title="Daily report",
        objective="Prepare it.",
        at=scheduled_at.isoformat(),
        cron=None,
        timezone=None,
        binding_id=None,
        now=now,
    )
    assert not transaction_active
    tasks.create.assert_awaited_once()
    assert tasks.create.await_args is not None
    created_task = tasks.create.await_args.args[1]
    assert created_task.scheduled_at == scheduled_at
    assert created_task.next_eligible_at == scheduled_at

    assert (
        await operations.list_tasks(
            agent_id="agent-1",
            session_id="session-1",
        )
        == []
    )
    assert not transaction_active

    assert (
        await operations.delete(
            session_id="session-1",
            task_id="task-1",
        )
        is None
    )
    assert not transaction_active
    assert transaction_count == 5
