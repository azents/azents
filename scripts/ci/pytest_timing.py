"""Write safe, structured pytest timing evidence for E2E CI runs."""

import json
import os
import time
from collections.abc import Generator
from dataclasses import asdict, dataclass
from pathlib import Path

import pytest

_ARTIFACT_DIR_ENV = "AZENTS_E2E_ARTIFACT_DIR"
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


class TimingObservabilityPlugin:
    """Globally observe pytest phases, including session-scoped fixtures."""

    def __init__(self) -> None:
        self.fixture_teardown_states: dict[int, FixtureTeardownState] = {}

    def pytest_runtest_logreport(self, report: pytest.TestReport) -> None:
        """Record every test setup, call, and teardown phase."""
        if report.when is None:
            return
        record_test_phase(
            node_id=report.nodeid,
            phase=report.when,
            duration_seconds=report.duration,
            outcome=report.outcome,
        )

    @pytest.hookimpl(wrapper=True)
    def pytest_fixture_setup(
        self,
        fixturedef: pytest.FixtureDef[object],
        request: pytest.FixtureRequest,
    ) -> Generator[None, object, object]:
        """Measure one real fixture setup without serializing fixture values."""
        started_at = monotonic_time()
        try:
            result = yield
        except BaseException:
            record_fixture_phase(
                fixture=fixturedef.argname,
                scope=fixturedef.scope,
                node_id=request.node.nodeid,
                phase="setup",
                duration_seconds=monotonic_time() - started_at,
                outcome="failed",
            )
            raise

        record_fixture_phase(
            fixture=fixturedef.argname,
            scope=fixturedef.scope,
            node_id=request.node.nodeid,
            phase="setup",
            duration_seconds=monotonic_time() - started_at,
            outcome="passed",
        )
        teardown_state = FixtureTeardownState()
        self.fixture_teardown_states[id(fixturedef)] = teardown_state
        fixturedef.addfinalizer(
            lambda: setattr(teardown_state, "started_at", monotonic_time())
        )
        return result

    def pytest_fixture_post_finalizer(
        self,
        fixturedef: pytest.FixtureDef[object],
        request: pytest.FixtureRequest,
    ) -> None:
        """Record fixture teardown after its finalizers have completed."""
        teardown_state = self.fixture_teardown_states.get(id(fixturedef))
        if teardown_state is None or teardown_state.started_at is None:
            return
        record_fixture_phase(
            fixture=fixturedef.argname,
            scope=fixturedef.scope,
            node_id=request.node.nodeid,
            phase="teardown",
            duration_seconds=monotonic_time() - teardown_state.started_at,
            outcome="completed",
        )
        del self.fixture_teardown_states[id(fixturedef)]


def record_test_phase(
    *,
    node_id: str,
    phase: str,
    duration_seconds: float,
    outcome: str,
) -> None:
    """Append one test phase timing when artifact capture is enabled."""
    _append_timing(
        TestPhaseTiming(
            record_type="test_phase",
            node_id=node_id,
            phase=phase,
            duration_seconds=round(duration_seconds, 6),
            outcome=outcome,
        )
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
    """Append one fixture phase timing when artifact capture is enabled."""
    _append_timing(
        FixtureTiming(
            record_type="fixture",
            fixture=fixture,
            scope=scope,
            node_id=node_id,
            phase=phase,
            duration_seconds=round(duration_seconds, 6),
            outcome=outcome,
        )
    )


def monotonic_time() -> float:
    """Return a monotonic timestamp for hook-level duration measurement."""
    return time.monotonic()


def timing_path() -> Path | None:
    """Return the configured pytest timing artifact path."""
    artifact_dir = os.environ.get(_ARTIFACT_DIR_ENV)
    if artifact_dir is None:
        return None
    return Path(artifact_dir) / _PYTEST_TIMINGS_FILENAME


def _append_timing(timing: TestPhaseTiming | FixtureTiming) -> None:
    path = timing_path()
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as output:
        output.write(json.dumps(asdict(timing), sort_keys=True))
        output.write("\n")
