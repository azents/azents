"""Persistent Nix bootstrap and Agent environment tests."""

import hashlib
import json
import os
import tarfile
from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest

from azents_runtime_runner.execution import DirectExecutionBackend
from azents_runtime_runner.nix_bootstrap import (
    NixBootstrapError,
    NixBootstrapper,
    NixCommandRunner,
    SubprocessNixCommandRunner,
    nix_agent_environment,
)

_RELEASE_1 = "/nix/store/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa-release-1"
_CATALOG_1 = "/nix/store/bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb-source"
_RELEASE_2 = "/nix/store/cccccccccccccccccccccccccccccccc-release-2"
_CATALOG_2 = "/nix/store/dddddddddddddddddddddddddddddddd-source"


class FakeNixCommandRunner(NixCommandRunner):
    """Record native Nix operations and optionally realize imported paths."""

    def __init__(
        self,
        *,
        nix_root: Path,
        imported_paths: tuple[str, str] | None = None,
        fail_validation_for: Path | None = None,
    ) -> None:
        self.nix_root = nix_root
        self.imported_paths = imported_paths
        self.fail_validation_for = fail_validation_for
        self.imports: list[Path] = []
        self.validations: list[tuple[Path, tuple[str, ...]]] = []

    def import_archive(
        self,
        *,
        nix_store_executable: Path,
        archive: Path,
        environment: Mapping[str, str],
    ) -> None:
        del nix_store_executable, environment
        self.imports.append(archive)
        if self.imported_paths is not None:
            _create_store_paths(self.nix_root, *self.imported_paths)

    def validate_paths(
        self,
        *,
        nix_store_executable: Path,
        paths: Sequence[str],
        environment: Mapping[str, str],
    ) -> None:
        del environment
        self.validations.append((nix_store_executable, tuple(paths)))
        if nix_store_executable == self.fail_validation_for:
            raise NixBootstrapError("Nix store validation failed.")


def test_subprocess_validation_verifies_recursive_store_contents(
    tmp_path: Path,
) -> None:
    release_bin = tmp_path / "release" / "bin"
    release_bin.mkdir(parents=True)
    nix_store = release_bin / "nix-store"
    nix_store.write_text("")
    record = tmp_path / "arguments"
    nix = release_bin / "nix"
    nix.write_text('#!/bin/sh\nprintf "%s\\n" "$@" > "$RECORD_PATH"\n')
    nix.chmod(0o755)

    SubprocessNixCommandRunner().validate_paths(
        nix_store_executable=nix_store,
        paths=(_RELEASE_1, _CATALOG_1),
        environment={"RECORD_PATH": str(record)},
    )

    assert record.read_text().splitlines() == [
        "store",
        "verify",
        "--recursive",
        "--no-trust",
        _RELEASE_1,
        _CATALOG_1,
    ]


def test_subprocess_validation_rejects_corrupt_store_contents(
    tmp_path: Path,
) -> None:
    release_bin = tmp_path / "release" / "bin"
    release_bin.mkdir(parents=True)
    nix_store = release_bin / "nix-store"
    nix_store.write_text("")
    nix = release_bin / "nix"
    nix.write_text("#!/bin/sh\nexit 1\n")
    nix.chmod(0o755)

    with pytest.raises(NixBootstrapError, match="validation failed"):
        SubprocessNixCommandRunner().validate_paths(
            nix_store_executable=nix_store,
            paths=(_RELEASE_1, _CATALOG_1),
            environment={},
        )


def test_empty_store_initialization_is_complete_before_environment_exposure(
    tmp_path: Path,
) -> None:
    seed_root = _create_seed(
        tmp_path / "seed",
        generation="generation-1",
        release_path=_RELEASE_1,
        catalog_path=_CATALOG_1,
    )
    nix_root = tmp_path / "nix"
    commands = FakeNixCommandRunner(nix_root=nix_root)

    environment = NixBootstrapper(
        seed_root=seed_root,
        nix_root=nix_root,
        command_runner=commands,
    ).prepare()

    state = json.loads(
        (nix_root / "var" / "azents" / "bootstrap-state.json").read_text()
    )
    assert state == {
        "generation": "generation-1",
        "previous_generation": None,
        "schema_version": 1,
        "state": "complete",
    }
    assert (
        os.readlink(nix_root / "var" / "nix" / "profiles" / "azents-release")
        == _RELEASE_1
    )
    assert (
        os.readlink(nix_root / "var" / "nix" / "gcroots" / "azents" / "nixpkgs")
        == _CATALOG_1
    )
    assert commands.imports == []
    assert commands.validations == [
        (
            nix_root / "store" / Path(_RELEASE_1).name / "bin" / "nix-store",
            (_RELEASE_1, _CATALOG_1),
        )
    ]
    assert environment["NIX_PROFILE"] == (
        f"{nix_root}/var/state/azents-agent/profiles/profile"
    )
    assert environment["PATH"].split(os.pathsep)[:2] == [
        f"{nix_root}/var/state/azents-agent/profiles/profile/bin",
        f"{nix_root}/var/nix/profiles/azents-release/bin",
    ]
    assert not (nix_root / ".azents-bootstrap").exists()


def test_same_generation_is_validated_without_import(tmp_path: Path) -> None:
    seed_root = _create_seed(
        tmp_path / "seed",
        generation="generation-1",
        release_path=_RELEASE_1,
        catalog_path=_CATALOG_1,
    )
    nix_root = tmp_path / "nix"
    first_commands = FakeNixCommandRunner(nix_root=nix_root)
    bootstrapper = NixBootstrapper(
        seed_root=seed_root,
        nix_root=nix_root,
        command_runner=first_commands,
    )
    bootstrapper.prepare()
    second_commands = FakeNixCommandRunner(nix_root=nix_root)

    NixBootstrapper(
        seed_root=seed_root,
        nix_root=nix_root,
        command_runner=second_commands,
    ).prepare()

    assert second_commands.imports == []
    assert len(second_commands.validations) == 1


def test_existing_store_reconciliation_preserves_agent_installed_roots(
    tmp_path: Path,
) -> None:
    nix_root = tmp_path / "nix"
    first_seed = _create_seed(
        tmp_path / "seed-1",
        generation="generation-1",
        release_path=_RELEASE_1,
        catalog_path=_CATALOG_1,
    )
    NixBootstrapper(
        seed_root=first_seed,
        nix_root=nix_root,
        command_runner=FakeNixCommandRunner(nix_root=nix_root),
    ).prepare()
    installed = (
        nix_root / "store" / "eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee-agent-installed-tool"
    )
    installed.mkdir()
    agent_profile = nix_root / "var" / "state" / "azents-agent" / "profiles" / "profile"
    agent_profile.parent.mkdir(parents=True)
    agent_profile.symlink_to(
        "/nix/store/eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee-agent-installed-tool"
    )
    second_seed = _create_seed(
        tmp_path / "seed-2",
        generation="generation-2",
        release_path=_RELEASE_2,
        catalog_path=_CATALOG_2,
    )
    commands = FakeNixCommandRunner(
        nix_root=nix_root,
        imported_paths=(_RELEASE_2, _CATALOG_2),
    )

    NixBootstrapper(
        seed_root=second_seed,
        nix_root=nix_root,
        command_runner=commands,
    ).prepare()

    assert commands.imports == [second_seed / "release-export.nar.gz"]
    assert installed.is_dir()
    assert os.readlink(agent_profile).endswith("agent-installed-tool")
    assert (
        os.readlink(nix_root / "var" / "nix" / "profiles" / "azents-release")
        == _RELEASE_2
    )
    state = json.loads(
        (nix_root / "var" / "azents" / "bootstrap-state.json").read_text()
    )
    assert state["generation"] == "generation-2"
    assert state["previous_generation"] == "generation-1"
    assert state["state"] == "complete"


def test_interrupted_empty_initialization_is_retried(tmp_path: Path) -> None:
    seed_root = _create_seed(
        tmp_path / "seed",
        generation="generation-1",
        release_path=_RELEASE_1,
        catalog_path=_CATALOG_1,
    )
    nix_root = tmp_path / "nix"
    state_dir = nix_root / "var" / "azents"
    state_dir.mkdir(parents=True)
    (state_dir / "bootstrap-state.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "state": "initializing",
                "generation": "generation-1",
                "previous_generation": None,
            }
        )
    )
    partial = nix_root / "store" / "ffffffffffffffffffffffffffffffff-partial"
    partial.mkdir(parents=True)
    partial.chmod(0o500)

    NixBootstrapper(
        seed_root=seed_root,
        nix_root=nix_root,
        command_runner=FakeNixCommandRunner(nix_root=nix_root),
    ).prepare()

    assert not partial.exists()
    state = json.loads((state_dir / "bootstrap-state.json").read_text())
    assert state["state"] == "complete"


def test_seed_digest_failure_does_not_mutate_store(tmp_path: Path) -> None:
    seed_root = _create_seed(
        tmp_path / "seed",
        generation="generation-1",
        release_path=_RELEASE_1,
        catalog_path=_CATALOG_1,
    )
    (seed_root / "empty-store.tar.gz").write_bytes(b"corrupt")
    nix_root = tmp_path / "nix"

    with pytest.raises(NixBootstrapError, match="digest mismatch"):
        NixBootstrapper(
            seed_root=seed_root,
            nix_root=nix_root,
            command_runner=FakeNixCommandRunner(nix_root=nix_root),
        ).prepare()

    assert not nix_root.exists()


def test_manifest_rejects_parent_artifact_path_before_store_mutation(
    tmp_path: Path,
) -> None:
    seed_root = _create_seed(
        tmp_path / "seed",
        generation="generation-1",
        release_path=_RELEASE_1,
        catalog_path=_CATALOG_1,
    )
    manifest_path = seed_root / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["artifacts"]["empty_store"]["path"] = ".."
    manifest_path.write_text(json.dumps(manifest))
    nix_root = tmp_path / "nix"

    with pytest.raises(NixBootstrapError, match="artifact path is invalid"):
        NixBootstrapper(
            seed_root=seed_root,
            nix_root=nix_root,
            command_runner=FakeNixCommandRunner(nix_root=nix_root),
        ).prepare()

    assert not nix_root.exists()


def test_empty_store_archive_rejects_parent_traversal(tmp_path: Path) -> None:
    seed_root = _create_seed(
        tmp_path / "seed",
        generation="generation-1",
        release_path=_RELEASE_1,
        catalog_path=_CATALOG_1,
    )
    archive = seed_root / "empty-store.tar.gz"
    with tarfile.open(archive, "w:gz") as output:
        member = tarfile.TarInfo("../../outside")
        member.size = 0
        output.addfile(member)
    _update_artifact_digest(seed_root, "empty_store", archive)
    nix_root = tmp_path / "nix"

    with pytest.raises(NixBootstrapError, match="archive member is invalid"):
        NixBootstrapper(
            seed_root=seed_root,
            nix_root=nix_root,
            command_runner=FakeNixCommandRunner(nix_root=nix_root),
        ).prepare()

    assert not (tmp_path / "outside").exists()
    assert not (nix_root / "store").exists()


def test_existing_store_without_managed_release_profile_fails(tmp_path: Path) -> None:
    seed_root = _create_seed(
        tmp_path / "seed",
        generation="generation-1",
        release_path=_RELEASE_1,
        catalog_path=_CATALOG_1,
    )
    nix_root = tmp_path / "nix"
    (nix_root / "store" / Path(_RELEASE_1).name).mkdir(parents=True)
    database = nix_root / "var" / "nix" / "db" / "db.sqlite"
    database.parent.mkdir(parents=True)
    database.write_text("database")

    with pytest.raises(NixBootstrapError, match="metadata is incomplete"):
        NixBootstrapper(
            seed_root=seed_root,
            nix_root=nix_root,
            command_runner=FakeNixCommandRunner(nix_root=nix_root),
        ).prepare()


def test_reconciliation_validation_failure_preserves_current_release_roots(
    tmp_path: Path,
) -> None:
    nix_root = tmp_path / "nix"
    first_seed = _create_seed(
        tmp_path / "seed-1",
        generation="generation-1",
        release_path=_RELEASE_1,
        catalog_path=_CATALOG_1,
    )
    NixBootstrapper(
        seed_root=first_seed,
        nix_root=nix_root,
        command_runner=FakeNixCommandRunner(nix_root=nix_root),
    ).prepare()
    second_seed = _create_seed(
        tmp_path / "seed-2",
        generation="generation-2",
        release_path=_RELEASE_2,
        catalog_path=_CATALOG_2,
    )
    next_nix_store = nix_root / "store" / Path(_RELEASE_2).name / "bin" / "nix-store"

    with pytest.raises(NixBootstrapError, match="validation failed"):
        NixBootstrapper(
            seed_root=second_seed,
            nix_root=nix_root,
            command_runner=FakeNixCommandRunner(
                nix_root=nix_root,
                imported_paths=(_RELEASE_2, _CATALOG_2),
                fail_validation_for=next_nix_store,
            ),
        ).prepare()

    assert (
        os.readlink(nix_root / "var" / "nix" / "profiles" / "azents-release")
        == _RELEASE_1
    )
    assert (
        os.readlink(nix_root / "var" / "nix" / "gcroots" / "azents" / "nixpkgs")
        == _CATALOG_1
    )
    state = json.loads(
        (nix_root / "var" / "azents" / "bootstrap-state.json").read_text()
    )
    assert state["state"] == "reconciling"
    assert state["generation"] == "generation-2"
    assert state["previous_generation"] == "generation-1"


def test_agent_environment_keeps_state_outside_workspace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PATH", "/usr/local/bin:/usr/bin")
    nix_root = tmp_path / "nix"

    environment = nix_agent_environment(nix_root)

    assert all("/workspace" not in value for value in environment.values())
    assert environment["NIX_STORE_DIR"] == f"{nix_root}/store"
    assert environment["NIX_STATE_DIR"] == f"{nix_root}/var/nix"
    assert environment["NIX_CACHE_HOME"] == f"{nix_root}/var/cache/azents-agent"
    assert environment["NIX_CONFIG_HOME"] == f"{nix_root}/var/config/azents-agent"
    assert environment["NIX_STATE_HOME"] == f"{nix_root}/var/state/azents-agent"
    xdg_names = {"XDG_CACHE_HOME", "XDG_CONFIG_HOME", "XDG_STATE_HOME"}
    assert not xdg_names & environment.keys()
    assert environment["PATH"].endswith("/usr/local/bin:/usr/bin")


def test_agent_environment_cannot_be_overridden_by_one_operation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PATH", "/usr/local/bin:/usr/bin")
    protected = nix_agent_environment(tmp_path / "nix")
    backend = DirectExecutionBackend(inherited_environment=protected)

    environment = backend.agent_environment(
        workspace_path="/workspace/agent",
        operation_environment={
            "NIX_PROFILE": "/workspace/agent/bypass-profile",
            "NIX_CONF_DIR": "/workspace/agent/bypass-config",
            "NIX_CONFIG_HOME": "/workspace/agent/config",
            "PATH": "/workspace/agent/bin",
            "TOOL_TOKEN": "tool-token",
        },
    )

    assert environment["NIX_PROFILE"] == protected["NIX_PROFILE"]
    assert environment["NIX_CONF_DIR"] == protected["NIX_CONF_DIR"]
    assert environment["NIX_CONFIG_HOME"] == protected["NIX_CONFIG_HOME"]
    assert environment["PATH"] == protected["PATH"]
    assert environment["TOOL_TOKEN"] == "tool-token"


def _create_seed(
    seed_root: Path,
    *,
    generation: str,
    release_path: str,
    catalog_path: str,
) -> Path:
    seed_root.mkdir(parents=True)
    staging = seed_root / "staging"
    _create_store_paths(staging, release_path, catalog_path)
    database = staging / "var" / "nix" / "db" / "db.sqlite"
    database.parent.mkdir(parents=True)
    database.write_text("database")
    profile = staging / "var" / "nix" / "profiles" / "azents-release"
    profile.parent.mkdir(parents=True)
    profile.symlink_to(release_path)
    catalog_root = staging / "var" / "nix" / "gcroots" / "azents" / "nixpkgs"
    catalog_root.parent.mkdir(parents=True)
    catalog_root.symlink_to(catalog_path)
    nix_conf = "experimental-features = nix-command flakes\nmax-jobs = 0\n"
    registry = '{"flakes":[],"version":2}\n'
    (staging / "etc" / "nix").mkdir(parents=True)
    (staging / "etc" / "nix" / "nix.conf").write_text(nix_conf)
    (staging / "var" / "azents").mkdir(parents=True)
    (staging / "var" / "azents" / "registry.json").write_text(registry)
    archive = seed_root / "empty-store.tar.gz"
    with tarfile.open(archive, "w:gz") as output:
        for name in ("etc", "store", "var"):
            output.add(staging / name, arcname=name)
    (seed_root / "release-export.nar.gz").write_bytes(b"release-export")
    (seed_root / "registry.json").write_text(registry)
    (seed_root / "nix.conf").write_text(nix_conf)
    artifacts = {
        name: {
            "path": path.name,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
        for name, path in {
            "empty_store": archive,
            "release_export": seed_root / "release-export.nar.gz",
            "registry": seed_root / "registry.json",
            "nix_conf": seed_root / "nix.conf",
        }.items()
    }
    (seed_root / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "generation": generation,
                "nix_version": "2.35.2",
                "nixpkgs_revision": "1" * 40,
                "release_profile_store_path": release_path,
                "catalog_store_path": catalog_path,
                "artifacts": artifacts,
            }
        )
    )
    return seed_root


def _create_store_paths(
    nix_root: Path,
    release_path: str,
    catalog_path: str,
) -> None:
    release = nix_root / "store" / Path(release_path).name
    (release / "bin").mkdir(parents=True)
    for name in ("nix", "nix-store"):
        executable = release / "bin" / name
        executable.write_text("#!/bin/sh\nexit 0\n")
        executable.chmod(0o755)
    catalog = nix_root / "store" / Path(catalog_path).name
    catalog.mkdir(parents=True)
    (catalog / "flake.nix").write_text("{}\n")


def _update_artifact_digest(
    seed_root: Path,
    artifact_name: str,
    artifact_path: Path,
) -> None:
    manifest_path = seed_root / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["artifacts"][artifact_name]["sha256"] = hashlib.sha256(
        artifact_path.read_bytes()
    ).hexdigest()
    manifest_path.write_text(json.dumps(manifest))
