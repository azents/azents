"""Application context lifecycle tests."""

import asyncio
from collections.abc import AsyncIterator

import pytest

from azents.utils.appctx import AppContext, AppContextClosedError


@pytest.mark.asyncio
async def test_pre_close_callbacks_run_before_managed_resources() -> None:
    """Runtime drains before lower-level AppContext resources are released."""
    events: list[str] = []
    appctx = AppContext(object())

    async def resource() -> AsyncIterator[object]:
        try:
            yield object()
        finally:
            events.append("resource_closed")

    async def pre_close() -> None:
        events.append("pre_close")

    await appctx.get_variable("resource", resource)
    appctx.add_pre_close_callback(pre_close)

    await appctx.close()
    await appctx.close()

    assert events == ["pre_close", "resource_closed"]


@pytest.mark.asyncio
async def test_resource_resolved_during_pre_close_is_closed_after_drain() -> None:
    """Late resources used by draining tasks remain on the active close stack."""
    events: list[str] = []
    pre_close_started = asyncio.Event()
    finish_pre_close = asyncio.Event()
    appctx = AppContext(object())

    async def resource(name: str) -> AsyncIterator[object]:
        try:
            yield object()
        finally:
            events.append(f"{name}_closed")

    async def early_resource() -> AsyncIterator[object]:
        async for value in resource("early"):
            yield value

    async def late_resource() -> AsyncIterator[object]:
        async for value in resource("late"):
            yield value

    async def pre_close() -> None:
        events.append("pre_close_started")
        pre_close_started.set()
        await finish_pre_close.wait()
        events.append("pre_close_finished")

    await appctx.get_variable("early", early_resource)
    appctx.add_pre_close_callback(pre_close)

    close_task = asyncio.create_task(appctx.close())
    await pre_close_started.wait()
    await appctx.get_variable("late", late_resource)
    assert events == ["pre_close_started"]

    finish_pre_close.set()
    await close_task

    assert events == [
        "pre_close_started",
        "pre_close_finished",
        "late_closed",
        "early_closed",
    ]


@pytest.mark.asyncio
async def test_context_rejects_resources_and_callbacks_after_close() -> None:
    """No resource can race into an unowned replacement stack after teardown."""
    appctx = AppContext(object())

    async def resource() -> AsyncIterator[object]:
        yield object()

    async def callback() -> None:
        return None

    await appctx.close()

    with pytest.raises(AppContextClosedError, match="closing"):
        await appctx.get_variable("late", resource)
    with pytest.raises(AppContextClosedError, match="closing"):
        appctx.add_pre_close_callback(callback)
