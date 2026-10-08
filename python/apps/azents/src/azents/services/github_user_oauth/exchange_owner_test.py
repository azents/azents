"""Strong application lifetime and immediate caller cancellation evidence."""

import asyncio
import gc

import pytest

from azents.core.config import Config
from azents.services.github_user_oauth.exchange_owner import (
    GitHubUserExchangeOperation,
    get_github_user_exchange_owner,
)
from azents.utils.appctx import AppContext


async def test_application_retains_cancelled_request_work_until_cleanup() -> None:
    appctx = AppContext(Config.model_construct())
    owner = await get_github_user_exchange_owner(appctx)
    assert await get_github_user_exchange_owner(appctx) is owner
    entered = asyncio.Event()
    release = asyncio.Event()
    cleaned = asyncio.Event()

    async def physical(operation: GitHubUserExchangeOperation) -> int:
        entered.set()
        await release.wait()
        assert operation.detached
        return 42

    async def finalize() -> None:
        cleaned.set()

    caller = asyncio.create_task(owner.run(physical, finalize))
    await entered.wait()
    caller.cancel()
    with pytest.raises(asyncio.CancelledError):
        await caller
    assert len(owner.operations) == 1
    gc.collect()
    assert not cleaned.is_set()
    release.set()
    await appctx.close()
    assert cleaned.is_set()
    assert owner.operations == set()


async def test_completed_result_cancellation_race_still_runs_finalization() -> None:
    appctx = AppContext(Config.model_construct())
    owner = await get_github_user_exchange_owner(appctx)
    caller: asyncio.Task[int] | None = None
    cleaned = asyncio.Event()

    async def physical(operation: GitHubUserExchangeOperation) -> int:
        assert caller is not None
        # Cancel delivery precisely before this inner result becomes visible.
        asyncio.get_running_loop().call_soon(caller.cancel)
        return 42

    async def finalize() -> None:
        cleaned.set()

    caller = asyncio.create_task(owner.run(physical, finalize))
    with pytest.raises(asyncio.CancelledError):
        await caller
    await appctx.close()
    assert cleaned.is_set()
    assert owner.operations == set()


async def test_detached_cleanup_failure_is_observed_without_exception_secrets(
    caplog: pytest.LogCaptureFixture,
) -> None:
    appctx = AppContext(Config.model_construct())
    owner = await get_github_user_exchange_owner(appctx)
    entered = asyncio.Event()
    release = asyncio.Event()

    async def physical(operation: GitHubUserExchangeOperation) -> None:
        entered.set()
        await release.wait()

    secret = "private-client-secret-must-not-be-logged"

    async def finalize() -> None:
        raise RuntimeError(secret)

    caller = asyncio.create_task(owner.run(physical, finalize))
    await entered.wait()
    caller.cancel()
    with pytest.raises(asyncio.CancelledError):
        await caller
    release.set()
    await appctx.close()
    assert "Detached GitHub token cleanup failed" in caplog.text
    assert "private-client-secret-must-not-be-logged" not in caplog.text
    assert owner.operations == set()
