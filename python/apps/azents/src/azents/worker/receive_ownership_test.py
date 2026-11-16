"""Worker transient receive/shutdown task ownership regressions."""

import asyncio
from typing import Literal
from unittest.mock import MagicMock

import pytest

from azents.broker.types import SessionBroker, WorkerSignal
from azents.worker.worker import AgentWorker, _ShutdownRequested


class _Shutdown(asyncio.Event):
    def __init__(self) -> None:
        super().__init__()
        self.started = asyncio.Event()
        self.finished = asyncio.Event()

    async def wait(self) -> Literal[True]:
        self.started.set()
        try:
            return await super().wait()
        finally:
            self.finished.set()


@pytest.mark.parametrize("outcome", ["cancel", "receive", "shutdown", "failure"])
async def test_receive_boundary_drains_both_owned_tasks(outcome: str) -> None:
    started, finished, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
    shutdown = _Shutdown()

    async def receive() -> list[WorkerSignal]:
        started.set()
        try:
            await release.wait()
            if outcome == "failure":
                raise ValueError("synthetic receive failure")
            return []
        finally:
            finished.set()

    broker = MagicMock(spec=SessionBroker)
    broker.receive_messages = receive
    worker = AgentWorker(
        broker=broker,
        stuck_session_recovery=MagicMock(),
        session_runner_factory=MagicMock(),
        model_stream_watchdog=MagicMock(),
    )
    owner = asyncio.create_task(worker._receive_or_shutdown(shutdown))
    try:
        async with asyncio.timeout(5):
            await started.wait()
            await shutdown.started.wait()
            if outcome == "cancel":
                owner.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await owner
            elif outcome == "shutdown":
                shutdown.set()
                with pytest.raises(_ShutdownRequested):
                    await owner
            elif outcome == "failure":
                release.set()
                with pytest.raises(ValueError, match="synthetic receive"):
                    await owner
            else:
                release.set()
                assert await owner == []
        assert finished.is_set()
        assert shutdown.finished.is_set()
    finally:
        owner.cancel()
        await asyncio.gather(owner, return_exceptions=True)
