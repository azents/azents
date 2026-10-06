"""Idle continuation repository atomicity tests."""

import datetime
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

from pytest import MonkeyPatch
from sqlalchemy.ext.asyncio import AsyncSession

import azents.repos.idle_continuation as idle_continuation_module
from azents.core.agent_session_data import AgentSession
from azents.core.enums import (
    AgentSessionStatus,
    MailboxItemKind,
    MailboxSchedulingMode,
)
from azents.core.mailbox_data import MailboxItem
from azents.rdb.session_capabilities import ReadWriteSession, WriteSession
from azents.repos.agent_execution import AgentRunRepository
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.idle_continuation import (
    IdleContinuationInput,
    IdleContinuationRepository,
)
from azents.repos.mailbox import MailboxRepository
from azents.repos.scheduled_task_cycle import ScheduledTaskCycleRepository


async def test_failed_boundary_consume_rolls_back_new_admissions(
    monkeypatch: MonkeyPatch,
) -> None:
    """Commit-on-exit cannot persist admissions after conditional consume fails."""
    _raw_session = AsyncMock(spec=AsyncSession)
    session = ReadWriteSession(_raw_session)
    staged: list[MailboxItem] = []
    persisted: list[MailboxItem] = []

    @asynccontextmanager
    async def session_manager() -> AsyncIterator[WriteSession]:
        try:
            yield session
        except BaseException:
            staged.clear()
            raise
        else:
            persisted.extend(staged)
            staged.clear()

    agent_session_repository = AsyncMock(spec=AgentSessionRepository)
    agent_session_repository.get_by_id.return_value = AgentSession.model_construct(
        id="session-1",
        pending_idle_continuation_run_id="run-1",
        pending_command_id=None,
    )
    monkeypatch.setattr(
        idle_continuation_module,
        "fence_owned_session_mutation",
        AsyncMock(
            return_value=SimpleNamespace(
                owner_generation=1,
                status=AgentSessionStatus.ACTIVE,
                pending_idle_continuation_run_id="run-1",
                pending_command_id=None,
                agent_id="agent-1",
            )
        ),
    )
    agent_session_repository.consume_pending_idle_continuation.return_value = False
    agent_run_repository = AsyncMock(spec=AgentRunRepository)
    agent_run_repository.get_active_by_session_id.return_value = None
    mailbox_repository = AsyncMock(spec=MailboxRepository)
    mailbox_repository.has_by_session_id_and_scheduling_mode.return_value = False
    mailbox_repository.get_by_idempotency_key.return_value = None
    mailbox_item = MailboxItem(
        id="1" * 32,
        session_id="session-1",
        kind=MailboxItemKind.GOAL_CONTINUATION,
        scheduling_mode=MailboxSchedulingMode.WAKE_SESSION,
        requested_model_target_label=None,
        requested_reasoning_effort=None,
        requested_enabled_execution_options=[],
        sender_user_id=None,
        order_group="1" * 32,
        order_sequence=0,
        content="continue",
        idempotency_key="idle:1",
        metadata={},
        attachments=[],
        file_parts=[],
        payload=None,
        created_at=datetime.datetime.now(datetime.UTC),
    )

    async def create_idempotent(*args: object, **kwargs: object) -> MailboxItem:
        del args, kwargs
        staged.append(mailbox_item)
        return mailbox_item

    mailbox_repository.create_idempotent.side_effect = create_idempotent
    repository = IdleContinuationRepository(
        session_manager=session_manager,
        agent_session_repository=agent_session_repository,
        agent_run_repository=agent_run_repository,
        mailbox_repository=mailbox_repository,
        scheduled_task_cycle_repository=AsyncMock(spec=ScheduledTaskCycleRepository),
    )

    result = await repository.finalize(
        session_id="session-1",
        run_id="run-1",
        owner_generation=1,
        inputs=[
            IdleContinuationInput(
                session_id="session-1",
                kind=MailboxItemKind.GOAL_CONTINUATION,
                content="continue",
                idempotency_key="idle:1",
                metadata={},
                payload=None,
                scheduled_cycle_id=None,
            )
        ],
    )

    assert not result.consumed
    assert result.admissions == []
    assert staged == []
    assert persisted == []
    mailbox_repository.create_idempotent.assert_awaited_once()
