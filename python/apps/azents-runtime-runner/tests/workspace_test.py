"""Workspace path policy tests."""

from pathlib import Path

import pytest

from azents_runtime_runner.workspace import Workspace


def test_workspace_resolves_relative_paths(tmp_path: Path) -> None:
    workspace = Workspace(str(tmp_path / "agent"))

    assert workspace.resolve("report.txt") == tmp_path / "agent" / "report.txt"


def test_workspace_allows_absolute_paths_outside_default_root(tmp_path: Path) -> None:
    workspace = Workspace(str(tmp_path / "agent"))
    outside = tmp_path / "secret.txt"

    assert workspace.resolve(str(outside)) == outside


def test_workspace_blocks_protected_staging_through_direct_and_symlink_paths(
    tmp_path: Path,
) -> None:
    workspace_root = tmp_path / "agent"
    staging = tmp_path / "transfer-staging"
    staging.mkdir()
    alias = tmp_path / "staging-alias"
    alias.symlink_to(staging, target_is_directory=True)
    workspace = Workspace(str(workspace_root), blocked_paths=(staging,))

    for path in (staging / "attempt", alias / "attempt"):
        with pytest.raises(ValueError, match="reserved for Runtime transfer staging"):
            workspace.resolve_lexical(str(path))
