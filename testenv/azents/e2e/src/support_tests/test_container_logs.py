"""Tests for E2E container-log diagnostics."""

from typing import NamedTuple

import pytest

from support.container_logs import (
    emit_container_logs,
    read_container_logs,
)
from tests import conftest as e2e_conftest


class _ContainerLogs(NamedTuple):
    """Container stdout and stderr returned by the test fake."""

    stdout: bytes
    stderr: bytes


class _Container:
    """Small fake container with deterministic stdout and stderr."""

    def __init__(self, stdout: bytes, stderr: bytes) -> None:
        self.stdout = stdout
        self.stderr = stderr

    def get_logs(self) -> _ContainerLogs:
        """Return configured output."""
        return _ContainerLogs(stdout=self.stdout, stderr=self.stderr)


def test_read_container_logs_returns_both_container_output_streams() -> None:
    """Diagnostic output retains both stdout and stderr without modification."""
    logs = read_container_logs(_Container(b"stdout token-value", b"stderr token-value"))

    assert logs == "stdout token-valuestderr token-value"


def test_emit_container_logs_writes_complete_terminal_output() -> None:
    """Terminal diagnostics retain the server name and complete server output."""
    lines: list[str] = []

    emit_container_logs(
        _Container(b"token-value\nnext line", b""),
        server_name="azents-public-server",
        write_line=lines.append,
    )

    assert lines == [
        "=== azents-public-server logs ===",
        "token-value",
        "next line",
    ]


def test_failed_report_emits_active_server_logs_to_terminal_reporter(
    monkeypatch: pytest.MonkeyPatch,
    request: pytest.FixtureRequest,
) -> None:
    """A failed test report prints complete active server logs to CI stdout."""
    lines: list[str] = []

    class Reporter:
        def write_line(self, line: str) -> None:
            lines.append(line)

    reporter = Reporter()
    get_plugin = request.config.pluginmanager.get_plugin

    def lookup_plugin(name: str) -> object:
        return reporter if name == "terminalreporter" else get_plugin(name)

    monkeypatch.setattr(request.config.pluginmanager, "get_plugin", lookup_plugin)
    item = request.node
    monkeypatch.setattr(e2e_conftest, "_SERVER_LOG_CAPTURES", {})
    monkeypatch.setattr(
        e2e_conftest,
        "_runtime_container_diagnostics",
        lambda: ("fake Runtime evidence",),
    )
    e2e_conftest._register_server_log_capture(  # pyright: ignore[reportPrivateUsage]
        "azents-public-server",
        _Container(b"public stdout", b"public stderr"),
    )

    call = pytest.CallInfo.from_call(lambda: None, when="call")
    hook = e2e_conftest.pytest_runtest_makereport(item, call)
    assert next(hook) is None
    report = pytest.TestReport.from_item_and_call(item, call)
    report.outcome = "failed"
    with pytest.raises(StopIteration) as stopped:
        hook.send(report)

    assert stopped.value.value is report
    assert lines == [
        "=== azents-public-server logs ===",
        "public stdoutpublic stderr",
        "fake Runtime evidence",
    ]
