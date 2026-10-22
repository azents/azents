"""Tests for E2E container-log diagnostics."""

import hashlib
import os
import subprocess
import sys
from pathlib import Path
from typing import Literal, NamedTuple

import pytest

from support.container_logs import (
    FailureLogTail,
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


@pytest.mark.parametrize("phase", ["setup", "call"])
def test_failed_report_emits_active_server_logs_to_terminal_reporter(
    monkeypatch: pytest.MonkeyPatch,
    request: pytest.FixtureRequest,
    phase: Literal["setup", "call"],
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

    call = pytest.CallInfo.from_call(lambda: None, when=phase)
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


def test_worker_failure_persists_without_a_terminal_reporter(
    monkeypatch: pytest.MonkeyPatch,
    request: pytest.FixtureRequest,
    tmp_path: Path,
) -> None:
    """An xdist-style worker retains logs under its existing artifact owner."""
    worker = tmp_path / "workers" / "gw1"
    monkeypatch.setenv("AZENTS_E2E_ARTIFACT_DIR", str(worker))
    get_plugin = request.config.pluginmanager.get_plugin
    monkeypatch.setattr(
        request.config.pluginmanager,
        "get_plugin",
        lambda name: None if name == "terminalreporter" else get_plugin(name),
    )
    monkeypatch.setattr(e2e_conftest.sys, "__stdout__", None)
    monkeypatch.setattr(e2e_conftest, "_SERVER_LOG_CAPTURES", {})
    monkeypatch.setattr(
        e2e_conftest, "_runtime_container_diagnostics", lambda: ("Runtime metadata",)
    )
    e2e_conftest._register_server_log_capture(
        "azents-engine-worker", _Container(b"publication stage failure", b"trace")
    )
    call = pytest.CallInfo.from_call(lambda: None, when="call")
    hook = e2e_conftest.pytest_runtest_makereport(request.node, call)
    assert next(hook) is None
    report = pytest.TestReport.from_item_and_call(request.node, call)
    report.outcome = "failed"
    with pytest.raises(StopIteration) as stopped:
        hook.send(report)
    assert stopped.value.value is report and report.failed
    name = hashlib.sha256(request.node.nodeid.encode()).hexdigest()
    evidence = worker / "server-failures" / f"{name}.log"
    assert "publication stage failuretrace" in evidence.read_text()
    assert "Runtime metadata" in evidence.read_text()
    assert list(tmp_path.glob("server-failures/*")) == []


def test_failure_log_tail_is_bounded_and_keeps_latest_diagnostics(
    tmp_path: Path,
) -> None:
    tail = FailureLogTail()
    tail.append("x" * 2_000_000)
    tail.append("latest failure")
    path = tmp_path / "failure.log"
    tail.save(path, node_id="../arbitrary/testcase")
    value = path.read_text()
    assert value.endswith("latest failure\n")
    assert len(value) <= 1_048_576 + 100
    assert not (tmp_path.parent / "arbitrary").exists()


def test_failure_log_io_error_does_not_replace_original_failure(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    tmp_path: Path,
) -> None:
    def fail_write(*_args: object, **_kwargs: object) -> int:
        raise OSError("diagnostic disk unavailable")

    monkeypatch.setattr(Path, "write_text", fail_write)
    tail = FailureLogTail()
    tail.append("original failure")
    tail.save(tmp_path / "failure.log", node_id="test::failure")
    assert "Failed to persist E2E server diagnostics" in caplog.text


def test_real_parallel_worker_failure_retains_server_artifact(tmp_path: Path) -> None:
    """Execute a failing synthetic call with xdist and fake containers only."""
    root = Path(__file__).resolve().parents[5]
    project = tmp_path / "project"
    project.mkdir()
    evidence = tmp_path / "evidence"
    (project / "conftest.py").write_text(
        "import os\n"
        "from pathlib import Path\n"
        "import pytest\n"
        "from tests import conftest as fixture_owner\n"
        "pytest_plugins = ['tests.conftest']\n"
        "class FakeContainer:\n"
        "    def get_logs(self):\n"
        "        return (b'preserved worker publication failure', b'')\n"
        "def pytest_configure(config):\n"
        "    worker = os.environ.get('PYTEST_XDIST_WORKER')\n"
        "    if worker:\n"
        "        path=Path(os.environ['AZENTS_E2E_ARTIFACT_DIR']) / worker\n"
        "        os.environ['AZENTS_E2E_ARTIFACT_DIR'] = str(path)\n"
        "@pytest.fixture(autouse=True)\n"
        "def fake_diagnostics(monkeypatch):\n"
        "    monkeypatch.setattr(fixture_owner, '_SERVER_LOG_CAPTURES', {})\n"
        "    monkeypatch.setattr(\n"
        "        fixture_owner, '_runtime_container_diagnostics', lambda: ())\n"
        "    fixture_owner._register_server_log_capture('engine', FakeContainer())\n"
    )
    (project / "test_failure.py").write_text(
        "def test_original_failure():\n    assert False, 'original failure retained'\n"
    )
    environment = dict(os.environ)
    for key in (
        "PYTEST_XDIST_WORKER",
        "PYTEST_XDIST_WORKER_COUNT",
        "PYTEST_XDIST_TESTRUNUID",
    ):
        environment.pop(key, None)
    environment["AZENTS_E2E_ARTIFACT_DIR"] = str(evidence)
    environment["PYTHONPATH"] = os.pathsep.join(
        [str(root / "testenv/azents/e2e/src"), str(root)]
    )
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "-n",
            "2",
            "--max-worker-restart=0",
            str(project),
        ],
        env=environment,
        cwd=project,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1, result.stdout + result.stderr
    assert "original failure retained" in result.stdout
    files = list(evidence.glob("gw*/server-failures/*.log"))
    assert len(files) == 1
    assert "preserved worker publication failure" in files[0].read_text()
