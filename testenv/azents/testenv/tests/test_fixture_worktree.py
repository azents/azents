"""Tests for fixture worktree fingerprinting."""

from pathlib import Path

import pytest

from testenv.fixture_manifest import WorktreeFingerprint
from testenv.fixture_worktree import current_worktree_fingerprint


def test_current_worktree_fingerprint_ignores_unrelated_dirty_files(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Dirty hash ignores fixture paths when checking git status."""
    calls: list[tuple[tuple[str, ...], Path]] = []

    def fake_run_git(args: tuple[str, ...], cwd: Path) -> str:
        calls.append((args, cwd))
        if args == ("rev-parse", "--show-toplevel"):
            return str(tmp_path.parent)
        if args == ("rev-parse", "HEAD"):
            return "abcdef1"
        if args[:3] == ("status", "--porcelain", "--"):
            return " M testenv/azents/testenv/cli.py"
        msg = f"unexpected git args: {args}"
        raise AssertionError(msg)

    monkeypatch.setattr("testenv.fixture_worktree._run_git", fake_run_git)

    fingerprint = current_worktree_fingerprint(tmp_path)

    assert isinstance(fingerprint, WorktreeFingerprint)
    assert fingerprint.head_sha == "abcdef1"
    assert calls[2][0] == (
        "status",
        "--porcelain",
        "--",
        "testenv/azents",
        "python/apps/azents",
        "docker/azents",
    )
