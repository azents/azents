"""Deterministic shared supervision ordering for public and private execution."""

import asyncio
import dataclasses

import pytest

from azents.engine.run.task_supervision import ExecutionTaskSupervision


@dataclasses.dataclass
class _Host:
    shutdown: asyncio.Event = dataclasses.field(default_factory=asyncio.Event)
    stop: asyncio.Event = dataclasses.field(default_factory=asyncio.Event)
    waiter_started: asyncio.Event = dataclasses.field(default_factory=asyncio.Event)
    finalization_entered: asyncio.Event = dataclasses.field(
        default_factory=asyncio.Event
    )
    release_finalization: asyncio.Event = dataclasses.field(
        default_factory=asyncio.Event
    )
    release_run: asyncio.Event = dataclasses.field(default_factory=asyncio.Event)
    run_started: asyncio.Event = dataclasses.field(default_factory=asyncio.Event)
    trace: list[str] = dataclasses.field(default_factory=list)
    stopped: bool = False

    async def execute(self) -> str:
        self.run_started.set()
        try:
            await self.release_run.wait()
            return "accepted"
        except asyncio.CancelledError as error:
            self.trace.append(f"cancel:{error.args[0]}")
            raise

    async def wait_for_stop(self) -> None:
        self.waiter_started.set()
        await self.stop.wait()
        self.stopped = True

    async def finalize_stop(self) -> None:
        self.trace.append("finalize")
        self.finalization_entered.set()
        await self.release_finalization.wait()

    def handover(self) -> None:
        self.trace.append("handover")

    async def close_admission(self) -> None:
        self.trace.append("close")

    def supervisor(self, *, timeout: float) -> ExecutionTaskSupervision[str]:
        return ExecutionTaskSupervision(
            session_id="private-or-public",
            shutdown_event=self.shutdown,
            wait_for_explicit_stop=self.wait_for_stop,
            finalize_explicit_stop=self.finalize_stop,
            user_stop_requested=lambda: self.stopped,
            request_handover_stop=self.handover,
            close_tool_admission=self.close_admission,
            cancelled_result=lambda terminal: "stopped" if terminal else "handover",
            shutdown_timeout=timeout,
            user_stop_cancel_message="user-stop",
            shutdown_cancel_message="shutdown",
        )


async def test_normal_result_is_not_finalized_as_stop() -> None:
    host = _Host()
    task = asyncio.create_task(host.execute())
    await host.run_started.wait()
    supervised = asyncio.create_task(host.supervisor(timeout=30).run(task))
    await host.waiter_started.wait()
    host.release_run.set()
    assert await supervised == "accepted"
    assert host.trace == []


async def test_stop_settlement_precedes_engine_cancel_and_waits_for_completion() -> (
    None
):
    host = _Host()
    task = asyncio.create_task(host.execute())
    await host.run_started.wait()
    supervised = asyncio.create_task(host.supervisor(timeout=30).run(task))
    await host.waiter_started.wait()
    host.stop.set()
    await host.finalization_entered.wait()
    assert not task.done()
    host.release_finalization.set()
    assert await supervised == "stopped"
    assert task.cancelled()
    assert host.trace == ["finalize", "cancel:user-stop"]


async def test_observed_user_cancel_runs_domain_finalization_once() -> None:
    host = _Host()
    task = asyncio.create_task(host.execute())
    await host.run_started.wait()
    supervised = asyncio.create_task(host.supervisor(timeout=30).run(task))
    await host.waiter_started.wait()
    host.stopped = True
    host.release_finalization.set()
    task.cancel("user-stop")
    assert await supervised == "stopped"
    assert host.trace == ["cancel:user-stop", "finalize"]


async def test_shutdown_closes_admission_then_preserves_accepted_result() -> None:
    host = _Host()
    task = asyncio.create_task(host.execute())
    await host.run_started.wait()
    host.shutdown.set()
    host.release_run.set()
    assert await host.supervisor(timeout=30).run(task) == "accepted"
    assert host.trace == ["handover", "close"]


async def test_elapsed_shutdown_timeout_cancels_without_terminal_failure() -> None:
    host = _Host()
    task = asyncio.create_task(host.execute())
    await host.run_started.wait()
    host.shutdown.set()
    assert await host.supervisor(timeout=0).run(task) == "handover"
    assert task.cancelled()
    assert host.trace == ["handover", "close", "cancel:shutdown"]


async def test_execution_error_propagates_without_invented_stop() -> None:
    host = _Host()

    async def fail() -> str:
        await host.release_run.wait()
        raise ValueError("observed engine failure")

    task = asyncio.create_task(fail())
    supervised = asyncio.create_task(host.supervisor(timeout=30).run(task))
    await host.waiter_started.wait()
    host.release_run.set()
    with pytest.raises(ValueError, match="observed engine failure"):
        await supervised
    assert host.trace == []
