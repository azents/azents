"""Workspace path policy tests."""

from pathlib import Path

from azents_runtime_runner.workspace import Workspace


def test_workspace_resolves_relative_paths(tmp_path: Path) -> None:
    workspace = Workspace(str(tmp_path / "agent"))

    assert workspace.resolve("report.txt") == tmp_path / "agent" / "report.txt"


def test_workspace_allows_absolute_paths_outside_default_root(tmp_path: Path) -> None:
    workspace = Workspace(str(tmp_path / "agent"))
    outside = tmp_path / "secret.txt"

    assert workspace.resolve(str(outside)) == outside
