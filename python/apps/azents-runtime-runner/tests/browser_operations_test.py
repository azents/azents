"""Browser commands use typed ingress and the current Runner transport fence."""

from datetime import UTC, datetime
from pathlib import Path

import pytest
from azents_runtime_control.browser_contract import (
    BrowserAuthority,
    BrowserCommand,
    BrowserOpenCommand,
    BrowserResult,
    encode_browser_command,
)
from azents_runtime_control.runner import (
    RunnerOperationEnvelope,
    RunnerOperationEvent,
    RuntimeRunnerEventType,
)

from azents_runtime_runner.browser import RunnerBrowserManager
from azents_runtime_runner.execution import DirectExecutionBackend
from azents_runtime_runner.operations import RunnerOperations
from azents_runtime_runner.workspace import Workspace


class Sink:
    def __init__(self) -> None:
        self.events: list[RunnerOperationEvent] = []

    async def append_runner_event(self, event: RunnerOperationEvent) -> None:
        self.events.append(event)


class Manager(RunnerBrowserManager):
    def __init__(self, root: Path) -> None:
        super().__init__(workspace_root=root, proxy=None)
        self.received: list[BrowserCommand] = []
        self.bind_runtime("runtime", lambda: 7)

    async def execute(self, command: BrowserCommand) -> BrowserResult:
        self.received.append(command)
        return BrowserResult((), None, None, False, (), None, None, None, None, "none")


def operation(root: Path, generation: int) -> RunnerOperationEnvelope:
    payload = encode_browser_command(
        BrowserOpenCommand(
            BrowserAuthority("concrete-session", str(root / "concrete-session")),
            None,
            None,
            None,
        )
    )
    return RunnerOperationEnvelope(
        request_id="command",
        runtime_id="runtime",
        runner_generation=generation,
        operation_type="browser.open",
        payload=payload,
        reply_stream_id="reply",
        body_stream_id=None,
        body_chunks=(),
        deadline_at=datetime.now(UTC),
        owner_session_id="separate-scheduling-owner",
    )


async def test_concrete_browser_authority_not_scheduling_owner(tmp_path: Path) -> None:
    sink = Sink()
    manager = Manager(tmp_path)
    operations = RunnerOperations(
        client=sink,
        browser_manager=manager,
        workspace=Workspace(str(tmp_path)),
        execution_backend=DirectExecutionBackend(),
    )
    await operations.handle(operation(tmp_path, 7))
    assert manager.received[0].authority.session_id == "concrete-session"
    assert sink.events[-1].event_type is RuntimeRunnerEventType.FINAL_SUCCESS
    await operations.close()


@pytest.mark.parametrize("generation", [0, 6, 8])
async def test_stale_generation_rejected_before_browser_command(
    tmp_path: Path, generation: int
) -> None:
    sink = Sink()
    manager = Manager(tmp_path)
    operations = RunnerOperations(
        client=sink,
        browser_manager=manager,
        workspace=Workspace(str(tmp_path)),
        execution_backend=DirectExecutionBackend(),
    )
    await operations.handle(operation(tmp_path, generation))
    assert not manager.received
    assert sink.events[-1].payload["error_code"] == "browser_stale_generation"
    await operations.close()


async def test_unknown_browser_fields_fail_typed_ingress(tmp_path: Path) -> None:
    sink = Sink()
    manager = Manager(tmp_path)
    operations = RunnerOperations(
        client=sink,
        browser_manager=manager,
        workspace=Workspace(str(tmp_path)),
        execution_backend=DirectExecutionBackend(),
    )
    request = operation(tmp_path, 7)
    payload = dict(request.payload)
    payload["script"] = "never executed"
    malformed = RunnerOperationEnvelope(
        request.request_id,
        request.runtime_id,
        request.runner_generation,
        request.operation_type,
        payload,
        request.reply_stream_id,
        request.body_stream_id,
        request.body_chunks,
        request.deadline_at,
        request.owner_session_id,
    )
    await operations.handle(malformed)
    assert not manager.received
    assert sink.events[-1].payload["error_code"] == "browser_invalid_payload"
    message = sink.events[-1].payload["error_message"]
    assert isinstance(message, str)
    assert "script" not in message
    await operations.close()
