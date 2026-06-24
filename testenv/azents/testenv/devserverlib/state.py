"""Read and write `devserver.state.json`.

The state file stores session metadata as JSON so status checks and stale-state
cleanup can inspect the running devserver.
"""

import json
import uuid
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from testenv.fixture_manifest import WorktreeFingerprint

from .paths import STATE_FILE


class DevserverFixtureState(BaseModel):
    """Devserver state schema used by fixture providers."""

    model_config = ConfigDict(extra="ignore")

    schema_version: int
    session_name: str
    started_at: str
    command: list[str]
    cwd: str
    reload: bool
    public_port: int
    admin_port: int
    repo_root: str
    head_sha: str
    worktree_fingerprint: WorktreeFingerprint
    started_by: str


def write_state(data: dict[str, object], state_file: Path | None = None) -> None:
    """Create or replace state.json atomically."""
    target = _resolve_state_file(state_file)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
    tmp_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp_path.replace(target)


def read_state_raw(state_file: Path | None = None) -> dict[str, object] | None:
    """Read state.json without swallowing parse errors.

    Returns ``None`` when the file is missing. Invalid JSON and non-object roots
    are raised to the caller.
    """
    target = _resolve_state_file(state_file)
    if not target.is_file():
        return None
    raw = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        msg = "devserver state JSON root must be an object"
        raise ValueError(msg)
    return raw


def read_state(state_file: Path | None = None) -> dict[str, object] | None:
    """Read state.json and return None for invalid or unreadable state."""
    try:
        return read_state_raw(state_file)
    except json.JSONDecodeError:
        return None
    except OSError:
        return None
    except ValueError:
        return None


def validate_state_for_fixture(raw: dict[str, object]) -> DevserverFixtureState:
    """Validate typed state used by fixture providers."""
    return DevserverFixtureState.model_validate(raw)


def clear_state(state_file: Path | None = None) -> None:
    """state.json delete."""
    target = _resolve_state_file(state_file)
    if target.is_file():
        target.unlink()


def _resolve_state_file(state_file: Path | None) -> Path:
    """Return the override path or the default state file path."""
    return state_file if state_file is not None else STATE_FILE
