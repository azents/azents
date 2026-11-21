import asyncio

import pytest

from azcommon.sync import KeyLock


@pytest.mark.asyncio
async def test_cancelling_a_waiter_reclaims_only_its_registration() -> None:
    lock = KeyLock()
    entered = asyncio.Event()
    survivor_waiting = asyncio.Event()
    survivor_entered = asyncio.Event()

    async def wait_for_key(waiting: asyncio.Event, acquired: asyncio.Event) -> None:
        waiting.set()
        async with lock("shared"):
            acquired.set()

    cancelled_entered = asyncio.Event()
    async with asyncio.timeout(5), asyncio.TaskGroup() as tasks:
        async with lock("shared"):
            cancelled = tasks.create_task(wait_for_key(entered, cancelled_entered))
            await entered.wait()
            survivor = tasks.create_task(
                wait_for_key(survivor_waiting, survivor_entered)
            )
            await survivor_waiting.wait()
            cancelled.cancel("stop waiting")
            with pytest.raises(asyncio.CancelledError, match="stop waiting"):
                await cancelled
            assert not cancelled_entered.is_set()
            assert not survivor_entered.is_set()
        await survivor

    assert survivor_entered.is_set()
    assert not lock._locks
    assert not lock._waiters
