"""Fixture provider types and the devserver fixture provider."""

import datetime as dt
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

from pydantic import JsonValue, ValidationError

from testenv.devserverlib import tmux
from testenv.devserverlib.paths import SESSION_NAME
from testenv.devserverlib.readiness import probe_url
from testenv.devserverlib.state import (
    DevserverFixtureState,
    read_state_raw,
    validate_state_for_fixture,
)
from testenv.fixture_errors import (
    FixtureManifestNotFoundError,
    FixtureManifestReadError,
    FixtureManifestSchemaError,
    FixtureSecretValidationError,
)
from testenv.fixture_manifest import (
    FIXTURE_SCHEMA_VERSION,
    DoctorCheck,
    DoctorSummary,
    FixtureManifest,
    WorktreeFingerprint,
    delete_fixture_manifest,
    load_fixture_manifest,
    save_fixture_manifest,
)
from testenv.fixture_worktree import current_worktree_fingerprint

FixtureStatus = Literal["ready", "stale", "error"]


@dataclass(frozen=True)
class FixtureContext:
    """fixture command run context."""

    testenv_root: Path
    now: dt.datetime


@dataclass(frozen=True)
class FixtureCommandResult:
    """fixture command result."""

    fixture_id: str
    status: FixtureStatus
    checks: tuple[DoctorCheck, ...]
    manifest: FixtureManifest | None
    message: str
    guidance: str | None
    error_code: str | None = None

    def to_json_dict(self) -> dict[str, object]:
        """Return the CLI JSON output payload."""
        payload: dict[str, object] = {
            "fixture_id": self.fixture_id,
            "status": self.status,
            "message": self.message,
            "guidance": self.guidance,
            "error_code": self.error_code,
            "checks": [check.model_dump(mode="json") for check in self.checks],
        }
        if self.manifest is not None:
            payload["manifest"] = self.manifest.model_dump(mode="json")
        return payload


class FixtureProvider(Protocol):
    """fixture provider protocol."""

    id: str

    def up(self, ctx: FixtureContext) -> FixtureCommandResult: ...

    def doctor(self, ctx: FixtureContext) -> FixtureCommandResult: ...

    def reset(self, ctx: FixtureContext) -> FixtureCommandResult: ...


@dataclass(frozen=True)
class _DoctorSnapshot:
    """Snapshot of a devserver doctor run."""

    current_worktree: WorktreeFingerprint
    manifest: FixtureManifest | None
    state: DevserverFixtureState | None
    checks: tuple[DoctorCheck, ...]
    overall: Literal["pass", "fail", "stale"]
    error_code: str | None
    message: str
    guidance: str | None


class DevserverFixtureProvider:
    """Fixture provider that records and validates a running devserver."""

    id = "devserver"

    def up(self, ctx: FixtureContext) -> FixtureCommandResult:
        """Save a ready manifest for the currently running devserver."""
        runtime = self._doctor_snapshot(ctx, include_manifest_check=False)
        if runtime.overall != "pass":
            return FixtureCommandResult(
                fixture_id=self.id,
                status=_result_status(runtime.overall),
                checks=runtime.checks,
                manifest=runtime.manifest,
                message=runtime.message,
                guidance=runtime.guidance,
                error_code=runtime.error_code,
            )

        created_at = ctx.now
        existing_manifest = runtime.manifest
        if (
            existing_manifest is not None
            and existing_manifest.worktree.fingerprint == runtime.current_worktree.fingerprint
        ):
            created_at = existing_manifest.created_at

        manifest = FixtureManifest(
            schema_version=FIXTURE_SCHEMA_VERSION,
            fixture_id=self.id,
            status="ready",
            created_at=created_at,
            updated_at=ctx.now,
            worktree=runtime.current_worktree,
            resources={"devserver": _manifest_resource(runtime.state)},
            provides=_manifest_provides(runtime.state),
            doctor=None,
        )
        save_fixture_manifest(manifest, ctx.testenv_root)
        return self.doctor(ctx)

    def doctor(self, ctx: FixtureContext) -> FixtureCommandResult:
        """Compare the manifest with the actual devserver state."""
        snapshot = self._doctor_snapshot(ctx, include_manifest_check=True)
        manifest = snapshot.manifest
        if manifest is not None:
            doctor = DoctorSummary(
                last_checked_at=ctx.now,
                last_result=snapshot.overall,
                checks=list(snapshot.checks),
            )
            manifest = manifest.model_copy(
                update={
                    "status": _manifest_status(snapshot.overall),
                    "updated_at": ctx.now,
                    "doctor": doctor,
                }
            )
            save_fixture_manifest(manifest, ctx.testenv_root)

        return FixtureCommandResult(
            fixture_id=self.id,
            status=_result_status(snapshot.overall),
            checks=snapshot.checks,
            manifest=manifest,
            message=snapshot.message,
            guidance=snapshot.guidance,
            error_code=snapshot.error_code,
        )

    def reset(self, ctx: FixtureContext) -> FixtureCommandResult:
        """Remove the logical fixture manifest."""
        deleted = delete_fixture_manifest(self.id, ctx.testenv_root)
        message = (
            "Fixture manifest removed; devserver is still running"
            if deleted
            else "Fixture manifest already absent"
        )
        return FixtureCommandResult(
            fixture_id=self.id,
            status="ready",
            checks=(),
            manifest=None,
            message=message,
            guidance=(
                "Use `uv run testenv fixture up devserver` to record the current devserver again."
            ),
        )

    def _doctor_snapshot(
        self,
        ctx: FixtureContext,
        *,
        include_manifest_check: bool,
    ) -> _DoctorSnapshot:
        """Build the shared state snapshot used by doctor and up."""
        current = current_worktree_fingerprint(ctx.testenv_root)
        manifest, manifest_check = self._load_manifest(
            ctx.testenv_root,
            include_check=include_manifest_check,
        )
        state, state_check = self._load_state(ctx.testenv_root)
        checks = [manifest_check, state_check]

        worktree_check = self._check_worktree(
            current,
            manifest,
            state,
            enforce_manifest_match=include_manifest_check,
        )
        checks.append(worktree_check)

        session_check = self._check_session()
        checks.append(session_check)

        public_check = self._check_readiness(
            "public_readiness",
            _public_readiness_url(state),
            "Public readiness endpoint",
        )
        checks.append(public_check)

        admin_check = self._check_readiness(
            "admin_readiness",
            _admin_readiness_url(state),
            "Admin readiness endpoint",
        )
        checks.append(admin_check)

        overall = _overall_result(tuple(checks))
        error_code = _first_non_pass_code(tuple(checks))
        message, guidance = _result_message(self.id, overall, error_code)
        return _DoctorSnapshot(
            current_worktree=current,
            manifest=manifest,
            state=state,
            checks=tuple(checks),
            overall=overall,
            error_code=error_code,
            message=message,
            guidance=guidance,
        )

    def _load_manifest(
        self,
        testenv_root: Path,
        *,
        include_check: bool,
    ) -> tuple[FixtureManifest | None, DoctorCheck]:
        """Load the manifest and return the corresponding doctor check."""
        try:
            manifest = load_fixture_manifest(self.id, testenv_root)
        except FixtureManifestNotFoundError:
            status = "stale" if include_check else "skip"
            return None, DoctorCheck(
                id="manifest",
                status=status,
                message="Fixture manifest is missing",
            )
        except (
            FixtureManifestReadError,
            FixtureManifestSchemaError,
            FixtureSecretValidationError,
        ) as exc:
            if not include_check:
                return None, DoctorCheck(
                    id="manifest",
                    status="skip",
                    message=exc.detail.message,
                )
            return None, DoctorCheck(
                id="manifest",
                status="fail",
                message=exc.detail.message,
            )
        return manifest, DoctorCheck(
            id="manifest",
            status="pass",
            message="Fixture manifest is valid",
        )

    def _load_state(self, testenv_root: Path) -> tuple[DevserverFixtureState | None, DoctorCheck]:
        """Load the devserver state file and validate the fixture schema."""
        state_path = _state_path(testenv_root)
        try:
            raw = read_state_raw(state_path)
        except json.JSONDecodeError:
            return None, DoctorCheck(
                id="devserver_state",
                status="fail",
                message="Devserver state JSON is invalid",
            )
        except ValueError:
            return None, DoctorCheck(
                id="devserver_state",
                status="fail",
                message="Devserver state JSON root must be an object",
            )

        if raw is None:
            return None, DoctorCheck(
                id="devserver_state",
                status="stale",
                message="Devserver state file is missing",
            )

        try:
            state = validate_state_for_fixture(raw)
        except ValidationError:
            return None, DoctorCheck(
                id="devserver_state",
                status="stale",
                message=(
                    "Devserver state is missing fixture ownership fields; "
                    "restart devserver with the current CLI"
                ),
            )

        return state, DoctorCheck(
            id="devserver_state",
            status="pass",
            message="Devserver state is valid",
        )

    def _check_worktree(
        self,
        current: WorktreeFingerprint,
        manifest: FixtureManifest | None,
        state: DevserverFixtureState | None,
        *,
        enforce_manifest_match: bool,
    ) -> DoctorCheck:
        """Check whether the current worktree owns the manifest and state."""
        if state is None:
            return DoctorCheck(
                id="worktree",
                status="stale",
                message="Worktree fingerprint cannot be checked without valid devserver state",
            )
        if state.worktree_fingerprint.fingerprint != current.fingerprint:
            return DoctorCheck(
                id="worktree",
                status="fail",
                message="Current worktree does not own the running devserver",
            )
        if (
            enforce_manifest_match
            and manifest is not None
            and manifest.worktree.fingerprint != current.fingerprint
        ):
            return DoctorCheck(
                id="worktree",
                status="fail",
                message="Fixture manifest belongs to a different worktree",
            )
        return DoctorCheck(id="worktree", status="pass", message="Worktree fingerprint matches")

    def _check_session(self) -> DoctorCheck:
        """Check whether the tmux session exists."""
        if tmux.has_session(SESSION_NAME):
            return DoctorCheck(id="session", status="pass", message="tmux session is running")
        return DoctorCheck(id="session", status="fail", message="tmux session is not running")

    def _check_readiness(self, check_id: str, url: str, label: str) -> DoctorCheck:
        """Check one readiness endpoint."""
        if probe_url(url):
            return DoctorCheck(id=check_id, status="pass", message=f"{label} is healthy")
        return DoctorCheck(id=check_id, status="fail", message=f"{label} is unhealthy")


def fixture_providers() -> dict[str, FixtureProvider]:
    """Return the current fixture provider registry."""
    from testenv.fixture_agent_basic import AgentBasicFixtureProvider  # noqa: PLC0415

    return {
        DevserverFixtureProvider.id: DevserverFixtureProvider(),
        AgentBasicFixtureProvider.id: AgentBasicFixtureProvider(),
    }


def _state_path(testenv_root: Path) -> Path:
    """Return the devserver state file path for this testenv root."""
    return testenv_root / ".state" / "devserver.state.json"


def _manifest_resource(state: DevserverFixtureState | None) -> dict[str, JsonValue]:
    """Build the manifest.resources.devserver payload."""
    if state is None:
        msg = "devserver state is required to build manifest resources"
        raise ValueError(msg)
    return {
        "session_name": state.session_name,
        "public_port": state.public_port,
        "admin_port": state.admin_port,
        "public_url": _public_base_url(state),
        "admin_url": _admin_base_url(state),
        "state_path": str(_state_path(Path(state.repo_root) / "testenv" / "azents")),
        "started_at": state.started_at,
        "reload": state.reload,
    }


def _manifest_provides(state: DevserverFixtureState | None) -> dict[str, JsonValue]:
    """Build the manifest.provides payload."""
    if state is None:
        msg = "devserver state is required to build manifest provides"
        raise ValueError(msg)
    return {
        "devserver.public_url": _public_base_url(state),
        "devserver.admin_url": _admin_base_url(state),
        "devserver.session_name": state.session_name,
    }


def _public_base_url(state: DevserverFixtureState | None) -> str:
    """Return the public base URL."""
    port = 8010 if state is None else state.public_port
    return f"http://localhost:{port}"


def _admin_base_url(state: DevserverFixtureState | None) -> str:
    """Return the admin base URL."""
    port = 8011 if state is None else state.admin_port
    return f"http://localhost:{port}"


def _public_readiness_url(state: DevserverFixtureState | None) -> str:
    """Return the public readiness URL."""
    port = 8010 if state is None else state.public_port
    return f"http://localhost:{port}/health/v1/readiness"


def _admin_readiness_url(state: DevserverFixtureState | None) -> str:
    """Return the admin readiness URL."""
    port = 8011 if state is None else state.admin_port
    return f"http://localhost:{port}/health/v1/readiness"


def _overall_result(checks: tuple[DoctorCheck, ...]) -> Literal["pass", "fail", "stale"]:
    """Convert doctor checks to the overall result."""
    if any(check.status == "fail" for check in checks):
        return "fail"
    if any(check.status == "stale" for check in checks):
        return "stale"
    return "pass"


def _first_non_pass_code(checks: tuple[DoctorCheck, ...]) -> str | None:
    """Return a machine-readable code for the first non-pass check."""
    checks_by_id = {check.id: check for check in checks}
    worktree = checks_by_id.get("worktree")
    if worktree is not None and worktree.status == "fail":
        return "FIXTURE_WORKTREE_MISMATCH"

    state = checks_by_id.get("devserver_state")
    if state is not None:
        if state.status == "stale":
            return "FIXTURE_DEVSERVER_STATE_MISSING"
        if state.status == "fail":
            return "FIXTURE_DEVSERVER_STATE_INVALID"

    public_readiness = checks_by_id.get("public_readiness")
    admin_readiness = checks_by_id.get("admin_readiness")
    if (
        public_readiness is not None
        and public_readiness.status == "fail"
        or admin_readiness is not None
        and admin_readiness.status == "fail"
    ):
        return "FIXTURE_DEVSERVER_UNHEALTHY"

    session = checks_by_id.get("session")
    if session is not None and session.status == "fail":
        return "FIXTURE_DEVSERVER_NOT_RUNNING"

    manifest = checks_by_id.get("manifest")
    if manifest is not None and manifest.status not in {"pass", "skip"}:
        return "FIXTURE_MANIFEST_NOT_READY"
    return None


def _result_message(
    fixture_id: str,
    overall: Literal["pass", "fail", "stale"],
    error_code: str | None,
) -> tuple[str, str | None]:
    """Return the CLI summary message and guidance."""
    if overall == "pass":
        return (f"Fixture {fixture_id} is ready", None)
    guidance = "Use `uv run testenv fixture up devserver` after fixing the issue."
    if error_code in {"FIXTURE_DEVSERVER_STATE_MISSING", "FIXTURE_DEVSERVER_NOT_RUNNING"}:
        guidance = (
            "Start devserver with `uv run devserver.py up`, then run "
            "`uv run testenv fixture up devserver`."
        )
    if error_code == "FIXTURE_WORKTREE_MISMATCH":
        guidance = (
            "Restart devserver from this worktree instead of reusing a different worktree session."
        )
    if overall == "stale":
        return (f"Fixture {fixture_id} is stale", guidance)
    return (f"Fixture {fixture_id} is unhealthy", guidance)


def _result_status(overall: Literal["pass", "fail", "stale"]) -> FixtureStatus:
    """Convert the doctor result to a command status."""
    if overall == "pass":
        return "ready"
    if overall == "stale":
        return "stale"
    return "error"


def _manifest_status(
    overall: Literal["pass", "fail", "stale"],
) -> Literal["ready", "stale", "error"]:
    """Convert the doctor result to manifest.status."""
    return _result_status(overall)
