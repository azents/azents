"""Unit tests for concurrent E2E prerequisite lifecycle boundaries."""

import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Self
from unittest.mock import Mock

import pytest
from testcontainers.core.container import DockerContainer

from tests import conftest as e2e_conftest


class _FakeContainer(DockerContainer):
    """Typed container fake for lifecycle compensation tests."""

    def __init__(self) -> None:
        self.start_error: Exception | None = None
        self.started = False
        self.stopped = False

    def start(self) -> Self:
        if self.start_error is not None:
            raise self.start_error
        self.started = True
        return self

    def stop(self, force: bool = True, delete_volume: bool = True) -> None:
        del force, delete_volume
        self.stopped = True


def test_reaper_initialization_respects_disabled_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Leave Ryuk disabled when Testcontainers explicitly disables it."""
    get_instance = Mock()
    monkeypatch.setattr(
        e2e_conftest,
        "testcontainers_config",
        SimpleNamespace(ryuk_disabled=True),
    )
    monkeypatch.setattr(e2e_conftest.Reaper, "get_instance", get_instance)

    e2e_conftest._initialize_testcontainers_reaper()

    get_instance.assert_not_called()


def test_reaper_initialization_runs_once_when_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Initialize Ryuk before prerequisite worker threads when enabled."""
    get_instance = Mock()
    monkeypatch.setattr(
        e2e_conftest,
        "testcontainers_config",
        SimpleNamespace(ryuk_disabled=False),
    )
    monkeypatch.setattr(e2e_conftest.Reaper, "get_instance", get_instance)

    e2e_conftest._initialize_testcontainers_reaper()

    get_instance.assert_called_once_with()


def test_partial_start_failure_stops_container_before_reraising() -> None:
    """Compensate when Testcontainers creates state and then raises."""
    container = _FakeContainer()
    container.start_error = RuntimeError("partial start")
    started_containers: list[DockerContainer] = []

    with pytest.raises(RuntimeError, match="partial start"):
        e2e_conftest._start_tracked_prerequisite_container(
            container,
            started_containers=started_containers,
            started_containers_lock=threading.Lock(),
            readiness=None,
        )

    assert container.stopped
    assert started_containers == []


def test_started_container_is_tracked_before_readiness() -> None:
    """Make readiness failures eligible for session cleanup."""
    container = _FakeContainer()
    started_containers: list[DockerContainer] = []

    def readiness(started: DockerContainer) -> None:
        assert started_containers == [started]
        raise RuntimeError("not ready")

    with pytest.raises(RuntimeError, match="not ready"):
        e2e_conftest._start_tracked_prerequisite_container(
            container,
            started_containers=started_containers,
            started_containers_lock=threading.Lock(),
            readiness=readiness,
        )

    assert container.started
    assert not container.stopped
    assert started_containers == [container]


def test_observability_write_failure_is_non_fatal(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Keep diagnostics I/O separate from prerequisite cleanup."""
    blocked_root = tmp_path / "blocked"
    blocked_root.write_text("not a directory", encoding="utf-8")
    monkeypatch.setenv("AZENTS_E2E_ARTIFACT_DIR", str(blocked_root))

    with pytest.warns(UserWarning, match="Failed to write"):
        e2e_conftest._write_core_prerequisite_observability(
            completed=False,
            wall_seconds=1.0,
            task_timings={},
        )
