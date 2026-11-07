"""Process wait helpers own their child task across every exit path."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from azents_runtime_runner.execution import _wait_process


@pytest.mark.parametrize("outcome", ["cancel", "timeout", "complete", "failure"])
async def test_process_wait_drains_owned_child(outcome: str) -> None:
    started, stopped, release = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def wait() -> int:
        started.set()
        try:
            await release.wait()
            if outcome == "failure":
                raise ValueError("process wait failed")
            return 0
        finally:
            stopped.set()

    process = MagicMock(spec=asyncio.subprocess.Process)
    process.wait = AsyncMock(side_effect=wait)
    owner = asyncio.create_task(
        _wait_process(process, 0 if outcome == "timeout" else 1)
    )
    try:
        await asyncio.wait_for(started.wait(), timeout=1)
        if outcome == "cancel":
            owner.cancel()
            with pytest.raises(asyncio.CancelledError):
                await owner
        elif outcome == "timeout":
            assert not await owner
        elif outcome == "failure":
            release.set()
            with pytest.raises(ValueError, match="process wait failed"):
                await owner
        else:
            release.set()
            assert await owner
        assert stopped.is_set()
    finally:
        if not owner.done():
            owner.cancel()
        await asyncio.gather(owner, return_exceptions=True)
