"""Real rollback-confirmed PostgreSQL replay of completed Memory DB owners."""

import asyncio
import dataclasses
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Literal, assert_never

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncEngine

from azents.core.historical_memory_consolidation import MemoryAcceptedOutcome
from azents.core.historical_memory_publication import MemorySubmissionError
from azents.core.session_execution_file import ExecutionFileChange
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.agent_session import RDBAgentSession
from azents.rdb.models.base import RDBModel
from azents.rdb.models.session_execution_file import RDBSessionExecutionFile
from azents.rdb.session_capabilities import (
    WriteSession,
    create_read_write_session_manager,
)
from azents.repos.hierarchy_contention import is_confirmed_transaction_abort
from azents.repos.historical_memory.locking_order_test import _pid, _wait_for_blocker
from azents.repos.historical_memory_consolidation.execution_test import _start
from azents.repos.session_execution_file import SessionExecutionFileRepository
from azents.repos.session_execution_record import SessionExecutionRecordRepository
from azents.testing.committed_fixture_cleanup import committed_fixture_graph


@pytest.mark.parametrize("operation", ["submit", "start_turn", "write", "patch"])
async def test_real_deadlock_replays_only_completed_db_operation(
    rdb_engine: AsyncEngine,
    latest_db_schema: None,
    operation: Literal["submit", "start_turn", "write", "patch"],
) -> None:
    """The deadlock victim repeats SQL under fresh authority, not its outer handler."""
    del latest_db_schema
    manager = create_read_write_session_manager(rdb_engine)
    async with committed_fixture_graph(rdb_engine, RDBModel.metadata):
        case = await _start(manager)
        principal = case.principal
        files = SessionExecutionFileRepository(manager)
        await files.write(principal.owner, "result.md", "Before", None, True)
        first_pid: asyncio.Future[int] = asyncio.get_running_loop().create_future()
        aborted: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        attempts = 0
        handler_calls = 0

        @asynccontextmanager
        async def observed_manager() -> AsyncIterator[WriteSession]:
            nonlocal attempts
            attempts += 1
            try:
                async with manager() as session:
                    await session.write_session.execute(
                        sa.text("SET LOCAL deadlock_timeout = '100ms'")
                    )
                    if not first_pid.done():
                        first_pid.set_result(await _pid(session))
                    yield session
            except OperationalError as error:
                if is_confirmed_transaction_abort(error) and not aborted.done():
                    aborted.set_result(None)
                raise

        repository = dataclasses.replace(
            case.repository, session_manager=observed_manager
        )
        observed_files = SessionExecutionFileRepository(observed_manager)

        async def handler() -> object:
            nonlocal handler_calls
            handler_calls += 1
            match operation:
                case "submit":
                    return await repository.submit(
                        principal,
                        tool_call_id="same-original-call",
                        authored_path="result.md",
                    )
                case "start_turn":
                    return await repository.start_turn(principal)
                case "write":
                    return await observed_files.write(
                        principal.owner, "result.md", "After", "Before", True
                    )
                case "patch":
                    return await observed_files.atomic_patch(
                        principal.owner,
                        (
                            ExecutionFileChange("result.md", "Before", "After"),
                            ExecutionFileChange("other.md", None, "Added"),
                        ),
                    )
                case _:
                    assert_never(operation)

        task: asyncio.Task[object] | None = None
        try:
            async with manager() as holder:
                await holder.write_session.execute(
                    sa.text("SET LOCAL deadlock_timeout = '5s'")
                )
                if operation in ("submit", "start_turn"):
                    assert (
                        await SessionExecutionRecordRepository().fence_owner(
                            holder, principal.owner
                        )
                        is not None
                    )
                else:
                    assert (
                        await holder.write_session.get(
                            RDBSessionExecutionFile,
                            (principal.owner.session_id, "result.md"),
                            with_for_update=True,
                        )
                        is not None
                    )
                holder_pid = await _pid(holder)
                task = asyncio.create_task(handler())
                waiter = await asyncio.wait_for(first_pid, timeout=5)
                await asyncio.wait_for(
                    _wait_for_blocker(rdb_engine, waiter=waiter, holder=holder_pid),
                    timeout=5,
                )
                if operation in ("submit", "start_turn"):
                    opposite = (
                        sa.select(RDBAgent.id)
                        .where(RDBAgent.id == principal.binding.unit.agent_id)
                        .with_for_update()
                    )
                else:
                    opposite = (
                        sa.select(RDBAgentSession.id)
                        .where(RDBAgentSession.id == principal.owner.session_id)
                        .with_for_update(of=RDBAgentSession)
                    )
                await asyncio.wait_for(holder.write_session.scalar(opposite), timeout=5)
                await asyncio.wait_for(aborted, timeout=5)
            result = await asyncio.wait_for(task, timeout=5)
            assert attempts >= 2 and handler_calls == 1
            binding = await case.repository.load_binding(principal.owner.session_id)
            assert binding is not None
            assert binding.deadline_at == principal.binding.deadline_at
            assert binding.execution_policy == principal.binding.execution_policy
            match operation:
                case "submit":
                    assert isinstance(result, MemoryAcceptedOutcome)
                    assert result.tool_call_id == "same-original-call"
                    assert result.settled_work_count == 1
                    assert binding.accepted == result
                case "start_turn":
                    assert binding.started_turns == 1
                case "write" | "patch":
                    current = await files.read(principal.owner, "result.md")
                    assert current is not None and current.content == "After"
                    if operation == "patch":
                        other = await files.read(principal.owner, "other.md")
                        assert other is not None and other.content == "Added"
                case _:
                    assert_never(operation)
        finally:
            if task is not None and not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)


async def test_submit_replay_retains_obtained_markdown_after_confirmed_rollback(
    rdb_engine: AsyncEngine,
    latest_db_schema: None,
) -> None:
    """A retry retains captured bytes and reports a changed file."""
    del latest_db_schema
    manager = create_read_write_session_manager(rdb_engine)
    async with committed_fixture_graph(rdb_engine, RDBModel.metadata):
        case = await _start(manager)
        principal = case.principal
        files = SessionExecutionFileRepository(manager)
        await files.write(principal.owner, "result.md", "Original bytes", None, True)
        attempts = 0

        @asynccontextmanager
        async def aborted_after_capture() -> AsyncIterator[WriteSession]:
            nonlocal attempts
            attempts += 1
            try:
                async with manager() as session:
                    yield session
                    if attempts == 1:
                        await session.write_session.flush()
                        await session.write_session.execute(
                            sa.text("""
                            DO $$ BEGIN
                                RAISE EXCEPTION 'Confirmed serialization abort'
                                USING ERRCODE = '40001';
                            END; $$;
                        """)
                        )
            except OperationalError as error:
                assert is_confirmed_transaction_abort(error)
                await files.write(
                    principal.owner,
                    "result.md",
                    "Changed bytes",
                    "Original bytes",
                    True,
                )
                raise

        observed = dataclasses.replace(
            case.repository, session_manager=aborted_after_capture
        )
        with pytest.raises(MemorySubmissionError, match="changed during retry"):
            await observed.submit(
                principal, tool_call_id="captured-call", authored_path="result.md"
            )
        assert attempts == 2
        assert await case.repository.current_result(case.corpus.team) is None
        assert (
            await case.repository.inspect_accepted(
                principal.owner.session_id, tool_call_id="captured-call"
            )
            is None
        )
        current = await files.read(principal.owner, "result.md")
        assert current is not None and current.content == "Changed bytes"
