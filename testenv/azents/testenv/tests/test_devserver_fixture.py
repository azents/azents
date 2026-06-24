"""Tests for the devserver fixture provider."""

import datetime as dt
import json
from pathlib import Path

import pytest

from testenv.fixture_manifest import WorktreeFingerprint, load_fixture_manifest
from testenv.fixture_resources import DevserverFixtureProvider, FixtureContext


def _write_state(testenv_root: Path, *, fingerprint: str = "sha256:current") -> None:
    """Create devserver state for fixture tests."""
    state_path = testenv_root / ".state" / "devserver.state.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "session_name": "azents-testenv-devserver",
                "started_at": "2026-05-12T09:00:00+00:00",
                "command": ["uv", "run", "python", "src/cli/devserver.py"],
                "cwd": "/repo/python/apps/azents",
                "reload": False,
                "public_port": 8010,
                "admin_port": 8011,
                "repo_root": str(testenv_root.parent.parent),
                "head_sha": "abcdef1",
                "worktree_fingerprint": {
                    "repo_root": str(testenv_root.parent.parent),
                    "head_sha": "abcdef1",
                    "dirty_hash": "sha256:dirty",
                    "env_hash": "sha256:env",
                    "fingerprint": fingerprint,
                },
                "started_by": "devserver.py up",
            }
        ),
        encoding="utf-8",
    )


def _ctx(testenv_root: Path) -> FixtureContext:
    """Create a fixed fixture context for tests."""
    return FixtureContext(
        testenv_root=testenv_root,
        now=dt.datetime(2026, 5, 12, 9, 5, tzinfo=dt.UTC),
    )


def _current_worktree(
    tmp_path: Path,
    *,
    fingerprint: str = "sha256:current",
) -> WorktreeFingerprint:
    """Create the current worktree fingerprint used by tests."""
    return WorktreeFingerprint(
        repo_root=str(tmp_path.parent.parent),
        head_sha="abcdef1",
        dirty_hash="sha256:dirty",
        env_hash="sha256:env",
        fingerprint=fingerprint,
    )


def test_fixture_up_devserver_saves_ready_manifest_when_state_and_health_match(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Healthy same-worktree devserver saves a ready manifest."""
    provider = DevserverFixtureProvider()
    _write_state(tmp_path)
    monkeypatch.setattr(
        "testenv.fixture_resources.current_worktree_fingerprint",
        lambda _: _current_worktree(tmp_path),
    )
    monkeypatch.setattr("testenv.fixture_resources.tmux.has_session", lambda _: True)
    monkeypatch.setattr("testenv.fixture_resources.probe_url", lambda _: True)

    result = provider.up(_ctx(tmp_path))

    assert result.status == "ready"
    manifest = load_fixture_manifest("devserver", tmp_path)
    assert manifest.provides["devserver.public_url"] == "http://localhost:8010"
    assert manifest.doctor is not None
    assert manifest.doctor.last_result == "pass"


def test_fixture_up_overwrites_mismatched_manifest_when_runtime_matches_current_worktree(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """up refreshes a stale manifest to match current runtime."""
    provider = DevserverFixtureProvider()
    _write_state(tmp_path)
    current = _current_worktree(tmp_path)
    other = current.model_copy(update={"fingerprint": "sha256:other"})
    manifest_path = tmp_path / ".state" / "fixtures" / "devserver.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "fixture_id": "devserver",
                "status": "ready",
                "created_at": "2026-05-12T08:00:00Z",
                "updated_at": "2026-05-12T08:00:00Z",
                "worktree": other.model_dump(mode="json"),
                "resources": {
                    "devserver": {
                        "session_name": "azents-testenv-devserver",
                        "public_port": 8010,
                        "admin_port": 8011,
                        "public_url": "http://localhost:8010",
                        "admin_url": "http://localhost:8011",
                        "state_path": str(tmp_path / ".state" / "devserver.state.json"),
                        "started_at": "2026-05-12T08:00:00Z",
                        "reload": False,
                    }
                },
                "provides": {
                    "devserver.public_url": "http://localhost:8010",
                    "devserver.admin_url": "http://localhost:8011",
                    "devserver.session_name": "azents-testenv-devserver",
                },
                "doctor": None,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "testenv.fixture_resources.current_worktree_fingerprint",
        lambda _: current,
    )
    monkeypatch.setattr("testenv.fixture_resources.tmux.has_session", lambda _: True)
    monkeypatch.setattr("testenv.fixture_resources.probe_url", lambda _: True)

    result = provider.up(_ctx(tmp_path))

    assert result.status == "ready"
    manifest = load_fixture_manifest("devserver", tmp_path)
    assert manifest.worktree.fingerprint == current.fingerprint


def test_fixture_up_devserver_missing_state_returns_fixture_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Missing state file makes up return stale status with guidance."""
    provider = DevserverFixtureProvider()
    monkeypatch.setattr("testenv.fixture_resources.tmux.has_session", lambda _: False)
    monkeypatch.setattr("testenv.fixture_resources.probe_url", lambda _: False)
    monkeypatch.setattr(
        "testenv.fixture_resources.current_worktree_fingerprint",
        lambda _: _current_worktree(tmp_path),
    )

    result = provider.up(_ctx(tmp_path))

    assert result.status == "error"
    assert result.error_code == "FIXTURE_DEVSERVER_STATE_MISSING"
    assert result.guidance is not None


def test_fixture_doctor_missing_manifest_reports_stale_with_up_guidance(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Missing manifest makes healthy runtime report stale."""
    provider = DevserverFixtureProvider()
    _write_state(tmp_path)
    monkeypatch.setattr("testenv.fixture_resources.tmux.has_session", lambda _: True)
    monkeypatch.setattr("testenv.fixture_resources.probe_url", lambda _: True)
    monkeypatch.setattr(
        "testenv.fixture_resources.current_worktree_fingerprint",
        lambda _: _current_worktree(tmp_path),
    )

    result = provider.doctor(_ctx(tmp_path))

    assert result.status == "stale"
    assert result.guidance is not None
    assert result.manifest is None


def test_fixture_doctor_worktree_mismatch_returns_fixture_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Current worktree mismatch with state fingerprint fails."""
    provider = DevserverFixtureProvider()
    _write_state(tmp_path, fingerprint="sha256:other")
    monkeypatch.setattr("testenv.fixture_resources.tmux.has_session", lambda _: True)
    monkeypatch.setattr("testenv.fixture_resources.probe_url", lambda _: True)
    monkeypatch.setattr(
        "testenv.fixture_resources.current_worktree_fingerprint",
        lambda _: _current_worktree(tmp_path),
    )

    result = provider.doctor(_ctx(tmp_path))

    assert result.status == "error"
    assert result.error_code == "FIXTURE_WORKTREE_MISMATCH"


def test_fixture_doctor_unhealthy_public_or_admin_returns_fixture_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Readiness failure reports unhealthy status."""
    provider = DevserverFixtureProvider()
    _write_state(tmp_path)
    monkeypatch.setattr("testenv.fixture_resources.tmux.has_session", lambda _: True)
    monkeypatch.setattr(
        "testenv.fixture_resources.current_worktree_fingerprint",
        lambda _: _current_worktree(tmp_path),
    )
    health = iter([True, False])
    monkeypatch.setattr("testenv.fixture_resources.probe_url", lambda _: next(health))

    result = provider.doctor(_ctx(tmp_path))

    assert result.status == "error"
    assert result.error_code == "FIXTURE_DEVSERVER_UNHEALTHY"


def test_fixture_doctor_updates_doctor_summary_when_manifest_valid(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """doctor updates doctor summary on a valid manifest."""
    provider = DevserverFixtureProvider()
    _write_state(tmp_path)
    monkeypatch.setattr("testenv.fixture_resources.tmux.has_session", lambda _: True)
    monkeypatch.setattr("testenv.fixture_resources.probe_url", lambda _: True)
    monkeypatch.setattr(
        "testenv.fixture_resources.current_worktree_fingerprint",
        lambda _: _current_worktree(tmp_path),
    )
    provider.up(_ctx(tmp_path))

    result = provider.doctor(_ctx(tmp_path))

    assert result.manifest is not None
    assert result.manifest.doctor is not None
    assert result.manifest.doctor.last_result == "pass"


def test_fixture_reset_deletes_manifest_without_stopping_devserver(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """reset removes manifest without stopping runtime."""
    provider = DevserverFixtureProvider()
    _write_state(tmp_path)
    monkeypatch.setattr("testenv.fixture_resources.tmux.has_session", lambda _: True)
    monkeypatch.setattr("testenv.fixture_resources.probe_url", lambda _: True)
    monkeypatch.setattr(
        "testenv.fixture_resources.current_worktree_fingerprint",
        lambda _: _current_worktree(tmp_path),
    )
    provider.up(_ctx(tmp_path))

    result = provider.reset(_ctx(tmp_path))

    assert result.status == "ready"
    assert (tmp_path / ".state" / "fixtures" / "devserver.json").exists() is False


def test_manifest_does_not_contain_secret_values(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Provider saves manifests through secret validation."""
    provider = DevserverFixtureProvider()
    _write_state(tmp_path)
    monkeypatch.setattr("testenv.fixture_resources.tmux.has_session", lambda _: True)
    monkeypatch.setattr("testenv.fixture_resources.probe_url", lambda _: True)
    monkeypatch.setattr(
        "testenv.fixture_resources.current_worktree_fingerprint",
        lambda _: _current_worktree(tmp_path),
    )

    provider.up(_ctx(tmp_path))
    manifest = load_fixture_manifest("devserver", tmp_path)

    assert manifest.resources["devserver"] is not None
