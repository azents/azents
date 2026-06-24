"""Tests for devserver state helpers."""

import json
from pathlib import Path
from typing import Protocol, cast

import pytest
from pydantic import ValidationError

import devserver
import testenv.devserverlib.state as devserver_state
from testenv.devserverlib.state import read_state_raw, validate_state_for_fixture
from testenv.fixture_manifest import WorktreeFingerprint


class _StartDevserver(Protocol):
    """Create private startup data for tests."""

    def __call__(self, env: dict[str, str], *, reload: bool) -> None: ...


def test_devserver_state_writer_includes_worktree_fingerprint(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Devserver state writer includes worktree ownership fields."""
    state_dir = tmp_path / ".state"
    state_file = state_dir / "devserver.state.json"
    log_file = state_dir / "devserver.log"

    monkeypatch.setattr(devserver, "STATE_DIR", state_dir)
    monkeypatch.setattr(devserver, "LOG_FILE", log_file)
    monkeypatch.setattr(devserver_state, "STATE_FILE", state_file)
    monkeypatch.setattr(devserver.tmux, "new_session", lambda **_: None)
    monkeypatch.setattr(devserver.tmux, "pipe_pane_to_file", lambda *_: None)
    monkeypatch.setattr(
        devserver,
        "current_worktree_fingerprint",
        lambda _: WorktreeFingerprint(
            repo_root=str(tmp_path.parent),
            head_sha="abcdef1",
            dirty_hash="sha256:dirty",
            env_hash="sha256:env",
            fingerprint="sha256:fingerprint",
        ),
    )

    start_devserver = cast(_StartDevserver, devserver.__dict__["_start_devserver"])
    start_devserver(
        {"AZ_PUBLIC_API_PORT": "8010", "AZ_ADMIN_API_PORT": "8011"},
        reload=False,
    )

    raw = json.loads(state_file.read_text(encoding="utf-8"))
    assert raw["schema_version"] == 1
    assert raw["started_by"] == "devserver.py up"
    assert raw["worktree_fingerprint"]["fingerprint"] == "sha256:fingerprint"


def test_legacy_devserver_state_without_fingerprint_is_stale(tmp_path: Path) -> None:
    """Legacy state is rejected by fixture validation."""
    state_file = tmp_path / "devserver.state.json"
    state_file.write_text(
        json.dumps(
            {
                "session_name": "azents-testenv-devserver",
                "started_at": "2026-05-12T09:00:00+00:00",
                "command": ["uv", "run"],
                "cwd": "/repo/python/apps/azents",
                "reload": False,
                "public_port": 8010,
                "admin_port": 8011,
            }
        ),
        encoding="utf-8",
    )

    raw = read_state_raw(state_file)
    assert raw is not None

    with pytest.raises(ValidationError):
        validate_state_for_fixture(raw)
