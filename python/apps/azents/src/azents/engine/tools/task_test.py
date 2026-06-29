"""Background task companion tool tests."""

import asyncio
import json

import pytest

from azents.core.tools import ToolkitStatus, TurnContext
from azents.engine.run.background import BackgroundTask, BackgroundTaskRegistry
from azents.engine.run.types import FunctionToolError, FunctionToolResult
from azents.engine.tools.task import BackgroundTaskToolkit


def _make_turn_context() -> TurnContext:
    """TurnContext for tests."""

    async def _noop_publish(_event: object) -> None:
        pass

    return TurnContext(
        user_id="user-1",
        workspace_id="ws-1",
        model="claude-3",
        run_id="run-1",
        publish_event=_noop_publish,
    )


async def _noop(_: BackgroundTask) -> None:
    pass


async def _run_slow(delay: float = 10.0) -> str:
    await asyncio.sleep(delay)
    return "never"


async def _register_dummy(
    registry: BackgroundTaskRegistry,
    *,
    task_id: str,
    parent_session_id: str,
) -> asyncio.Task[str | FunctionToolResult]:
    """Register dummy task in Registry and return future."""
    future: asyncio.Task[str | FunctionToolResult] = asyncio.create_task(_run_slow())
    registry.register(
        task_id=task_id,
        future=future,
        parent_session_id=parent_session_id,
        agent_id="agent-1",
        workspace_id="ws-1",
        tool_name="subagent",
    )
    return future


@pytest.mark.asyncio
async def test_toolkit_returns_enabled_with_two_tools() -> None:
    """Toolkit returns two tools in ENABLED status."""
    registry = BackgroundTaskRegistry(on_complete=_noop)
    toolkit = BackgroundTaskToolkit(registry=registry, session_id="session-1")

    state = await toolkit.update_context(_make_turn_context())
    assert state.status == ToolkitStatus.ENABLED
    names = sorted(t.spec.name for t in state.tools)
    assert names == ["task_status", "task_stop"]
    assert "run_in_background" in (
        await toolkit.get_static_prompt(_make_turn_context())
    )


@pytest.mark.asyncio
async def test_task_status_returns_running_for_live_task() -> None:
    """task_status returns status of running task."""
    registry = BackgroundTaskRegistry(on_complete=_noop)
    future = await _register_dummy(
        registry, task_id="t1", parent_session_id="session-1"
    )
    toolkit = BackgroundTaskToolkit(registry=registry, session_id="session-1")
    state = await toolkit.update_context(_make_turn_context())
    status_tool = next(t for t in state.tools if t.spec.name == "task_status")

    result = await status_tool.handler(json.dumps({"task_id": "t1"}))
    assert isinstance(result, str)
    payload = json.loads(result)
    assert payload["task_id"] == "t1"
    assert payload["status"] == "running"
    assert payload["tool_name"] == "subagent"
    assert payload["elapsed_seconds"] >= 0

    future.cancel()


@pytest.mark.asyncio
async def test_task_status_not_found_for_unknown_task() -> None:
    """task_status returns not_found for nonexistent task."""
    registry = BackgroundTaskRegistry(on_complete=_noop)
    toolkit = BackgroundTaskToolkit(registry=registry, session_id="session-1")
    state = await toolkit.update_context(_make_turn_context())
    status_tool = next(t for t in state.tools if t.spec.name == "task_status")

    result = await status_tool.handler(json.dumps({"task_id": "missing"}))
    assert isinstance(result, str)
    payload = json.loads(result)
    assert payload["status"] == "not_found"


@pytest.mark.asyncio
async def test_task_stop_cancels_owned_task() -> None:
    """task_stop cancels task in same session."""
    registry = BackgroundTaskRegistry(on_complete=_noop)
    future = await _register_dummy(
        registry, task_id="t1", parent_session_id="session-1"
    )
    toolkit = BackgroundTaskToolkit(registry=registry, session_id="session-1")
    state = await toolkit.update_context(_make_turn_context())
    stop_tool = next(t for t in state.tools if t.spec.name == "task_stop")

    result = await stop_tool.handler(
        json.dumps({"task_id": "t1", "reason": "wrong direction"})
    )
    assert isinstance(result, str)
    payload = json.loads(result)
    assert payload["cancelled"] is True

    with pytest.raises(asyncio.CancelledError):
        await future


@pytest.mark.asyncio
async def test_task_stop_rejects_cross_session_cancellation() -> None:
    """task_stop denies task from different session (permission check)."""
    registry = BackgroundTaskRegistry(on_complete=_noop)
    future = await _register_dummy(
        registry, task_id="t1", parent_session_id="session-other"
    )
    # Call session is session-mine, task owner is session-other
    toolkit = BackgroundTaskToolkit(registry=registry, session_id="session-mine")
    state = await toolkit.update_context(_make_turn_context())
    stop_tool = next(t for t in state.tools if t.spec.name == "task_stop")

    with pytest.raises(FunctionToolError, match="another session"):
        await stop_tool.handler(json.dumps({"task_id": "t1"}))
    # task should still be running
    assert registry.get("t1") is not None

    future.cancel()


@pytest.mark.asyncio
async def test_task_stop_returns_not_found_for_unknown_task() -> None:
    """task_stop returns cancelled=False for nonexistent task."""
    registry = BackgroundTaskRegistry(on_complete=_noop)
    toolkit = BackgroundTaskToolkit(registry=registry, session_id="session-1")
    state = await toolkit.update_context(_make_turn_context())
    stop_tool = next(t for t in state.tools if t.spec.name == "task_stop")

    result = await stop_tool.handler(json.dumps({"task_id": "missing"}))
    assert isinstance(result, str)
    payload = json.loads(result)
    assert payload["cancelled"] is False
    assert payload["reason"] == "not_found"
