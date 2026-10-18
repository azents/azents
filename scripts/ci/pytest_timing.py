"""Write safe, structured pytest timing evidence for every CI pytest project."""

import json
import os
import re
from collections.abc import Generator
from dataclasses import asdict, dataclass
from pathlib import Path
from time import perf_counter

import pytest
from scripts.ci.observability import merge_worker_fixture_timings

_ARTIFACT_DIR_ENV = "AZENTS_CI_ARTIFACT_DIR"
_PYTEST_TIMINGS_FILENAME = "pytest-timings.jsonl"


@dataclass(frozen=True)
class TestPhaseTiming:
    """Timing evidence for one pytest test phase."""

    record_type: str
    node_id: str
    phase: str
    duration_seconds: float
    outcome: str


@dataclass(frozen=True)
class FixtureTiming:
    """Timing evidence for one fixture setup or teardown."""

    record_type: str
    fixture: str
    scope: str
    node_id: str
    phase: str
    duration_seconds: float
    outcome: str


@dataclass
class FixtureTeardownState:
    """Mutable timestamps retained between fixture finalizer hooks."""

    started_at: float | None = None

    def start(self) -> None:
        """Capture the finalizer boundary without inspecting fixture values."""
        self.started_at = monotonic_time()


class TimingObservabilityPlugin:
    """Observe pytest using startup-bound evidence and performance-clock authority."""

    def __init__(self, artifact_path: Path, *, record_test_phases: bool) -> None:
        self.artifact_path = artifact_path
        self.record_test_phases = record_test_phases
        self.fixture_teardown_states: dict[int, FixtureTeardownState] = {}

    def pytest_runtest_logreport(self, report: pytest.TestReport) -> None:
        """Record every test setup, call, and teardown phase."""
        if not self.record_test_phases or report.when is None:
            return
        _append_timing(
            TestPhaseTiming(
                record_type="test_phase",
                node_id=report.nodeid,
                phase=report.when,
                duration_seconds=round(report.duration, 6),
                outcome=report.outcome,
            ),
            self.artifact_path,
        )

    def pytest_unconfigure(self) -> None:
        """Merge after workers and fixture teardown finish, inside pytest wall time."""
        if self.record_test_phases:
            merge_worker_fixture_timings(self.artifact_path.parent)

    @pytest.hookimpl(optionalhook=True, tryfirst=True)
    def pytest_testnodedown(self, node: object, error: object | None) -> None:
        """Abort on worker death before xdist can redistribute its unfinished file."""
        if self.record_test_phases and error is not None:
            pytest.exit(
                "A pytest worker crashed; aborting without worker restart or replay",
                returncode=1,
            )

    @pytest.hookimpl(wrapper=True)
    def pytest_fixture_setup(
        self,
        fixturedef: pytest.FixtureDef[object],
        request: pytest.FixtureRequest,
    ) -> Generator[None, object, object]:
        """Measure real fixture setup without serializing values or consuming mocks."""
        started_at = monotonic_time()
        try:
            result = yield
        except BaseException:
            self.record_fixture_phase(
                fixture=fixturedef.argname,
                scope=fixturedef.scope,
                node_id=request.node.nodeid,
                phase="setup",
                duration_seconds=monotonic_time() - started_at,
                outcome="failed",
            )
            raise
        self.record_fixture_phase(
            fixture=fixturedef.argname,
            scope=fixturedef.scope,
            node_id=request.node.nodeid,
            phase="setup",
            duration_seconds=monotonic_time() - started_at,
            outcome="passed",
        )
        teardown_state = FixtureTeardownState()
        self.fixture_teardown_states[id(fixturedef)] = teardown_state
        fixturedef.addfinalizer(teardown_state.start)
        return result

    def pytest_fixture_post_finalizer(
        self,
        fixturedef: pytest.FixtureDef[object],
        request: pytest.FixtureRequest,
    ) -> None:
        """Record fixture teardown after its finalizers have completed."""
        state = self.fixture_teardown_states.get(id(fixturedef))
        if state is None or state.started_at is None:
            return
        self.record_fixture_phase(
            fixture=fixturedef.argname,
            scope=fixturedef.scope,
            node_id=request.node.nodeid,
            phase="teardown",
            duration_seconds=monotonic_time() - state.started_at,
            outcome="completed",
        )
        del self.fixture_teardown_states[id(fixturedef)]

    def record_fixture_phase(
        self,
        *,
        fixture: str,
        scope: str,
        node_id: str,
        phase: str,
        duration_seconds: float,
        outcome: str,
    ) -> None:
        """Retain the observer destination even when a unit test mocks environment."""
        _append_timing(
            _fixture_timing(
                fixture=fixture,
                scope=scope,
                node_id=node_id,
                phase=phase,
                duration_seconds=duration_seconds,
                outcome=outcome,
            ),
            self.artifact_path,
        )


def pytest_configure(config: pytest.Config) -> None:
    """Enable the same observer for unit, migration, support, and E2E tests."""
    path = timing_path()
    if path is not None:
        worker = os.environ.get("PYTEST_XDIST_WORKER")
        if worker is not None:
            if re.fullmatch(r"gw[0-9]+", worker) is None:
                raise ValueError("Invalid pytest worker identity for timing evidence")
            path = path.with_name(f"fixture-timings-{worker}.jsonl")
        config.pluginmanager.register(
            TimingObservabilityPlugin(path, record_test_phases=worker is None),
            "azents-ci-timing-observability",
        )


def record_test_phase(
    *,
    node_id: str,
    phase: str,
    duration_seconds: float,
    outcome: str,
) -> None:
    """Append explicitly reported timing to the caller's current evidence path."""
    _append_timing(
        TestPhaseTiming(
            record_type="test_phase",
            node_id=node_id,
            phase=phase,
            duration_seconds=round(duration_seconds, 6),
            outcome=outcome,
        ),
        timing_path(),
    )


def _fixture_timing(
    *,
    fixture: str,
    scope: str,
    node_id: str,
    phase: str,
    duration_seconds: float,
    outcome: str,
) -> FixtureTiming:
    return FixtureTiming(
        record_type="fixture",
        fixture=fixture,
        scope=scope,
        node_id=node_id,
        phase=phase,
        duration_seconds=round(duration_seconds, 6),
        outcome=outcome,
    )


def record_fixture_phase(
    *,
    fixture: str,
    scope: str,
    node_id: str,
    phase: str,
    duration_seconds: float,
    outcome: str,
) -> None:
    """Append manually reported fixture timing when artifact capture is enabled."""
    _append_timing(
        _fixture_timing(
            fixture=fixture,
            scope=scope,
            node_id=node_id,
            phase=phase,
            duration_seconds=duration_seconds,
            outcome=outcome,
        ),
        timing_path(),
    )


def monotonic_time() -> float:
    """Use the startup-bound performance clock, not application clock mocks."""
    return perf_counter()


def timing_path() -> Path | None:
    """Return the configured pytest timing artifact path."""
    artifact_dir = os.environ.get(_ARTIFACT_DIR_ENV)
    return (
        Path(artifact_dir) / _PYTEST_TIMINGS_FILENAME
        if artifact_dir is not None
        else None
    )


def _append_timing(timing: TestPhaseTiming | FixtureTiming, path: Path | None) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as output:
        output.write(json.dumps(asdict(timing), sort_keys=True))
        output.write("\n")
