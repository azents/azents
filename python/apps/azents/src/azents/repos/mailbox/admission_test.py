"""Mailbox admission transaction, wake, idempotency and cancellation tests."""

import asyncio
import dataclasses
import datetime
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.agent_session_data import AgentSessionCreate
from azents.core.enums import (
    AgentSessionProductMode,
    AgentSessionRunState,
    MailboxItemKind,
    MailboxSchedulingMode,
)
from azents.core.llm_catalog import ModelReasoningEffort
from azents.core.mailbox_data import MailboxItem
from azents.core.model_execution_options import ModelExecutionOptionId
from azents.rdb.session import SessionManager
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.agent_session.repository_test import _create_agent, _create_workspace
from azents.repos.mailbox import MailboxRepository
from azents.repos.mailbox.admission import MailboxAdmissionRepository
from azents.repos.mailbox.admission_data import MailboxEnqueue


class _ObservedManager:
    """Observe resolution of real database sessions before operation return."""

    def __init__(self, manager: SessionManager[AsyncSession]) -> None:
        self.manager = manager
        self.active = False
        self.sessions: list[AsyncSession] = []
        self.resolved: list[bool] = []

    @asynccontextmanager
    async def __call__(self) -> AsyncIterator[AsyncSession]:
        """Yield a real session and observe its completed transaction lifetime."""
        assert not self.active
        self.active = True
        session: AsyncSession | None = None
        try:
            async with self.manager() as current:
                session = current
                self.sessions.append(current)
                yield current
        finally:
            self.active = False
            if session is not None:
                self.resolved.append(not session.in_transaction())


class _WakeRepository(AgentSessionRepository):
    """Record actual wake mutations and optionally fail the second mutation."""

    def __init__(self, failure: ValueError | None) -> None:
        self.failure = failure
        self.wakes: list[str] = []
        self.sessions: list[AsyncSession] = []

    async def mark_running_for_input_wakeup(
        self, session: AsyncSession, session_id: str
    ) -> None:
        """Apply the real wake transition before injecting a late failure."""
        await super().mark_running_for_input_wakeup(session, session_id)
        self.sessions.append(session)
        self.wakes.append(session_id)
        if len(self.wakes) == 2 and self.failure is not None:
            raise self.failure


class _CancellationWakeRepository(_WakeRepository):
    """Expose a deterministic cancellation boundary after real wake writes."""

    def __init__(self) -> None:
        super().__init__(None)
        self.second_wake_written = asyncio.Event()
        self.release = asyncio.Event()

    async def mark_running_for_input_wakeup(
        self, session: AsyncSession, session_id: str
    ) -> None:
        """Pause after the second mutation until cancellation is requested."""
        await super().mark_running_for_input_wakeup(session, session_id)
        if len(self.wakes) == 2:
            self.second_wake_written.set()
            await self.release.wait()


async def _sessions(manager: SessionManager[AsyncSession], name: str) -> list[str]:
    """Create two root Sessions with real Mailbox foreign-key authority."""
    async with manager() as session:
        workspace_id = await _create_workspace(session, name)
        agent_id = await _create_agent(session, workspace_id, name)
        repository = AgentSessionRepository()
        return [
            (
                await repository.create(
                    session,
                    AgentSessionCreate(
                        workspace_id=workspace_id,
                        agent_id=agent_id,
                        product_mode=AgentSessionProductMode.TEAM,
                        associated_user_id=None,
                        title=None,
                    ),
                )
            ).id
            for _ in range(2)
        ]


def _input(
    session_id: str, key: str | None, mode: MailboxSchedulingMode
) -> MailboxEnqueue:
    """Build one typed admission without introducing request defaults."""
    return MailboxEnqueue(
        session_id=session_id,
        kind=MailboxItemKind.USER_MESSAGE,
        scheduling_mode=mode,
        requested_model_target_label=None,
        requested_reasoning_effort=None,
        requested_enabled_execution_options=[],
        sender_user_id=None,
        order_group=None,
        order_sequence=0,
        content="admission input",
        idempotency_key=key,
        metadata={"source": "test"},
        attachments=[],
        file_parts=[],
        action=None,
        payload=None,
    )


async def _assert_rolled_back(
    manager: SessionManager[AsyncSession], session_ids: list[str]
) -> None:
    """Verify all real row writes and wake changes were abandoned."""
    async with manager() as session:
        for session_id in session_ids:
            assert (
                await MailboxRepository().list_by_session_id(session, session_id) == []
            )
            state = await AgentSessionRepository().get_by_id(session, session_id)
            assert state is not None
            assert state.run_state is AgentSessionRunState.IDLE


async def test_completed_batch_closes_and_wakes_distinct_sessions_in_order(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """Input order and sorted wakes share one completed database transaction."""
    ids = await _sessions(rdb_session_manager, "admission-completed-batch")
    manager = _ObservedManager(rdb_session_manager)
    wakes = _WakeRepository(None)
    repository = MailboxAdmissionRepository(manager, MailboxRepository(), wakes)
    inputs = [
        _input(ids[1], "last-first", MailboxSchedulingMode.WAKE_SESSION),
        _input(ids[0], "first-second", MailboxSchedulingMode.WAKE_SESSION),
        _input(ids[1], "last-third", MailboxSchedulingMode.WAKE_SESSION),
    ]

    results = await repository.enqueue_many(inputs)

    assert not manager.active
    assert manager.resolved == [True]
    assert len(manager.sessions) == 1
    assert wakes.sessions == [manager.sessions[0], manager.sessions[0]]
    assert wakes.wakes == sorted(ids)
    assert [result.mailbox_item.idempotency_key for result in results] == [
        input.idempotency_key for input in inputs
    ]
    assert all(result.created for result in results)
    async with rdb_session_manager() as session:
        assert len(await MailboxRepository().list_by_session_id(session, ids[0])) == 1
        assert len(await MailboxRepository().list_by_session_id(session, ids[1])) == 2


async def test_queue_only_batch_does_not_wake(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """Queue-only admission completes without changing idle state."""
    ids = await _sessions(rdb_session_manager, "admission-queue-only")
    wakes = _WakeRepository(None)
    repository = MailboxAdmissionRepository(
        rdb_session_manager, MailboxRepository(), wakes
    )
    results = await repository.enqueue_many(
        [_input(ids[0], None, MailboxSchedulingMode.QUEUE_ONLY)]
    )
    assert len(results) == 1
    assert wakes.wakes == []
    async with rdb_session_manager() as session:
        state = await AgentSessionRepository().get_by_id(session, ids[0])
        assert state is not None
        assert state.run_state is AgentSessionRunState.IDLE


async def test_idle_continuation_admission_preserves_composer_session_state(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """Idle-hook row scheduling intent does not independently wake the Session."""
    ids = await _sessions(rdb_session_manager, "admission-idle-no-wake")
    wakes = _WakeRepository(None)
    repository = MailboxAdmissionRepository(
        rdb_session_manager, MailboxRepository(), wakes
    )
    async with rdb_session_manager() as session:
        results = await repository.enqueue_idle_continuations_in_session(
            session, [_input(ids[0], "idle-key", MailboxSchedulingMode.WAKE_SESSION)]
        )
        state = await AgentSessionRepository().get_by_id(session, ids[0])
        assert state is not None
        assert state.run_state is AgentSessionRunState.IDLE
    assert results[0].mailbox_item.scheduling_mode is MailboxSchedulingMode.WAKE_SESSION
    assert wakes.wakes == []


async def test_idempotent_replay_reapplies_wake_without_a_second_row(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """Replayed input restores the wake transition and preserves row identity."""
    ids = await _sessions(rdb_session_manager, "admission-replay-wake")
    repository = MailboxAdmissionRepository(
        rdb_session_manager, MailboxRepository(), AgentSessionRepository()
    )
    input = _input(ids[0], "replayed-key", MailboxSchedulingMode.WAKE_SESSION)
    first = (await repository.enqueue_many([input]))[0]
    async with rdb_session_manager() as session:
        await AgentSessionRepository().mark_idle(session, ids[0])
    replay = (await repository.enqueue_many([input]))[0]
    assert first.created
    assert not replay.created
    assert first.mailbox_item.id == replay.mailbox_item.id
    async with rdb_session_manager() as session:
        state = await AgentSessionRepository().get_by_id(session, ids[0])
        assert state is not None
        assert state.run_state is AgentSessionRunState.RUNNING
        assert len(await MailboxRepository().list_by_session_id(session, ids[0])) == 1


async def test_late_wake_failure_rolls_back_all_rows_and_session_changes(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """A failure after both wake writes cannot leave partially committed admission."""
    ids = await _sessions(rdb_session_manager, "admission-late-wake-rollback")
    manager = _ObservedManager(rdb_session_manager)
    wakes = _WakeRepository(ValueError("final wake failed"))
    repository = MailboxAdmissionRepository(manager, MailboxRepository(), wakes)
    with pytest.raises(ValueError, match="final wake failed"):
        await repository.enqueue_many(
            [
                _input(id, "rollback-key", MailboxSchedulingMode.WAKE_SESSION)
                for id in ids
            ]
        )
    assert wakes.wakes == sorted(ids)
    assert not manager.active
    assert manager.resolved == [True]
    await _assert_rolled_back(rdb_session_manager, ids)


async def test_cancellation_after_wake_writes_rolls_back_the_completed_operation(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """Cancellation propagates after abandoning real Mailbox and Session writes."""
    ids = await _sessions(rdb_session_manager, "admission-cancel-rollback")
    manager = _ObservedManager(rdb_session_manager)
    wakes = _CancellationWakeRepository()
    repository = MailboxAdmissionRepository(manager, MailboxRepository(), wakes)
    task = asyncio.create_task(
        repository.enqueue_many(
            [_input(id, "cancel-key", MailboxSchedulingMode.WAKE_SESSION) for id in ids]
        )
    )
    try:
        await asyncio.wait_for(wakes.second_wake_written.wait(), timeout=5)
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert not manager.active
    assert manager.resolved == [True]
    await _assert_rolled_back(rdb_session_manager, ids)


async def test_profile_failure_on_later_row_rolls_back_earlier_row(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """Late dedupe validation cannot commit an earlier new row or any wake."""
    ids = await _sessions(rdb_session_manager, "admission-late-profile-rollback")
    repository = MailboxAdmissionRepository(
        rdb_session_manager, MailboxRepository(), AgentSessionRepository()
    )
    existing = _input(ids[1], "existing-key", MailboxSchedulingMode.QUEUE_ONLY)
    await repository.enqueue_many([existing])
    with pytest.raises(ValueError, match="another inference profile"):
        await repository.enqueue_many(
            [
                _input(ids[0], "rolled-back-key", MailboxSchedulingMode.WAKE_SESSION),
                dataclasses.replace(existing, requested_model_target_label="Quality"),
            ]
        )
    async with rdb_session_manager() as session:
        assert await MailboxRepository().list_by_session_id(session, ids[0]) == []
        assert len(await MailboxRepository().list_by_session_id(session, ids[1])) == 1
        for id in ids:
            state = await AgentSessionRepository().get_by_id(session, id)
            assert state is not None
            assert state.run_state is AgentSessionRunState.IDLE


@pytest.mark.parametrize(
    ("winner_updates", "message"),
    [
        (
            {"scheduling_mode": MailboxSchedulingMode.QUEUE_ONLY},
            "another scheduling mode",
        ),
        ({"requested_model_target_label": "Fast"}, "another inference profile"),
        (
            {"requested_reasoning_effort": ModelReasoningEffort.HIGH},
            "another inference profile",
        ),
        (
            {"requested_enabled_execution_options": [ModelExecutionOptionId.FAST]},
            "another inference profile",
        ),
        ({}, None),
    ],
)
async def test_upsert_result_validation_and_pre_read_created_semantics(
    winner_updates: dict[str, object], message: str | None
) -> None:
    """Validate the race winner before wake and retain pre-read creation semantics."""
    input = _input("session-1", "race-key", MailboxSchedulingMode.WAKE_SESSION)
    winner = MailboxItem(
        id="winner-row",
        session_id=input.session_id,
        kind=input.kind,
        scheduling_mode=input.scheduling_mode,
        requested_model_target_label=None,
        requested_reasoning_effort=None,
        requested_enabled_execution_options=[],
        sender_user_id=None,
        order_group="winner-row",
        order_sequence=0,
        content=input.content,
        idempotency_key=input.idempotency_key,
        metadata=input.metadata,
        attachments=[],
        file_parts=[],
        created_at=datetime.datetime.now(datetime.UTC),
    ).model_copy(update=winner_updates)
    mailbox = AsyncMock(spec=MailboxRepository)
    mailbox.get_by_idempotency_key.return_value = None
    mailbox.create_idempotent.return_value = winner
    sessions = AsyncMock(spec=AgentSessionRepository)
    manager = AsyncMock()
    repository = MailboxAdmissionRepository(manager, mailbox, sessions)
    session = AsyncMock(spec=AsyncSession)
    if message is not None:
        with pytest.raises(ValueError, match=message):
            await repository.enqueue_in_session(session, input)
        sessions.mark_running_for_input_wakeup.assert_not_awaited()
    else:
        result = await repository.enqueue_in_session(session, input)
        assert result.created is True
        assert result.mailbox_item is winner
        sessions.mark_running_for_input_wakeup.assert_awaited_once_with(
            session, input.session_id
        )
    mailbox.create_idempotent.assert_awaited_once()
    manager.assert_not_called()
