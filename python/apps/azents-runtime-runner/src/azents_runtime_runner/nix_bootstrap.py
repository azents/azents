"""Release-owned persistent Nix bootstrap and Agent environment."""

import fcntl
import gzip
import hashlib
import json
import logging
import os
import re
import shutil
import stat
import subprocess
import tarfile
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Protocol, Self

_LOGGER = logging.getLogger(__name__)
_DEFAULT_SEED_ROOT = Path("/opt/azents/nix-seed")
_DEFAULT_NIX_ROOT = Path("/nix")
_MANIFEST_SCHEMA_VERSION = 1
_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_STORE_PATH_RE = re.compile(r"/nix/store/[0-9a-z]{32}-[^/]+")
_PROFILE_NAME = "azents-release"
_CATALOG_GC_ROOT_NAME = "nixpkgs"
_STATE_INITIALIZING = "initializing"
_STATE_RECONCILING = "reconciling"
_STATE_COMPLETE = "complete"


class NixBootstrapError(RuntimeError):
    """Raised when the release-owned Nix store cannot become ready."""


@dataclass(frozen=True)
class NixSeedArtifact:
    """One integrity-checked seed artifact."""

    path: str
    sha256: str


@dataclass(frozen=True)
class NixSeedManifest:
    """Validated release-owned Nix seed manifest."""

    generation: str
    nix_version: str
    nixpkgs_revision: str
    release_profile_store_path: str
    catalog_store_path: str
    empty_store: NixSeedArtifact
    release_export: NixSeedArtifact
    registry: NixSeedArtifact
    nix_conf: NixSeedArtifact

    @classmethod
    def load(cls, seed_root: Path) -> Self:
        """Load and validate one immutable image seed manifest."""
        manifest_path = seed_root / "manifest.json"
        try:
            raw = json.loads(manifest_path.read_text())
        except (OSError, json.JSONDecodeError) as error:
            raise NixBootstrapError("Nix seed manifest is unreadable.") from error
        if not isinstance(raw, dict) or raw.get("schema_version") != (
            _MANIFEST_SCHEMA_VERSION
        ):
            raise NixBootstrapError("Nix seed manifest schema is invalid.")
        artifacts = raw.get("artifacts")
        if not isinstance(artifacts, dict):
            raise NixBootstrapError("Nix seed artifact manifest is invalid.")
        return cls(
            generation=_required_text(raw, "generation"),
            nix_version=_required_text(raw, "nix_version"),
            nixpkgs_revision=_required_text(raw, "nixpkgs_revision"),
            release_profile_store_path=_store_path(
                raw,
                "release_profile_store_path",
            ),
            catalog_store_path=_store_path(raw, "catalog_store_path"),
            empty_store=_artifact(artifacts, "empty_store"),
            release_export=_artifact(artifacts, "release_export"),
            registry=_artifact(artifacts, "registry"),
            nix_conf=_artifact(artifacts, "nix_conf"),
        )


class NixCommandRunner(Protocol):
    """Nix command execution boundary used by bootstrap."""

    def import_archive(
        self,
        *,
        nix_store_executable: Path,
        archive: Path,
        environment: Mapping[str, str],
    ) -> None:
        """Import one compressed release closure into an existing store."""
        ...

    def validate_paths(
        self,
        *,
        nix_store_executable: Path,
        paths: Sequence[str],
        environment: Mapping[str, str],
    ) -> None:
        """Validate that release roots are registered in the current store."""
        ...


class SubprocessNixCommandRunner:
    """Run the native direct single-user Nix store commands."""

    def import_archive(
        self,
        *,
        nix_store_executable: Path,
        archive: Path,
        environment: Mapping[str, str],
    ) -> None:
        try:
            process = subprocess.Popen(
                [str(nix_store_executable), "--import"],
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=dict(environment),
            )
            if process.stdin is None:
                raise NixBootstrapError("Nix release import stdin is unavailable.")
            with gzip.open(archive, "rb") as source:
                shutil.copyfileobj(source, process.stdin)
            process.stdin.close()
            if process.wait() != 0:
                raise NixBootstrapError("Nix release import failed.")
        except OSError as error:
            raise NixBootstrapError("Nix release import failed.") from error

    def validate_paths(
        self,
        *,
        nix_store_executable: Path,
        paths: Sequence[str],
        environment: Mapping[str, str],
    ) -> None:
        nix_executable = nix_store_executable.with_name("nix")
        if not nix_executable.is_file():
            raise NixBootstrapError("Nix release executable is missing.")
        try:
            subprocess.run(
                [
                    str(nix_executable),
                    "store",
                    "verify",
                    "--recursive",
                    "--no-trust",
                    *paths,
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                check=True,
                env=dict(environment),
            )
        except (OSError, subprocess.CalledProcessError) as error:
            raise NixBootstrapError("Nix store validation failed.") from error


class NixBootstrapper:
    """Initialize or reconcile one Provider-owned Nix store."""

    def __init__(
        self,
        *,
        seed_root: Path,
        nix_root: Path,
        command_runner: NixCommandRunner,
    ) -> None:
        self.seed_root = seed_root
        self.nix_root = nix_root
        self.command_runner = command_runner

    def prepare(self) -> Mapping[str, str]:
        """Prepare the store before Runtime registration and return Agent env."""
        manifest = NixSeedManifest.load(self.seed_root)
        self._verify_artifacts(manifest)
        state_dir = self.nix_root / "var" / "azents"
        try:
            state_dir.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            raise NixBootstrapError("Nix store mount is not writable.") from error
        lock_path = state_dir / "bootstrap.lock"
        with lock_path.open("a+b") as lock_file:
            fcntl.flock(lock_file, fcntl.LOCK_EX)
            self._prepare_locked(manifest)
        return nix_agent_environment(self.nix_root)

    def _prepare_locked(self, manifest: NixSeedManifest) -> None:
        state = self._load_state()
        if state is not None and state.get("state") == _STATE_INITIALIZING:
            self._clear_interrupted_initialization()
            state = None
        if self._store_empty():
            self._initialize_empty_store(manifest)
            return
        current_nix_store = self._current_nix_store_executable()
        if current_nix_store is None:
            raise NixBootstrapError("Existing Nix store metadata is incomplete.")
        if (
            state is not None
            and state.get("state") == _STATE_COMPLETE
            and state.get("generation") == manifest.generation
        ):
            self._validate_release(manifest, current_nix_store)
            self._ensure_runtime_directories()
            _LOGGER.info(
                "Runtime Runner Nix seed already applied",
                extra={"nix_seed_generation": manifest.generation},
            )
            return
        self._reconcile_existing_store(manifest, current_nix_store, state)

    def _initialize_empty_store(self, manifest: NixSeedManifest) -> None:
        self._write_state(
            state=_STATE_INITIALIZING,
            generation=manifest.generation,
            previous_generation=None,
        )
        staging = self.nix_root / ".azents-bootstrap" / manifest.generation
        _remove_tree(staging)
        staging.mkdir(parents=True)
        archive = self._artifact_path(manifest.empty_store)
        try:
            with tarfile.open(archive, "r:gz") as seed:
                _validate_archive(seed)
                seed.extractall(staging, filter="fully_trusted")
        except (OSError, tarfile.TarError) as error:
            raise NixBootstrapError("Nix empty-store seed is invalid.") from error
        self._validate_staging(staging, manifest)
        self._install_staging(staging)
        nix_store = self._manifest_nix_store_executable(manifest)
        self._validate_release(manifest, nix_store)
        self._ensure_runtime_directories()
        self._write_state(
            state=_STATE_COMPLETE,
            generation=manifest.generation,
            previous_generation=None,
        )
        _remove_tree(self.nix_root / ".azents-bootstrap")
        _LOGGER.info(
            "Runtime Runner initialized Nix store",
            extra={"nix_seed_generation": manifest.generation},
        )

    def _reconcile_existing_store(
        self,
        manifest: NixSeedManifest,
        current_nix_store: Path,
        state: Mapping[str, object] | None,
    ) -> None:
        generation_value = state.get("generation") if state is not None else None
        previous_generation = (
            generation_value if isinstance(generation_value, str) else None
        )
        self._write_state(
            state=_STATE_RECONCILING,
            generation=manifest.generation,
            previous_generation=previous_generation,
        )
        self.command_runner.import_archive(
            nix_store_executable=current_nix_store,
            archive=self._artifact_path(manifest.release_export),
            environment=nix_command_environment(self.nix_root),
        )
        next_nix_store = self._manifest_nix_store_executable(manifest)
        self._validate_release(manifest, next_nix_store)
        self._copy_release_configuration(manifest)
        self._replace_release_roots(manifest)
        self._ensure_runtime_directories()
        self._write_state(
            state=_STATE_COMPLETE,
            generation=manifest.generation,
            previous_generation=previous_generation,
        )
        _LOGGER.info(
            "Runtime Runner reconciled Nix release seed",
            extra={
                "nix_seed_generation": manifest.generation,
                "nix_previous_seed_generation": previous_generation,
            },
        )

    def _validate_release(
        self,
        manifest: NixSeedManifest,
        nix_store_executable: Path,
    ) -> None:
        for store_path in (
            manifest.release_profile_store_path,
            manifest.catalog_store_path,
        ):
            if not self._physical_store_path(store_path).exists():
                raise NixBootstrapError("Nix release store path is missing.")
        self.command_runner.validate_paths(
            nix_store_executable=nix_store_executable,
            paths=(
                manifest.release_profile_store_path,
                manifest.catalog_store_path,
            ),
            environment=nix_command_environment(self.nix_root),
        )

    def _validate_staging(
        self,
        staging: Path,
        manifest: NixSeedManifest,
    ) -> None:
        for store_path in (
            manifest.release_profile_store_path,
            manifest.catalog_store_path,
        ):
            if not (staging / "store" / Path(store_path).name).exists():
                raise NixBootstrapError("Nix empty-store seed path is missing.")
        profile = staging / "var" / "nix" / "profiles" / _PROFILE_NAME
        catalog = staging / "var" / "nix" / "gcroots" / "azents" / _CATALOG_GC_ROOT_NAME
        if (
            not profile.is_symlink()
            or os.readlink(profile) != manifest.release_profile_store_path
            or not catalog.is_symlink()
            or os.readlink(catalog) != manifest.catalog_store_path
        ):
            raise NixBootstrapError("Nix empty-store release roots are invalid.")
        if not (staging / "var" / "nix" / "db" / "db.sqlite").is_file():
            raise NixBootstrapError("Nix empty-store database is missing.")

    def _install_staging(self, staging: Path) -> None:
        targets = (
            (staging / "store", self.nix_root / "store"),
            (staging / "var" / "nix", self.nix_root / "var" / "nix"),
            (staging / "etc" / "nix", self.nix_root / "etc" / "nix"),
        )
        for source, target in targets:
            if target.exists() or target.is_symlink():
                raise NixBootstrapError("Nix initialization target already exists.")
            target.parent.mkdir(parents=True, exist_ok=True)
            os.replace(source, target)
        registry_source = staging / "var" / "azents" / "registry.json"
        registry_target = self.nix_root / "var" / "azents" / "registry.json"
        _atomic_copy(registry_source, registry_target)

    def _copy_release_configuration(self, manifest: NixSeedManifest) -> None:
        _atomic_copy(
            self._artifact_path(manifest.nix_conf),
            self.nix_root / "etc" / "nix" / "nix.conf",
        )
        _atomic_copy(
            self._artifact_path(manifest.registry),
            self.nix_root / "var" / "azents" / "registry.json",
        )

    def _replace_release_roots(self, manifest: NixSeedManifest) -> None:
        _atomic_symlink(
            manifest.release_profile_store_path,
            self.nix_root / "var" / "nix" / "profiles" / _PROFILE_NAME,
        )
        _atomic_symlink(
            manifest.catalog_store_path,
            self.nix_root
            / "var"
            / "nix"
            / "gcroots"
            / "azents"
            / _CATALOG_GC_ROOT_NAME,
        )

    def _current_nix_store_executable(self) -> Path | None:
        profile = self.nix_root / "var" / "nix" / "profiles" / _PROFILE_NAME
        if not profile.is_symlink():
            return None
        target = os.readlink(profile)
        if _STORE_PATH_RE.fullmatch(target) is None:
            return None
        executable = self._physical_store_path(target) / "bin" / "nix-store"
        return executable if executable.is_file() else None

    def _manifest_nix_store_executable(
        self,
        manifest: NixSeedManifest,
    ) -> Path:
        executable = (
            self._physical_store_path(manifest.release_profile_store_path)
            / "bin"
            / "nix-store"
        )
        if not executable.is_file():
            raise NixBootstrapError("Nix release executable is missing.")
        return executable

    def _physical_store_path(self, logical_path: str) -> Path:
        return self.nix_root / "store" / Path(logical_path).name

    def _store_empty(self) -> bool:
        database = self.nix_root / "var" / "nix" / "db" / "db.sqlite"
        store = self.nix_root / "store"
        store_has_paths = store.exists() and any(store.iterdir())
        if database.exists() != store_has_paths:
            raise NixBootstrapError("Nix store and database state disagree.")
        return not database.exists()

    def _clear_interrupted_initialization(self) -> None:
        for path in (
            self.nix_root / "store",
            self.nix_root / "var" / "nix",
            self.nix_root / "etc" / "nix",
            self.nix_root / ".azents-bootstrap",
        ):
            _remove_tree(path)
        _LOGGER.warning("Runtime Runner retrying interrupted Nix initialization")

    def _ensure_runtime_directories(self) -> None:
        for path in (
            self.nix_root / "var" / "cache" / "azents-agent",
            self.nix_root / "var" / "config" / "azents-agent",
            self.nix_root / "var" / "log" / "nix",
            self.nix_root / "var" / "state" / "azents-agent",
            self.nix_root / "var" / "nix" / "profiles",
        ):
            path.mkdir(parents=True, exist_ok=True)

    def _verify_artifacts(self, manifest: NixSeedManifest) -> None:
        for artifact in (
            manifest.empty_store,
            manifest.release_export,
            manifest.registry,
            manifest.nix_conf,
        ):
            path = self._artifact_path(artifact)
            digest = hashlib.sha256()
            try:
                with path.open("rb") as source:
                    while chunk := source.read(1024 * 1024):
                        digest.update(chunk)
            except OSError as error:
                raise NixBootstrapError("Nix seed artifact is unreadable.") from error
            if digest.hexdigest() != artifact.sha256:
                raise NixBootstrapError("Nix seed artifact digest mismatch.")

    def _artifact_path(self, artifact: NixSeedArtifact) -> Path:
        return self.seed_root / artifact.path

    def _load_state(self) -> Mapping[str, object] | None:
        path = self.nix_root / "var" / "azents" / "bootstrap-state.json"
        if not path.exists():
            return None
        try:
            raw = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError) as error:
            raise NixBootstrapError("Nix bootstrap state is unreadable.") from error
        if not isinstance(raw, dict):
            raise NixBootstrapError("Nix bootstrap state is invalid.")
        return raw

    def _write_state(
        self,
        *,
        state: str,
        generation: str,
        previous_generation: str | None,
    ) -> None:
        path = self.nix_root / "var" / "azents" / "bootstrap-state.json"
        payload = {
            "schema_version": 1,
            "state": state,
            "generation": generation,
            "previous_generation": previous_generation,
        }
        _atomic_write(path, json.dumps(payload, sort_keys=True) + "\n")


def prepare_nix_runtime(
    *,
    seed_root: Path = _DEFAULT_SEED_ROOT,
    nix_root: Path = _DEFAULT_NIX_ROOT,
    command_runner: NixCommandRunner | None = None,
) -> Mapping[str, str]:
    """Prepare persistent Nix and return protected Agent shell variables."""
    return NixBootstrapper(
        seed_root=seed_root,
        nix_root=nix_root,
        command_runner=command_runner or SubprocessNixCommandRunner(),
    ).prepare()


def nix_command_environment(nix_root: Path) -> Mapping[str, str]:
    """Build the environment required by bootstrap Nix commands."""
    environment = dict(os.environ)
    environment.update(nix_agent_environment(nix_root))
    return environment


def nix_agent_environment(nix_root: Path) -> Mapping[str, str]:
    """Build the default persistent Nix environment for Agent commands."""
    profile_root = nix_root / "var" / "nix" / "profiles"
    agent_config = nix_root / "var" / "config" / "azents-agent"
    agent_state = nix_root / "var" / "state" / "azents-agent"
    agent_profile = agent_state / "profiles" / "profile"
    release_profile = profile_root / _PROFILE_NAME
    path = os.environ.get("PATH", "")
    path_parts = (
        str(agent_profile / "bin"),
        str(release_profile / "bin"),
        *(part for part in path.split(os.pathsep) if part),
    )
    return {
        "NIX_STORE_DIR": str(nix_root / "store"),
        "NIX_STATE_DIR": str(nix_root / "var" / "nix"),
        "NIX_LOG_DIR": str(nix_root / "var" / "log" / "nix"),
        "NIX_CONF_DIR": str(nix_root / "etc" / "nix"),
        "NIX_CACHE_HOME": str(nix_root / "var" / "cache" / "azents-agent"),
        "NIX_CONFIG_HOME": str(agent_config),
        "NIX_PROFILE": str(agent_profile),
        "NIX_SSL_CERT_FILE": "/etc/ssl/certs/ca-certificates.crt",
        "NIX_STATE_HOME": str(agent_state),
        "PATH": os.pathsep.join(dict.fromkeys(path_parts)),
    }


def _required_text(values: Mapping[str, object], key: str) -> str:
    value = values.get(key)
    if not isinstance(value, str) or not value:
        raise NixBootstrapError(f"Nix seed manifest field is invalid: {key}.")
    return value


def _store_path(values: Mapping[str, object], key: str) -> str:
    value = _required_text(values, key)
    if _STORE_PATH_RE.fullmatch(value) is None:
        raise NixBootstrapError(f"Nix seed store path is invalid: {key}.")
    return value


def _artifact(
    artifacts: Mapping[str, object],
    key: str,
) -> NixSeedArtifact:
    raw = artifacts.get(key)
    if not isinstance(raw, dict):
        raise NixBootstrapError(f"Nix seed artifact is invalid: {key}.")
    path = _required_text(raw, "path")
    if path in {".", ".."} or PurePosixPath(path).name != path:
        raise NixBootstrapError(f"Nix seed artifact path is invalid: {key}.")
    sha256 = _required_text(raw, "sha256")
    if _SHA256_RE.fullmatch(sha256) is None:
        raise NixBootstrapError(f"Nix seed artifact digest is invalid: {key}.")
    return NixSeedArtifact(path=path, sha256=sha256)


def _validate_archive(archive: tarfile.TarFile) -> None:
    allowed_roots = {"etc", "store", "var"}
    for member in archive.getmembers():
        path = PurePosixPath(member.name)
        if (
            path.is_absolute()
            or ".." in path.parts
            or not path.parts
            or path.parts[0] not in allowed_roots
            or member.isdev()
            or member.isfifo()
        ):
            raise NixBootstrapError("Nix empty-store archive member is invalid.")


def _atomic_copy(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as temporary:
        temp_path = Path(temporary.name)
        with source.open("rb") as content:
            shutil.copyfileobj(content, temporary)
    os.replace(temp_path, target)


def _atomic_symlink(target: str, link: Path) -> None:
    link.parent.mkdir(parents=True, exist_ok=True)
    temporary = link.with_name(f".{link.name}.{os.getpid()}.tmp")
    temporary.unlink(missing_ok=True)
    temporary.symlink_to(target)
    os.replace(temporary, link)


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        dir=path.parent,
        delete=False,
    ) as temporary:
        temporary.write(content)
        temp_path = Path(temporary.name)
    os.replace(temp_path, path)


def _remove_tree(path: Path) -> None:
    if not path.exists() and not path.is_symlink():
        return
    if path.is_symlink() or path.is_file():
        path.unlink()
        return
    for root, directories, files in os.walk(path):
        os.chmod(root, stat.S_IRWXU)
        for name in directories:
            directory = Path(root) / name
            if not directory.is_symlink():
                directory.chmod(stat.S_IRWXU)
        for name in files:
            file_path = Path(root) / name
            if not file_path.is_symlink():
                file_path.chmod(stat.S_IRUSR | stat.S_IWUSR)
    shutil.rmtree(path)
