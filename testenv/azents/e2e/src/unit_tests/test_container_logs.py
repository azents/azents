"""Tests for E2E container-log diagnostics."""

from types import SimpleNamespace
from typing import cast

import pytest

from support.container_logs import (
    emit_container_logs,
    read_container_logs,
)
from tests import conftest as e2e_conftest


class _Container:
    """Small fake container with deterministic stdout and stderr."""

    def __init__(self, stdout: bytes, stderr: bytes) -> None:
        self.stdout = stdout
        self.stderr = stderr

    def get_logs(self) -> tuple[bytes, bytes]:
        """Return configured output."""
        return self.stdout, self.stderr


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
) -> None:
    """A failed test report prints complete active server logs to CI stdout."""
    lines: list[str] = []
    terminal_reporter = SimpleNamespace(write_line=lines.append)
    config = SimpleNamespace(
        pluginmanager=SimpleNamespace(
            get_plugin=lambda name: (
                terminal_reporter if name == "terminalreporter" else None
            )
        )
    )
    item = cast(pytest.Item, SimpleNamespace(config=config, stash={}))
    monkeypatch.setattr(e2e_conftest, "_SERVER_LOG_CAPTURES", {})
    e2e_conftest._register_server_log_capture(  # pyright: ignore[reportPrivateUsage]
        "azents-public-server",
        _Container(b"public stdout", b"public stderr"),
    )

    hook = e2e_conftest.pytest_runtest_makereport(
        item,
        cast(pytest.CallInfo[None], None),
    )
    assert next(hook) is None
    report = cast(pytest.TestReport, SimpleNamespace(when="call", failed=True))
    with pytest.raises(StopIteration) as stopped:
        hook.send(report)

    assert stopped.value.value is report
    assert lines == [
        "=== azents-public-server logs ===",
        "public stdoutpublic stderr",
    ]
