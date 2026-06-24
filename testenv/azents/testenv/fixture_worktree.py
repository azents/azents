"""Fixture worktree fingerprint helpers."""

import hashlib
import json
import os
import subprocess
from collections.abc import Mapping
from pathlib import Path

from dotenv import dotenv_values

from testenv.fixture_errors import FixtureError, FixtureErrorDetail
from testenv.fixture_manifest import WorktreeFingerprint

_AFFECTED_PATHS = (
    "testenv/azents",
    "python/apps/azents",
    "docker/azents",
)
_ENV_DEFAULTS = {
    "AZ_PUBLIC_API_PORT": "8010",
    "AZ_ADMIN_API_PORT": "8011",
}


def current_worktree_fingerprint(testenv_root: Path) -> WorktreeFingerprint:
    """Build a fingerprint for the worktree that owns this testenv root."""
    repo_root = Path(_run_git(("rev-parse", "--show-toplevel"), cwd=testenv_root)).resolve()
    head_sha = _run_git(("rev-parse", "HEAD"), cwd=testenv_root)
    env_hash = selected_env_hash(_selected_env_subset(testenv_root))
    dirty_hash = selected_dirty_hash(repo_root)
    fingerprint = _hash_payload(
        {
            "repo_root": str(repo_root),
            "head_sha": head_sha,
            "dirty_hash": dirty_hash,
            "env_hash": env_hash,
        }
    )
    return WorktreeFingerprint(
        repo_root=str(repo_root),
        head_sha=head_sha,
        dirty_hash=dirty_hash,
        env_hash=env_hash,
        fingerprint=fingerprint,
    )


def selected_env_hash(env: Mapping[str, str]) -> str:
    """Hash the non-secret environment subset used for fixture ownership."""
    normalized = {
        key: env.get(key, default_value) for key, default_value in sorted(_ENV_DEFAULTS.items())
    }
    return _hash_payload(normalized)


def selected_dirty_hash(repo_root: Path) -> str:
    """Hash git dirty state for paths that affect fixtures."""
    status_output = _run_git(
        ("status", "--porcelain", "--", *_AFFECTED_PATHS),
        cwd=repo_root,
    )
    return _hash_payload({"git_status": status_output})


def _selected_env_subset(testenv_root: Path) -> dict[str, str]:
    """Resolve fingerprint environment values from `.env` and process env."""
    env_path = testenv_root / ".env"
    file_values = dotenv_values(env_path) if env_path.is_file() else {}
    resolved: dict[str, str] = {}
    for key, default_value in sorted(_ENV_DEFAULTS.items()):
        file_value = file_values.get(key)
        resolved[key] = os.environ.get(
            key,
            file_value if isinstance(file_value, str) else default_value,
        )
    return resolved


def _run_git(args: tuple[str, ...], cwd: Path) -> str:
    """Run git and return stripped stdout."""
    command = ["git", *args]
    try:
        completed = subprocess.run(
            command,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError as exc:
        detail = FixtureErrorDetail(
            code="FIXTURE_WORKTREE_FINGERPRINT_ERROR",
            message=f"Failed to inspect current worktree: git {' '.join(args)}",
        )
        raise FixtureError(detail) from exc
    return completed.stdout.strip()


def _hash_payload(payload: object) -> str:
    """Return a SHA-256 fingerprint string for a JSON payload."""
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"
