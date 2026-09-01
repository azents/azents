"""Persistent Workspace-backed Pixi setup tests."""

import os
import shutil
from pathlib import Path

import pytest

from azents_runtime_runner.pixi import prepare_pixi_environment


@pytest.mark.parametrize(
    ("machine", "expected_platform"),
    (
        ("x86_64", "linux-64"),
        ("amd64", "linux-64"),
        ("aarch64", "linux-aarch64"),
        ("arm64", "linux-aarch64"),
    ),
)
def test_pixi_uses_runtime_workspace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    machine: str,
    expected_platform: str,
) -> None:
    workspace = tmp_path / "workspace"
    monkeypatch.setenv("PATH", "/usr/local/bin:/usr/bin:/usr/local/bin")

    environment = prepare_pixi_environment(
        workspace_path=str(workspace),
        machine=machine,
    )

    assert environment["PIXI_HOME"] == f"{workspace}/.pixi"
    assert environment["PIXI_CACHE_DIR"] == f"{workspace}/.cache/pixi"
    assert environment["PIXI_PLATFORM"] == expected_platform
    assert environment["PIXI_BASE_PATH"] == "/usr/local/bin:/usr/bin"
    assert environment["PATH"].split(os.pathsep) == [
        f"{workspace}/.pixi/bin",
        "/usr/local/bin",
        "/usr/bin",
    ]
    assert (workspace / ".pixi").is_dir()
    assert (workspace / ".cache/pixi").is_dir()


def test_pixi_preserves_existing_workspace_state_across_recreation(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    prepare_pixi_environment(workspace_path=str(workspace), machine="x86_64")
    installed = workspace / ".pixi/envs/installed"
    installed.parent.mkdir(parents=True)
    installed.write_text("installed")

    prepare_pixi_environment(workspace_path=str(workspace), machine="x86_64")

    assert installed.read_text() == "installed"


def test_workspace_reset_removes_pixi_state(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    prepare_pixi_environment(workspace_path=str(workspace), machine="x86_64")
    installed = workspace / ".pixi/envs/installed"
    installed.parent.mkdir(parents=True)
    installed.write_text("installed")
    shutil.rmtree(workspace)

    prepare_pixi_environment(workspace_path=str(workspace), machine="x86_64")

    assert not installed.exists()
    assert (workspace / ".pixi").is_dir()
    assert (workspace / ".cache/pixi").is_dir()


def test_pixi_rejects_unsupported_machine(tmp_path: Path) -> None:
    with pytest.raises(
        ValueError,
        match="Unsupported Pixi machine architecture: riscv64",
    ):
        prepare_pixi_environment(
            workspace_path=str(tmp_path / "workspace"),
            machine="riscv64",
        )
