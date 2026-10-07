"""Real PostgreSQL idle-boundary and parent-mailbox lock compatibility."""

import asyncio
import datetime
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Literal, NamedTuple
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from azents.core.agent_session_data import AgentSessionCreate
from azents.core.enums import (
    AgentRunStatus,
    AgentRuntimeCapability,
    AgentSessionProductMode,
    AgentSessionRunState,
    MailboxItemKind,
    MailboxSchedulingMode,
)
from azents.core.mailbox_data import MailboxItem, MailboxItemCreate
from azents.rdb.session_capabilities import ReadWriteSession, WriteSession
from azents.repos.agent_execution import AgentRunRepository
from azents.repos.agent_execution.data import AgentRunCreate
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.agent_session.repository_test import _create_agent, _create_workspace
from azents.repos.idle_continuation import (
    IdleContinuationFinalization,
    IdleContinuationRepository,
)
from azents.repos.mailbox import MailboxRepository
from azents.repos.scheduled_task_cycle import ScheduledTaskCycleRepository
from azents.repos.session_execution_record import SessionExecutionRecordRepository
from azents.repos.toolkit_state import ToolkitStateRepository
from azents.worker.session.idle_continuation_lock_test import (
    _cleanup_workspace_fixture,
    _wait_for_database_blocker,
)


class _MailboxIdleOutcome(NamedTuple):
    """Committed outcomes after both owned operations have finished."""

    delivery: MailboxItem
    idle: IdleContinuationFinalization


def _database_abort_classes(
    error: OperationalError | BaseExceptionGroup[OperationalError],
) -> set[str]:
    """Extract safe driver class names without SQL or parameter values."""
    if isinstance(error, OperationalError):
        return {type(error.orig).__name__}
    return {
        name for nested in error.exceptions for name in _database_abort_classes(nested)
    }


async def _run_mailbox_idle_tasks(
    *,
    mailbox_ready: asyncio.Future[int],
    deliver: Callable[[], Awaitable[MailboxItem]],
    finalize: Callable[[int], Awaitable[IdleContinuationFinalization]],
) -> _MailboxIdleOutcome:
    """Cancel all peers and parent barrier waits on any operation failure."""

    async def delivery_operation() -> MailboxItem:
        return await deliver()

    async def idle_operation(pid: int) -> IdleContinuationFinalization:
        result = await finalize(pid)
        assert result.consumed, "Idle boundary was rejected before consumption"
        return result

    try:
        async with asyncio.TaskGroup() as tasks:
            delivery_task = tasks.create_task(delivery_operation())
            pid = await mailbox_ready
            idle_task = tasks.create_task(idle_operation(pid))
    except* OperationalError as errors:
        classes = sorted(_database_abort_classes(errors))
        pytest.fail(
            "Atomic mailbox/idle operation aborted: " + ", ".join(classes),
            pytrace=False,
        )
    return _MailboxIdleOutcome(delivery_task.result(), idle_task.result())


class _ObservedIdleConsumption(AgentSessionRepository):
    """Observe the real competing writer before consuming an idle boundary."""

    def __init__(
        self,
        *,
        engine: AsyncEngine,
        mailbox_pid: int,
        idle_pid: asyncio.Future[int],
        consumption_started: asyncio.Event,
    ) -> None:
        self.engine = engine
        self.mailbox_pid = mailbox_pid
        self.idle_pid = idle_pid
        self.consumption_started = consumption_started

    async def consume_pending_idle_continuation(
        self,
        session: WriteSession,
        *,
        session_id: str,
        run_id: str,
        continue_running: bool,
        allow_archived_scheduled_continuation: bool,
    ) -> bool:
        """Establish the actual owner-fence wait, then execute production SQL."""
        self.consumption_started.set()
        await _wait_for_database_blocker(
            self.engine,
            blocked_pid=self.mailbox_pid,
            blocker_pid=await self.idle_pid,
        )
        return await super().consume_pending_idle_continuation(
            session,
            session_id=session_id,
            run_id=run_id,
            continue_running=continue_running,
            allow_archived_scheduled_continuation=(
                allow_archived_scheduled_continuation
            ),
        )


@pytest.mark.asyncio
async def test_idle_consumption_preserves_child_root_fk_and_parent_mailbox(
    rdb_engine: AsyncEngine,
    latest_db_schema: None,
) -> None:
    """Both atomic operations must commit without a key-share upgrade deadlock."""
    del latest_db_schema
    sessions = AgentSessionRepository()
    runs = AgentRunRepository()
    mailboxes = MailboxRepository()
    suffix = uuid4().hex[:8]
    async with AsyncSession(rdb_engine, expire_on_commit=False) as raw_setup:
        constraint = (
            await raw_setup.execute(
                sa.text(
                    "SELECT condeferrable, condeferred, "
                    "conrelid = 'agent_sessions'::regclass, "
                    "confrelid = 'agent_sessions'::regclass "
                    "FROM pg_constraint WHERE conname = 'fk_session_lifecycle_root'"
                )
            )
        ).one()
        assert constraint == (False, False, True, True)
        setup = ReadWriteSession(raw_setup)
        workspace_id = await _create_workspace(setup, f"idle-mailbox-{suffix}")
        agent_id = await _create_agent(
            setup,
            workspace_id,
            f"idle-mailbox-{suffix}",
            runtime_capability=AgentRuntimeCapability.NONE,
        )
        root = await sessions.create(
            setup,
            AgentSessionCreate(
                workspace_id=workspace_id,
                product_mode=AgentSessionProductMode.TEAM,
                associated_user_id=None,
                agent_id=agent_id,
                title=None,
            ),
        )
        run = await runs.create(
            setup,
            AgentRunCreate(
                session_id=root.id,
                scheduled_task_cycle_id=None,
                parent_agent_run_id=None,
            ),
        )
        await runs.mark_terminal(
            setup,
            run.id,
            AgentRunStatus.COMPLETED,
            ended_at=datetime.datetime.now(datetime.UTC),
        )
        await sessions.mark_running(setup, root.id)
        await raw_setup.commit()

    mailbox_ready: asyncio.Future[int] = asyncio.get_running_loop().create_future()
    idle_pid: asyncio.Future[int] = asyncio.get_running_loop().create_future()
    consumption_started = asyncio.Event()
    child_session_id: asyncio.Future[str] = asyncio.get_running_loop().create_future()

    async def deliver_parent_result() -> MailboxItem:
        async with AsyncSession(rdb_engine, expire_on_commit=False) as raw:
            try:
                pid = await raw.scalar(sa.text("SELECT pg_backend_pid()"))
                assert isinstance(pid, int)
                session = ReadWriteSession(raw)
                # Exercise the real paired child-row insertion below outer
                # admission locks. Its immediate lifecycle-root FK, unlike the
                # deferred mailbox FK, retains KEY SHARE on this exact parent.
                child = await sessions._create_linked_subagent_session(
                    session,
                    workspace_id=workspace_id,
                    agent_id=agent_id,
                    title=None,
                    lifecycle_root_session_id=root.id,
                )
                child_session_id.set_result(child.id)
                child_run = await runs.create(
                    session,
                    AgentRunCreate(
                        session_id=child.id,
                        scheduled_task_cycle_id=None,
                        parent_agent_run_id=run.id,
                    ),
                )
                await runs.mark_terminal(
                    session,
                    child_run.id,
                    AgentRunStatus.COMPLETED,
                    ended_at=datetime.datetime.now(datetime.UTC),
                )
                item = await mailboxes.create(
                    session,
                    MailboxItemCreate(
                        session_id=root.id,
                        kind=MailboxItemKind.AGENT_MESSAGE,
                        scheduling_mode=MailboxSchedulingMode.QUEUE_ONLY,
                        requested_model_target_label=None,
                        requested_reasoning_effort=None,
                        requested_enabled_execution_options=[],
                        sender_user_id=None,
                        order_group=None,
                        order_sequence=0,
                        content="Completed child result",
                        idempotency_key=f"idle-mailbox-result-{suffix}",
                        metadata={
                            "message_kind": "agent_result",
                            "source_run_id": child_run.id,
                            "source_run_index": str(child_run.run_index),
                            "run_status": AgentRunStatus.COMPLETED.value,
                        },
                        attachments=[],
                        file_parts=[],
                    ),
                )
                mailbox_ready.set_result(pid)
                await consumption_started.wait()
                target = await sessions.fence_active_mailbox_target(session, root.id)
                assert target is not None
                await raw.commit()
                return item
            except asyncio.CancelledError:
                await raw.rollback()
                raise
            except Exception:
                await raw.rollback()
                raise

    @asynccontextmanager
    async def manager() -> AsyncIterator[WriteSession]:
        async with AsyncSession(rdb_engine, expire_on_commit=False) as raw:
            pid = await raw.scalar(sa.text("SELECT pg_backend_pid()"))
            assert isinstance(pid, int)
            idle_pid.set_result(pid)
            try:
                yield ReadWriteSession(raw)
                await raw.commit()
            except asyncio.CancelledError:
                await raw.rollback()
                raise
            except Exception:
                await raw.rollback()
                raise

    async def finalize_idle(pid: int) -> IdleContinuationFinalization:
        repository = IdleContinuationRepository(
            manager,
            _ObservedIdleConsumption(
                engine=rdb_engine,
                mailbox_pid=pid,
                idle_pid=idle_pid,
                consumption_started=consumption_started,
            ),
            runs,
            mailboxes,
            ScheduledTaskCycleRepository(ToolkitStateRepository()),
        )
        return await repository.finalize(
            session_id=root.id,
            run_id=run.id,
            owner_generation=root.owner_generation,
            inputs=[],
        )

    try:
        outcome = await _run_mailbox_idle_tasks(
            mailbox_ready=mailbox_ready,
            deliver=deliver_parent_result,
            finalize=finalize_idle,
        )
        assert outcome.idle.continuation_count == 0
        assert outcome.idle.admissions == []
        async with AsyncSession(rdb_engine) as raw_verify:
            verify = ReadWriteSession(raw_verify)
            current = await sessions.get_by_id(verify, root.id)
            assert current is not None
            assert current.owner_generation == root.owner_generation
            assert current.run_state is AgentSessionRunState.IDLE
            assert current.pending_idle_continuation_run_id is None
            terminal_run = await runs.get_by_id(verify, run.id)
            assert terminal_run is not None
            assert terminal_run.status is AgentRunStatus.COMPLETED
            items = await mailboxes.list_by_session_id(verify, root.id)
            assert len(items) == 1
            assert items[0].id == outcome.delivery.id
            assert items[0].kind is MailboxItemKind.AGENT_MESSAGE
            assert items[0].scheduling_mode is MailboxSchedulingMode.QUEUE_ONLY
            assert items[0].content == "Completed child result"
            child_record = await SessionExecutionRecordRepository().get_by_id(
                verify, await child_session_id
            )
            assert child_record is not None
            assert child_record.lifecycle_root_session_id == root.id
            child_terminal_run = await runs.get_by_id(
                verify, items[0].metadata["source_run_id"]
            )
            assert child_terminal_run is not None
            assert child_terminal_run.session_id == child_record.id
            assert child_terminal_run.status is AgentRunStatus.COMPLETED
    finally:
        await _cleanup_workspace_fixture(rdb_engine, workspace_id)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure",
    ["delivery-before-ready", "idle-before-consumption", "idle-rejected"],
)
async def test_operation_failure_cancels_parent_wait_and_cleans_delivery_peer(
    failure: Literal[
        "delivery-before-ready", "idle-before-consumption", "idle-rejected"
    ],
) -> None:
    """Use the real harness to reject early faults without leaving barrier waits."""
    mailbox_ready: asyncio.Future[int] = asyncio.get_running_loop().create_future()
    delivery_waiting = asyncio.Event()
    delivery_cleaned = asyncio.Event()
    delivery_cancelled = asyncio.Event()
    consumption_started = asyncio.Event()
    finalization_started = asyncio.Event()

    async def deliver() -> MailboxItem:
        try:
            if failure == "delivery-before-ready":
                raise RuntimeError("Delivery failed before readiness")
            mailbox_ready.set_result(1)
            delivery_waiting.set()
            await consumption_started.wait()
            raise AssertionError("Delivery unexpectedly crossed its barrier")
        except asyncio.CancelledError:
            delivery_cancelled.set()
            raise
        finally:
            delivery_cleaned.set()

    async def finalize(pid: int) -> IdleContinuationFinalization:
        assert pid == 1
        finalization_started.set()
        await delivery_waiting.wait()
        if failure == "idle-rejected":
            return IdleContinuationFinalization(
                consumed=False,
                admissions=[],
                continuation_count=0,
            )
        raise RuntimeError("Idle finalization failed before consumption")

    with pytest.raises(ExceptionGroup) as raised:
        await _run_mailbox_idle_tasks(
            mailbox_ready=mailbox_ready,
            deliver=deliver,
            finalize=finalize,
        )
    assert len(raised.value.exceptions) == 1
    expected_error = AssertionError if failure == "idle-rejected" else RuntimeError
    assert isinstance(raised.value.exceptions[0], expected_error)
    assert delivery_cleaned.is_set()
    assert not consumption_started.is_set()
    if failure == "delivery-before-ready":
        assert mailbox_ready.cancelled()
        assert not finalization_started.is_set()
        assert not delivery_cancelled.is_set()
    else:
        assert finalization_started.is_set()
        assert delivery_cancelled.is_set()
