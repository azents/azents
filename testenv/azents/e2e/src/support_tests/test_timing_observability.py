"""Unit tests for structured pytest timing evidence."""

import json
from pathlib import Path
from typing import Protocol

from support.timing_observability import (
    record_fixture_phase,
    record_test_phase,
    timing_path,
)


class _EnvironmentSetter(Protocol):
    def setenv(self, name: str, value: str) -> None: ...


def test_timing_records_contain_only_safe_metadata(
    tmp_path: Path,
    monkeypatch: _EnvironmentSetter,
) -> None:
    """Write test and fixture phase records without runtime values or logs."""
    monkeypatch.setenv("AZENTS_E2E_ARTIFACT_DIR", str(tmp_path))

    record_test_phase(
        node_id="src/tests/test_example.py::test_example",
        phase="call",
        duration_seconds=1.23456789,
        outcome="passed",
    )
    record_fixture_phase(
        fixture="service_container",
        scope="session",
        node_id="",
        phase="setup",
        duration_seconds=2.34567891,
        outcome="passed",
    )

    path = timing_path()
    assert path is not None
    records = [json.loads(line) for line in path.read_text().splitlines()]
    assert records == [
        {
            "duration_seconds": 1.234568,
            "node_id": "src/tests/test_example.py::test_example",
            "outcome": "passed",
            "phase": "call",
            "record_type": "test_phase",
        },
        {
            "duration_seconds": 2.345679,
            "fixture": "service_container",
            "node_id": "",
            "outcome": "passed",
            "phase": "setup",
            "record_type": "fixture",
            "scope": "session",
        },
    ]
