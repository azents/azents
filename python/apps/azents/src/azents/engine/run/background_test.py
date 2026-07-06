"""BackgroundTaskRegistry unit tests."""

import asyncio
from contextlib import suppress

import pytest

from azents.engine.run.background import BackgroundTask, BackgroundTaskRegistry


async def _wait_for_completion(registry: BackgroundTaskRegistry, task_id: str) -> None:
    """Wait until task is removed from registry, up to 1 second."""
    for _ in range(100):
        if registry.get(task_id) is None:
            return
        await asyncio.sleep(0.01)
    msg = f"Task {task_id} did not clean up in time"
    raise AssertionError(msg)


async def _run_success(result: str = "ok") -> str:
    """Test coroutine that immediately returns successful result."""
    await asyncio.sleep(0)
    return result


async def _run_slow(delay: float = 10.0) -> str:
    """Long-running test coroutine for cancel tests."""
    await asyncio.sleep(delay)
    return "should not reach"


async def _run_failure() -> str:
    """Test coroutine that raises error."""
    await asyncio.sleep(0)
    raise RuntimeError("boom")


@pytest.mark.asyncio
async def test_register_and_complete_invokes_on_complete() -> None:
    """on_complete callback should be called when registered task completes."""
    completed: list[BackgroundTask] = []

    async def on_complete(task: BackgroundTask) -> None:
        completed.append(task)

    registry = BackgroundTaskRegistry(on_complete=on_complete)
    future = asyncio.create_task(_run_success("done"))
    registered = registry.register(
        task_id="t1",
        future=future,
        parent_session_id="session-1",
        agent_id="agent-1",
        workspace_id="ws-1",
        tool_name="background_tool",
    )
    assert registered.task_id == "t1"

    # wait for future completion + registry cleanup
    await future
    await _wait_for_completion(registry, "t1")

    assert len(completed) == 1
    assert completed[0].task_id == "t1"
    assert completed[0].tool_name == "background_tool"
    # removed from registry after completion
    assert registry.list_for_session("session-1") == []


@pytest.mark.asyncio
async def test_get_returns_running_task() -> None:
    """Running task should be retrievable with get."""

    async def _noop(_: BackgroundTask) -> None:
        pass

    registry = BackgroundTaskRegistry(on_complete=_noop)
    future = asyncio.create_task(_run_slow())
    registry.register(
        task_id="t1",
        future=future,
        parent_session_id="session-1",
        agent_id="agent-1",
        workspace_id="ws-1",
        tool_name="background_tool",
    )
    assert registry.get("t1") is not None
    assert registry.get("t1") is not None  # can be called multiple times
    # task list for same session
    tasks = registry.list_for_session("session-1")
    assert len(tasks) == 1
    assert tasks[0].task_id == "t1"
    # cleanup
    future.cancel()
    with suppress(asyncio.CancelledError):
        await future


@pytest.mark.asyncio
async def test_cancel_returns_true_and_cleans_up() -> None:
    """cancel returns True and removes from registry through completion callback."""

    async def _noop(_: BackgroundTask) -> None:
        pass

    registry = BackgroundTaskRegistry(on_complete=_noop)
    future = asyncio.create_task(_run_slow())
    registry.register(
        task_id="t1",
        future=future,
        parent_session_id="session-1",
        agent_id="agent-1",
        workspace_id="ws-1",
        tool_name="background_tool",
    )
    cancelled = await registry.cancel("t1")
    assert cancelled is True
    # wait for cancel propagation + done callback + _handle_completion
    with suppress(asyncio.CancelledError):
        await future
    await _wait_for_completion(registry, "t1")


@pytest.mark.asyncio
async def test_cancel_missing_returns_false() -> None:
    """cancel returns False for nonexistent task ID."""

    async def _noop(_: BackgroundTask) -> None:
        pass

    registry = BackgroundTaskRegistry(on_complete=_noop)
    assert await registry.cancel("nonexistent") is False


@pytest.mark.asyncio
async def test_cancel_all_for_session() -> None:
    """cancel_all by session cancels only tasks for that session."""

    async def _noop(_: BackgroundTask) -> None:
        pass

    registry = BackgroundTaskRegistry(on_complete=_noop)
    f1 = asyncio.create_task(_run_slow())
    f2 = asyncio.create_task(_run_slow())
    f3 = asyncio.create_task(_run_slow())
    registry.register(
        task_id="t1",
        future=f1,
        parent_session_id="session-1",
        agent_id="agent-1",
        workspace_id="ws-1",
        tool_name="background_tool",
    )
    registry.register(
        task_id="t2",
        future=f2,
        parent_session_id="session-1",
        agent_id="agent-1",
        workspace_id="ws-1",
        tool_name="background_tool",
    )
    registry.register(
        task_id="t3",
        future=f3,
        parent_session_id="session-2",
        agent_id="agent-1",
        workspace_id="ws-1",
        tool_name="background_tool",
    )

    await registry.cancel_all_for_session("session-1")
    # cancel propagation + cleanup
    with suppress(asyncio.CancelledError):
        await f1
    with suppress(asyncio.CancelledError):
        await f2
    await _wait_for_completion(registry, "t1")
    await _wait_for_completion(registry, "t2")

    # session-2 task should remain
    assert registry.get("t3") is not None

    # cleanup
    f3.cancel()
    with suppress(asyncio.CancelledError):
        await f3


@pytest.mark.asyncio
async def test_cancel_all_waits_for_completion_cleanup() -> None:
    """cancel_all waits for completion cleanup after future cancellation."""
    completed = asyncio.Event()

    async def on_complete(_: BackgroundTask) -> None:
        await asyncio.sleep(0)
        completed.set()

    registry = BackgroundTaskRegistry(on_complete=on_complete)
    future = asyncio.create_task(_run_slow())
    registry.register(
        task_id="t1",
        future=future,
        parent_session_id="session-1",
        agent_id="agent-1",
        workspace_id="ws-1",
        tool_name="background_tool",
    )

    await registry.cancel_all()

    assert completed.is_set()
    assert registry.get("t1") is None
    assert registry.list_for_session("session-1") == []


@pytest.mark.asyncio
async def test_on_complete_called_even_when_future_failed() -> None:
    """on_complete is called even when Future ends with exception."""

    completed: list[BackgroundTask] = []

    async def on_complete(task: BackgroundTask) -> None:
        completed.append(task)

    registry = BackgroundTaskRegistry(on_complete=on_complete)
    future = asyncio.create_task(_run_failure())
    registry.register(
        task_id="t1",
        future=future,
        parent_session_id="session-1",
        agent_id="agent-1",
        workspace_id="ws-1",
        tool_name="background_tool",
    )
    # wait until future ends with exception
    with pytest.raises(RuntimeError, match="boom"):
        await future
    await _wait_for_completion(registry, "t1")

    assert len(completed) == 1
    assert completed[0].task_id == "t1"


@pytest.mark.asyncio
async def test_on_complete_exception_does_not_leak_task_entry() -> None:
    """Removed from registry even when on_complete callback raises exception."""

    async def on_complete(_: BackgroundTask) -> None:
        raise RuntimeError("callback error")

    registry = BackgroundTaskRegistry(on_complete=on_complete)
    future = asyncio.create_task(_run_success())
    registry.register(
        task_id="t1",
        future=future,
        parent_session_id="session-1",
        agent_id="agent-1",
        workspace_id="ws-1",
        tool_name="background_tool",
    )
    await future
    await _wait_for_completion(registry, "t1")
