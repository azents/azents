"""Private setup state and Docker Compose ingress boundary regressions."""

import json
import subprocess
from pathlib import Path
from unittest.mock import Mock

import pytest
from pydantic import ValidationError

from testenv.checks.base import RunContext, Status
from testenv.checks.infra import PostgresContainerHealthy, _decode_compose_statuses
from testenv.state import Finalizer, State, load_state


@pytest.mark.parametrize(
    "payload",
    [
        [],
        None,
        True,
        {"unknown": "extra"},
        {"_meta": []},
        {"_meta": {"run_id": None}},
        {"_meta": {"run_id": 3}},
        {"_meta": {"started_at": False}},
        {"_meta": {"unknown": "extra"}},
        {"run": []},
        {"run": False},
        {"tc": {"case": []}},
        {"tc": {"case": None}},
        {"_finalizers": {}},
        {"_finalizers": [None]},
        {"_finalizers": [{"cmd": 3}]},
        {"_finalizers": [{"scope": None}]},
        {"_finalizers": [{"unknown": "extra"}]},
        {"_verified_at": {"key": 3}},
        {"_verified_at": {"key": None}},
    ],
)
def test_state_rejects_malformed_structure_without_overwriting(
    tmp_path: Path, payload: object
) -> None:
    path = tmp_path / "state.json"
    encoded = json.dumps(payload)
    path.write_text(encoded)
    with pytest.raises((ValueError, ValidationError)):
        load_state(path)
    assert path.read_text() == encoded


@pytest.mark.parametrize("null_containers", [False, True])
def test_state_preserves_legacy_omissions(tmp_path: Path, null_containers: bool) -> None:
    path = tmp_path / "state.json"
    payload = (
        dict.fromkeys(["_meta", "run", "tc", "_finalizers", "_verified_at"])
        if null_containers
        else {}
    )
    path.write_text(json.dumps(payload))
    state = load_state(path)
    assert state.run_id == tmp_path.name
    assert state.started_at
    assert not state.run and not state.tc and not state.finalizers and not state.verified_at


def test_state_round_trip_preserves_private_seed_payload_and_finalizers(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    state = State(path, "fixture-agent-basic", "2026-10-13T00:00:00Z")
    state.set_run("user.email", "fixture@example.test")
    state.set_run("user.token", "private-fixture-token")
    state.set_run("opaque", [None, False, 0, {"arbitrary": "data"}])
    state.set_tc("case", "value", [])
    state.push_finalizer("setup", "echo clean", scope="tc")
    state.mark_verified("user.email", "2026-10-13T00:00:00Z")
    state.save()
    original = path.read_text()
    restored = load_state(path)
    assert restored.to_dict() == state.to_dict()
    assert restored.get_run("user.token") == "private-fixture-token"
    assert restored.get_tc("case", "value") == []
    assert restored.pop_all_finalizers() == state.finalizers
    restored.reload()
    assert restored.to_dict() == state.to_dict()
    restored.save()
    assert path.read_text() == original


def test_legacy_finalizer_omissions_keep_existing_defaults(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    path.write_text('{"_finalizers": [{}]}')
    assert load_state(path).finalizers == [Finalizer("?", "", "", "run")]


@pytest.mark.parametrize(
    "encoded",
    ['[{"State": "Running", "DockerExtra": 1}]', '{"State":"Running"}\n{"State":"exited"}'],
)
def test_compose_decodes_supported_wire_shapes(encoded: str) -> None:
    assert _decode_compose_statuses(encoded)[0].state == "Running"


@pytest.mark.parametrize(
    "encoded",
    [
        "null",
        "true",
        "3",
        '"running"',
        "[null]",
        '[{"State":null}]',
        '[{"State":false}]',
        '[{"State":3}]',
        '{"State":[]}',
        "{broken",
    ],
)
def test_compose_check_reports_malformed_ingress_as_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, encoded: str
) -> None:
    completed = subprocess.CompletedProcess(["docker"], 0, encoded, "")
    monkeypatch.setattr("testenv.checks.infra.subprocess.run", Mock(return_value=completed))
    context = RunContext(repo_root=tmp_path, azents_dir=tmp_path, env_file=tmp_path / ".env")
    result = PostgresContainerHealthy().run(context)
    assert result.status == Status.FAIL
    assert result.message == "failed to parse compose ps output: invalid container status"


@pytest.mark.parametrize(
    "encoded,expected",
    [
        ("[]", "db container not present"),
        ("{}", "db container state: unknown"),
        ('{"State":"exited"}', "db container state: exited"),
    ],
)
def test_compose_existing_unready_diagnostics(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, encoded: str, expected: str
) -> None:
    monkeypatch.setattr(
        "testenv.checks.infra.subprocess.run",
        Mock(return_value=subprocess.CompletedProcess(["docker"], 0, encoded, "")),
    )
    context = RunContext(repo_root=tmp_path, azents_dir=tmp_path, env_file=tmp_path / ".env")
    result = PostgresContainerHealthy().run(context)
    assert result.status == Status.FAIL
    assert result.message == expected
