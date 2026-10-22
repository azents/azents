"""Independent Wait Toolkit tests."""

import asyncio
import json
from unittest.mock import create_autospec

import pytest
from azents_runtime_control.process_observation import (
    ProcessCompletion,
    ProcessObservation,
)

import azents.engine.tools.wait as wait_module
from azents.core.tools import ToolkitStatus, TurnContext
from azents.engine.run.contracts import ToolkitBinding
from azents.engine.run.types import FunctionToolError, FunctionToolResult
from azents.engine.tools.builtin import RuntimeToolkit
from azents.engine.tools.process_wait import ProcessWaitTarget
from azents.engine.tools.runtime_io import RuntimeRunnerOperationUnavailable
from azents.engine.tools.wait import WaitToolkit
from azents.services.agent_wait import WaitObservation
from azents.worker.run.executor import _refresh_runtime_peer_toolkits
from azents.worker.session.mailbox_activity import MailboxActivityObserver


class _WaitService:
    def __init__(self, observations: list[WaitObservation]) -> None:
        self.observations = iter(observations)

    async def observe(self, session_id: str) -> WaitObservation:
        del session_id
        return next(self.observations)

    async def process_revision(
        self, session_id: str, runtime_id: str, runner_generation: int
    ) -> int:
        return 0


def _context(observer: MailboxActivityObserver) -> TurnContext:
    return TurnContext(
        workspace_id="workspace-1",
        model="gpt-5.1",
        run_id="run-1",
        session_id="session-1",
        publish_event=lambda _event: _noop(),
        mailbox_activity_observer=observer,
    )


async def _noop() -> None:
    return None


class _MutableWaitState:
    def __init__(self) -> None:
        self.pending = False
        self.checkpoint = 7

    async def observe(self, session_id: str) -> WaitObservation:
        return WaitObservation(self.pending, 0, ())

    async def process_revision(
        self, session_id: str, runtime_id: str, runner_generation: int
    ) -> int:
        assert (session_id, runtime_id, runner_generation) == (
            "session-1",
            "runtime-1",
            2,
        )
        return self.checkpoint


class _ShellSource:
    def __init__(self) -> None:
        self.entered = asyncio.Event()
        self.finished = asyncio.Event()
        self.cancelled = asyncio.Event()
        self.cancel_release = asyncio.Event()
        self.after_revision: int | None = None
        self.timeout_ms: int | None = None
        self.error = False

    async def process_wait_target(self) -> ProcessWaitTarget:
        return ProcessWaitTarget("runtime-1", 2, "session-1")

    async def wait_processes(
        self, target: ProcessWaitTarget, *, after_revision: int, timeout_ms: int
    ) -> ProcessObservation:
        self.after_revision = after_revision
        self.timeout_ms = timeout_ms
        self.entered.set()
        try:
            await self.finished.wait()
        except asyncio.CancelledError:
            self.cancelled.set()
            # Simulate slow remote cancellation acknowledgement.
            await self.cancel_release.wait()
            raise
        if self.error:
            raise RuntimeRunnerOperationUnavailable("Runner disconnected")
        return ProcessObservation(
            revision=8,
            running_count=1,
            completed=(ProcessCompletion("proc-1", "exited"),),
        )


def test_managed_wait_rebinds_replaced_or_removed_runtime() -> None:
    old = create_autospec(RuntimeToolkit, instance=True)
    current = create_autospec(RuntimeToolkit, instance=True)
    toolkit = WaitToolkit(wait_service=_MutableWaitState(), process_source=old)
    wait_binding = ToolkitBinding(toolkit, "wait", "wait", False)
    runtime_binding = ToolkitBinding(current, "runtime", "runtime", False)
    _refresh_runtime_peer_toolkits([wait_binding, runtime_binding])
    assert toolkit.process_source is current
    _refresh_runtime_peer_toolkits([wait_binding])
    assert toolkit.process_source is None


@pytest.mark.asyncio
async def test_stalled_observation_cleanup_is_bounded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(wait_module, "_OBSERVATION_CLEANUP_GRACE_SECONDS", 0)
    observer = MailboxActivityObserver()
    service, source = _MutableWaitState(), _ShellSource()
    toolkit = WaitToolkit(wait_service=service, process_source=source)
    state = await toolkit.update_context(_context(observer))
    waiter = asyncio.ensure_future(state.tools[0].handler("{}"))
    await source.entered.wait()
    service.pending = True
    observer.notify()
    await asyncio.wait_for(waiter, timeout=2)
    await source.cancelled.wait()
    await asyncio.wait_for(
        asyncio.gather(*toolkit.cleanup_tasks, return_exceptions=True), timeout=2
    )
    assert not toolkit.cleanup_tasks
    assert not source.cancel_release.is_set()


@pytest.mark.asyncio
async def test_shell_only_completion_returns_cursor_without_output() -> None:
    observer = MailboxActivityObserver()
    service, source = _MutableWaitState(), _ShellSource()
    toolkit = WaitToolkit(wait_service=service, process_source=source)
    state = await toolkit.update_context(_context(observer))
    tool = state.tools[0]
    properties = tool.spec.input_schema["properties"]
    assert isinstance(properties, dict) and set(properties) == {"timeout_seconds"}
    waiter = asyncio.ensure_future(tool.handler('{"timeout_seconds": 30}'))
    await source.entered.wait()
    assert not waiter.done()
    assert source.after_revision == 7 and source.timeout_ms == 30_000
    source.finished.set()
    result = await asyncio.wait_for(waiter, timeout=2)
    assert isinstance(result, FunctionToolResult)
    assert result.metadata == {
        "shell_wait_runtime_id": "runtime-1",
        "shell_wait_generation": 2,
        "shell_wait_revision": 8,
    }
    assert isinstance(result.output, str)
    assert json.loads(result.output) == {
        "outcome": "activity",
        "reason": "shell_completion",
        "completed": [{"process_id": "proc-1", "status": "exited"}],
    }


@pytest.mark.asyncio
async def test_mailbox_wakes_shell_wait_without_awaiting_remote_cancellation() -> None:
    observer = MailboxActivityObserver()
    service, source = _MutableWaitState(), _ShellSource()
    toolkit = WaitToolkit(wait_service=service, process_source=source)
    state = await toolkit.update_context(_context(observer))
    waiter = asyncio.ensure_future(state.tools[0].handler('{"timeout_seconds": 900}'))
    await source.entered.wait()
    service.pending = True
    observer.notify()
    result = await asyncio.wait_for(waiter, timeout=2)
    assert isinstance(result, str)
    assert json.loads(result)["outcome"] == "activity"
    await source.cancelled.wait()
    assert toolkit.cleanup_tasks
    source.cancel_release.set()
    await asyncio.wait_for(
        asyncio.gather(*toolkit.cleanup_tasks, return_exceptions=True), 2
    )
    assert service.checkpoint == 7


@pytest.mark.asyncio
async def test_mailbox_has_priority_over_simultaneous_shell_completion() -> None:
    observer = MailboxActivityObserver()
    service, source = _MutableWaitState(), _ShellSource()
    toolkit = WaitToolkit(wait_service=service, process_source=source)
    state = await toolkit.update_context(_context(observer))
    waiter = asyncio.ensure_future(state.tools[0].handler("{}"))
    await source.entered.wait()
    service.pending = True
    source.finished.set()
    observer.notify()
    result = await asyncio.wait_for(waiter, timeout=2)
    assert (
        isinstance(result, str) and json.loads(result)["reason"] != "shell_completion"
    )
    # No durable acknowledgement is returned for the unselected completion.
    assert service.checkpoint == 7


@pytest.mark.asyncio
async def test_runtime_failure_is_not_reported_as_no_work() -> None:
    source = _ShellSource()
    source.error = True
    source.finished.set()
    toolkit = WaitToolkit(wait_service=_MutableWaitState(), process_source=source)
    state = await toolkit.update_context(_context(MailboxActivityObserver()))
    with pytest.raises(FunctionToolError, match="Runner disconnected"):
        await state.tools[0].handler("{}")


@pytest.mark.asyncio
async def test_wait_tool_is_independent_and_describes_input_activity() -> None:
    observer = MailboxActivityObserver()
    toolkit = WaitToolkit(
        wait_service=_WaitService([WaitObservation(True, 1, ("/root/child",))]),
        process_source=None,
    )
    state = await toolkit.update_context(_context(observer))

    assert state.status is ToolkitStatus.ENABLED
    assert [tool.spec.name for tool in state.tools] == ["wait"]
    result = await state.tools[0].handler(json.dumps({}))
    assert isinstance(result, str)
    assert json.loads(result) == {
        "outcome": "activity",
        "reason": (
            "new user input, agent or subagent message, scheduled continuation, "
            "external-channel request, or action"
        ),
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("observation", "expected"),
    [
        (
            WaitObservation(False, 0, ()),
            {"outcome": "not_waitable", "reason": "no_descendants"},
        ),
        (
            WaitObservation(False, 1, ()),
            {"outcome": "not_waitable", "reason": "all_descendants_idle"},
        ),
    ],
)
async def test_wait_tool_reports_not_waitable_outcomes(
    observation: WaitObservation,
    expected: dict[str, str],
) -> None:
    observer = MailboxActivityObserver()
    toolkit = WaitToolkit(wait_service=_WaitService([observation]), process_source=None)
    state = await toolkit.update_context(_context(observer))

    result = await state.tools[0].handler(json.dumps({"timeout_seconds": 0}))
    assert isinstance(result, str)
    assert json.loads(result) == expected


@pytest.mark.asyncio
async def test_wait_tool_accepts_fifteen_minute_timeout() -> None:
    observer = MailboxActivityObserver()
    toolkit = WaitToolkit(
        wait_service=_WaitService([WaitObservation(False, 0, ())]), process_source=None
    )
    state = await toolkit.update_context(_context(observer))

    result = await state.tools[0].handler(json.dumps({"timeout_seconds": 900}))
    assert isinstance(result, str)
    assert json.loads(result) == {
        "outcome": "not_waitable",
        "reason": "no_descendants",
    }


@pytest.mark.asyncio
async def test_wait_tool_reconciles_after_activity_signal_loss() -> None:
    observer = MailboxActivityObserver()
    service = _WaitService(
        [
            WaitObservation(False, 1, ("/root/child",)),
            WaitObservation(True, 1, ("/root/child",)),
        ]
    )
    toolkit = WaitToolkit(wait_service=service, process_source=None)
    state = await toolkit.update_context(_context(observer))

    result = await state.tools[0].handler(json.dumps({"timeout_seconds": 1}))
    assert isinstance(result, str)
    assert json.loads(result) == {
        "outcome": "activity",
        "reason": (
            "new user input, agent or subagent message, scheduled continuation, "
            "external-channel request, or action"
        ),
    }
