"""Persistent home-backed Nix setup tests."""

import os
import shutil
from pathlib import Path

from azents_runtime_runner.nix import prepare_nix_environment


def test_nix_uses_runtime_home_storage(tmp_path: Path) -> None:
    home = tmp_path / "home"

    environment = prepare_nix_environment(
        workspace_path=str(home),
    )

    assert environment["NIX_STORE_DIR"] == f"{home}/.nix/store"
    assert environment["NIX_STATE_DIR"] == f"{home}/.nix/var/nix"
    assert environment["NIX_CONF_DIR"] == f"{home}/.nix/etc/nix"
    assert environment["NIX_PROFILE"] == (f"{home}/.local/state/nix/profiles/profile")
    assert environment["PATH"].split(os.pathsep)[0] == (
        f"{home}/.local/state/nix/profiles/profile/bin"
    )
    assert (
        "experimental-features = nix-command flakes"
        in (home / ".nix/etc/nix/nix.conf").read_text()
    )


def test_nix_preserves_existing_home_state_across_recreation(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    prepare_nix_environment(workspace_path=str(home))
    installed = home / ".nix/store/installed"
    installed.parent.mkdir(parents=True)
    installed.write_text("installed")

    prepare_nix_environment(workspace_path=str(home))

    assert installed.read_text() == "installed"


def test_workspace_reset_removes_nix_state(tmp_path: Path) -> None:
    home = tmp_path / "home"
    prepare_nix_environment(workspace_path=str(home))
    installed = home / ".nix/store/installed"
    installed.parent.mkdir(parents=True)
    installed.write_text("installed")
    shutil.rmtree(home)

    prepare_nix_environment(workspace_path=str(home))

    assert not installed.exists()
    assert (home / ".nix/etc/nix/nix.conf").exists()
