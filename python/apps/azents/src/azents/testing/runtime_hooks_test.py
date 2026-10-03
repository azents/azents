"""Tests for the testenv runtime hook QA toolkit."""

import asyncio
import logging
from pathlib import Path

import pytest

from azents.engine.hooks.types import (
    AfterToolCallHookContext,
    BeforeToolCallHookContext,
    RunEndHookContext,
    RunStartHookContext,
    RuntimeHibernateHookContext,
    RuntimeRestoreHookContext,
    SessionStartHookContext,
    TurnEndHookContext,
    TurnStartHookContext,
)
from azents.engine.run.types import FunctionTool
from azents.testing.runtime_hooks import RuntimeHookQAContext
from azents.testing.runtime_hooks import (
    TestenvRuntimeHookQAConfig as RuntimeHookQAConfig,
)
from azents.testing.runtime_hooks import (
    TestenvRuntimeHookQAToolkit as RuntimeHookQAToolkit,
)


class _RuntimeHookQAToolkitForTest(RuntimeHookQAToolkit):
    """Expose the probe tool for focused behavior tests."""

    def make_probe_tool(self) -> FunctionTool:
        """Return the probe tool under test."""
        return self._make_probe_tool()

    def log_context(self, context: RuntimeHookQAContext) -> None:
        """Expose typed context logging for the declared hook variants."""
        self._log("test_lifecycle", context)


@pytest.mark.asyncio
async def test_probe_waits_for_release_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep the probe blocked until the configured release file exists."""
    release_file = tmp_path / "release"
    release_file_checked = asyncio.Event()
    path_exists = Path.exists

    def observed_exists(path: Path) -> bool:
        if path == release_file:
            release_file_checked.set()
        return path_exists(path)

    monkeypatch.setattr(Path, "exists", observed_exists)
    toolkit = _RuntimeHookQAToolkitForTest(
        RuntimeHookQAConfig(release_file_path=str(release_file))
    )
    tool = toolkit.make_probe_tool()

    task = asyncio.ensure_future(tool.handler('{"marker":"blocked"}'))
    await asyncio.wait_for(release_file_checked.wait(), timeout=1)
    assert not task.done()

    release_file.touch()

    assert await asyncio.wait_for(task, timeout=1) == (
        "runtime hook qa raw output: blocked"
    )


@pytest.mark.parametrize(
    "context",
    [
        SessionStartHookContext("workspace", "agent", "session", None),
        RunStartHookContext("workspace", "agent", "session", "run"),
        RunEndHookContext("workspace", "agent", "session", "run", "completed"),
        TurnStartHookContext("workspace", "agent", "session", "run", 1),
        TurnEndHookContext("workspace", "agent", "session", "run", "error", 1),
        BeforeToolCallHookContext(
            "probe", "toolkit", "sensitive-args", "workspace", "agent", "session", "run"
        ),
        AfterToolCallHookContext(
            "probe",
            "toolkit",
            "sensitive-args",
            "workspace",
            "agent",
            "session",
            "run",
            "sensitive-output",
            "sensitive-error",
        ),
        RuntimeHibernateHookContext(None, "agent", None, "runtime"),
        RuntimeRestoreHookContext("workspace", "agent", "session", "runtime"),
    ],
)
def test_hook_context_logging_keeps_typed_optional_fields(
    context: RuntimeHookQAContext,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Every observed hook logs only the declared non-sensitive context."""
    toolkit = _RuntimeHookQAToolkitForTest(RuntimeHookQAConfig())

    with caplog.at_level(logging.INFO, logger="azents.testing.runtime_hooks"):
        toolkit.log_context(context)

    record = caplog.records[-1]
    assert record.getMessage() == "Runtime hook QA lifecycle event"
    assert record.args == ()
    fields = record.__dict__
    assert fields["runtime_hook_qa_lifecycle"] == "test_lifecycle"
    assert fields["workspace_id"] == context.workspace_id
    assert fields["agent_id"] == context.agent_id
    assert fields["session_id"] == context.session_id
    if isinstance(context, RuntimeHibernateHookContext | RuntimeRestoreHookContext):
        assert fields["run_id"] is None
    else:
        assert fields["run_id"] == context.run_id
    if isinstance(context, RunEndHookContext | TurnEndHookContext):
        assert fields["reason"] == context.reason
    else:
        assert fields["reason"] is None
    if isinstance(context, BeforeToolCallHookContext | AfterToolCallHookContext):
        assert fields["tool_name"] == context.tool_name
        assert fields["toolkit_slug"] == context.toolkit_slug
    else:
        assert fields["tool_name"] is None
        assert fields["toolkit_slug"] is None
    assert "sensitive" not in caplog.text
    assert "args_json" not in fields
    assert "output_text" not in fields
    assert "error_message" not in fields
