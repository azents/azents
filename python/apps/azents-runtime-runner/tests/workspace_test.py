"""Workspace path policy tests."""

from pathlib import Path

import pytest

from azents_runtime_runner.workspace import FilesystemAccessPolicy, Workspace


def test_workspace_resolves_relative_paths(tmp_path: Path) -> None:
    workspace = Workspace(str(tmp_path / "agent"))

    assert workspace.resolve("report.txt") == tmp_path / "agent" / "report.txt"


def test_unrestricted_workspace_allows_absolute_paths_outside_default_root(
    tmp_path: Path,
) -> None:
    workspace = Workspace(str(tmp_path / "agent"))
    outside = tmp_path / "secret.txt"

    assert workspace.resolve(str(outside)) == outside


def test_contained_policy_maps_runtime_temporary_paths_to_backing_storage(
    tmp_path: Path,
) -> None:
    root = tmp_path / "agent"
    temporary = tmp_path / "agent-temporary"
    workspace = Workspace(
        str(root),
        access_policy=FilesystemAccessPolicy.contained(
            temporary_backing_path=temporary,
            read_only_paths=(Path("/usr"),),
            denied_paths=(tmp_path / "runner-private",),
        ),
    )

    resolved = workspace.resolve("/tmp/agent/imports/report.csv", write=True)

    assert resolved == temporary / "agent/imports/report.csv"
    assert workspace.display_path(resolved) == "/tmp/agent/imports/report.csv"


def test_contained_policy_distinguishes_read_only_and_writable_roots(
    tmp_path: Path,
) -> None:
    workspace = Workspace(
        str(tmp_path / "agent"),
        access_policy=FilesystemAccessPolicy.contained(
            temporary_backing_path=tmp_path / "agent-temporary",
            read_only_paths=(Path("/usr"),),
            denied_paths=(tmp_path / "runner-private",),
        ),
    )

    assert workspace.resolve("/usr/bin", write=False) == Path("/usr/bin").resolve()
    with pytest.raises(ValueError, match="not permitted"):
        workspace.resolve("/usr/bin", write=True)
    with pytest.raises(ValueError, match="not permitted"):
        workspace.resolve("/opt/azents-outside.txt", write=False)


def test_contained_policy_rejects_symlink_escape_to_runner_private_path(
    tmp_path: Path,
) -> None:
    root = tmp_path / "agent"
    private = tmp_path / "runner-private"
    private.mkdir()
    (private / "credential").write_text("secret")
    root.mkdir()
    link = root / "private-link"
    link.symlink_to(private, target_is_directory=True)
    workspace = Workspace(
        str(root),
        access_policy=FilesystemAccessPolicy.contained(
            temporary_backing_path=tmp_path / "agent-temporary",
            read_only_paths=(Path("/usr"),),
            denied_paths=(private,),
        ),
    )

    with pytest.raises(ValueError, match="not permitted"):
        workspace.resolve(str(link / "credential"), write=False)

    assert workspace.resolve_lexical(str(link), write=True) == link
