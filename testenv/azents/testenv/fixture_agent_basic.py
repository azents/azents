"""agent-basic fixture provider."""

import datetime as dt
from dataclasses import dataclass
from json import JSONDecodeError
from pathlib import Path
from typing import Literal, cast

from pydantic import JsonValue

from testenv.config import TestenvConfig, default_env_path
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
from testenv.fixture_paths import fixture_private_state_path
from testenv.fixture_resources import (
    DevserverFixtureProvider,
    FixtureCommandResult,
    FixtureContext,
    FixtureProvider,
)
from testenv.fixture_worktree import current_worktree_fingerprint
from testenv.frontmatter import load_all_setups
from testenv.setup_runner import resolve_setup_dag, run_setup
from testenv.state import State, load_state
from testenv.types import SetupOutcome

_READY = "ready"
_STALE = "stale"
_ERROR = "error"
_PASS = "pass"
_FAIL = "fail"
_SKIP = "skip"

_REQUIRED_SETUP_IDS = (
    "test-user-workspace",
    "llm-provider-dummy",
    "agent-dummy-key",
)
_REQUIRED_STATE_KEYS = (
    "user.email",
    "ws.handle",
    "ws.name",
    "integration.id",
    "integration.provider",
    "integration.name",
    "agent.id",
    "agent.model_slug",
)


@dataclass(frozen=True)
class _DoctorSnapshot:
    """Snapshot of an agent-basic doctor run."""

    current_worktree: WorktreeFingerprint
    manifest: FixtureManifest | None
    checks: tuple[DoctorCheck, ...]
    overall: Literal["pass", "fail", "stale"]
    error_code: str | None
    message: str
    guidance: str | None


class AgentBasicFixtureProvider:
    """Fixture provider that seeds and validates the agent-basic fixture."""

    id = "agent-basic"

    def __init__(self, devserver_provider: FixtureProvider | None = None) -> None:
        self._devserver_provider = devserver_provider or DevserverFixtureProvider()

    def up(self, ctx: FixtureContext) -> FixtureCommandResult:
        """Ensure the devserver is ready, then run the setup DAG."""
        dependency = self._devserver_provider.doctor(ctx)
        if dependency.status != _READY:
            return self._dependency_not_ready_result(dependency)

        current = current_worktree_fingerprint(ctx.testenv_root)
        state_path = fixture_private_state_path(self.id, ctx.testenv_root)
        state = _load_or_recreate_private_state(state_path, current)
        _record_private_state_worktree(state, current)
        setup_outcomes = self._run_setup_chain(ctx, state)
        blocked = next(
            (outcome for outcome in setup_outcomes if outcome.outcome == "blocked"),
            None,
        )
        if blocked is not None:
            return FixtureCommandResult(
                fixture_id=self.id,
                status=_ERROR,
                checks=(
                    DoctorCheck(
                        id="devserver",
                        status=_PASS,
                        message="Dependency fixture devserver is ready",
                    ),
                    DoctorCheck(
                        id="setup_chain",
                        status=_FAIL,
                        message=f"Setup {blocked.setup_id} blocked: {blocked.reason}",
                    ),
                ),
                manifest=None,
                message="Fixture agent-basic setup chain failed",
                guidance=(
                    "Fix the blocked setup, then rerun `uv run testenv fixture up agent-basic`."
                ),
                error_code="FIXTURE_AGENT_BASIC_SETUP_BLOCKED",
            )

        state = load_state(state_path)
        _record_private_state_worktree(state, current)
        state_snapshot = self._load_private_state_snapshot(state_path, current)
        if state_snapshot.check.status != _PASS:
            return FixtureCommandResult(
                fixture_id=self.id,
                status=_status_from_check(state_snapshot.check.status),
                checks=(
                    DoctorCheck(
                        id="devserver",
                        status=_PASS,
                        message="Dependency fixture devserver is ready",
                    ),
                    state_snapshot.check,
                ),
                manifest=None,
                message=_message_for_code(_error_code_for_state_check(state_snapshot.check)),
                guidance=_guidance_for_code(_error_code_for_state_check(state_snapshot.check)),
                error_code=_error_code_for_state_check(state_snapshot.check),
            )

        existing_manifest = _load_existing_manifest(self.id, ctx.testenv_root)
        manifest = self._build_manifest(
            now=ctx.now,
            current_worktree=current,
            dependency_manifest=dependency.manifest,
            state=state_snapshot.state,
            created_at=(
                existing_manifest.created_at
                if existing_manifest is not None
                and existing_manifest.worktree.fingerprint == current.fingerprint
                else ctx.now
            ),
        )
        save_fixture_manifest(manifest, ctx.testenv_root)
        return self.doctor(ctx)

    def doctor(self, ctx: FixtureContext) -> FixtureCommandResult:
        """Check manifest, dependency fixture, private state, and runtime readiness."""
        snapshot = self._doctor_snapshot(ctx)
        manifest = snapshot.manifest
        if manifest is not None:
            manifest = manifest.model_copy(
                update={
                    "status": _manifest_status(snapshot.overall),
                    "updated_at": ctx.now,
                    "doctor": DoctorSummary(
                        last_checked_at=ctx.now,
                        last_result=snapshot.overall,
                        checks=list(snapshot.checks),
                    ),
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
        """Delete the public manifest and fixture-private state."""
        deleted_manifest = delete_fixture_manifest(self.id, ctx.testenv_root)
        deleted_state = _delete_private_state(self.id, ctx.testenv_root)
        message = (
            "Fixture manifest and private state removed"
            if deleted_manifest or deleted_state
            else "Fixture manifest and private state already absent"
        )
        return FixtureCommandResult(
            fixture_id=self.id,
            status=_READY,
            checks=(),
            manifest=None,
            message=message,
            guidance="Run `uv run testenv fixture up agent-basic` to seed a fresh fixture again.",
        )

    def _doctor_snapshot(self, ctx: FixtureContext) -> _DoctorSnapshot:
        """Build the current fixture state used by doctor and up."""
        current = current_worktree_fingerprint(ctx.testenv_root)
        manifest, manifest_check = _load_manifest_check(self.id, ctx.testenv_root)
        dependency = self._devserver_provider.doctor(ctx)
        dependency_check = _dependency_check(dependency)
        worktree_check = _worktree_check(current, manifest)
        state_snapshot = self._load_private_state_snapshot(
            fixture_private_state_path(self.id, ctx.testenv_root),
            current,
        )
        checks = (
            manifest_check,
            dependency_check,
            worktree_check,
            state_snapshot.check,
        )
        overall = _overall_result(checks)
        error_code = _first_error_code(checks)
        return _DoctorSnapshot(
            current_worktree=current,
            manifest=manifest,
            checks=checks,
            overall=overall,
            error_code=error_code,
            message=_message_for_code(error_code, overall=overall),
            guidance=_guidance_for_code(error_code),
        )

    def _load_private_state_snapshot(
        self,
        path: Path,
        current_worktree: WorktreeFingerprint,
    ) -> "_PrivateStateSnapshot":
        """Check whether the required private state file exists and is valid."""
        if not path.exists():
            return _PrivateStateSnapshot(
                state=None,
                check=DoctorCheck(
                    id="private_state",
                    status=_STALE,
                    message="Fixture private state file is missing",
                ),
            )
        try:
            state = load_state(path)
        except JSONDecodeError:
            return _PrivateStateSnapshot(
                state=None,
                check=DoctorCheck(
                    id="private_state",
                    status=_FAIL,
                    message="Fixture private state JSON is invalid",
                ),
            )
        owner = state.get_run("fixture.worktree_fingerprint")
        if owner is None:
            return _PrivateStateSnapshot(
                state=state,
                check=DoctorCheck(
                    id="private_state",
                    status=_STALE,
                    message="Fixture private state is missing worktree ownership",
                ),
            )
        if owner != current_worktree.fingerprint:
            return _PrivateStateSnapshot(
                state=state,
                check=DoctorCheck(
                    id="private_state",
                    status=_FAIL,
                    message="Fixture private state belongs to a different worktree",
                ),
            )
        missing_keys = [key for key in _REQUIRED_STATE_KEYS if not state.has_provide(key)]
        if missing_keys:
            return _PrivateStateSnapshot(
                state=state,
                check=DoctorCheck(
                    id="private_state",
                    status=_STALE,
                    message=(
                        "Fixture private state is missing required identifiers: "
                        + ", ".join(missing_keys)
                    ),
                ),
            )
        return _PrivateStateSnapshot(
            state=state,
            check=DoctorCheck(
                id="private_state",
                status=_PASS,
                message="Fixture private state contains required identifiers",
            ),
        )

    def _run_setup_chain(self, ctx: FixtureContext, state: State) -> list[SetupOutcome]:
        """Run the setup DAG required by this fixture."""
        all_setups = load_all_setups(ctx.testenv_root / "setup")
        ordered = resolve_setup_dag(list(_REQUIRED_SETUP_IDS), all_setups)
        config = _load_testenv_config(ctx.testenv_root)
        outcomes: list[SetupOutcome] = []
        for spec in ordered:
            outcome = run_setup(spec, state, config=config)
            outcomes.append(outcome)
            if outcome.outcome == "blocked":
                break
        return outcomes

    def _build_manifest(
        self,
        *,
        now: dt.datetime,
        current_worktree: WorktreeFingerprint,
        dependency_manifest: FixtureManifest | None,
        state: State | None,
        created_at: dt.datetime,
    ) -> FixtureManifest:
        """Build the public-safe manifest payload from private state."""
        if dependency_manifest is None:
            msg = "Dependency manifest is required to build agent-basic manifest"
            raise ValueError(msg)
        if state is None:
            msg = "Fixture private state is required to build agent-basic manifest"
            raise ValueError(msg)
        resources = _manifest_resources(state, dependency_manifest)
        provides = _manifest_provides(state, dependency_manifest)
        return FixtureManifest(
            schema_version=FIXTURE_SCHEMA_VERSION,
            fixture_id=self.id,
            status=_READY,
            created_at=created_at,
            updated_at=now,
            worktree=current_worktree,
            resources=resources,
            provides=provides,
            doctor=None,
        )

    def _dependency_not_ready_result(
        self,
        dependency: FixtureCommandResult,
    ) -> FixtureCommandResult:
        """Convert an unready devserver dependency into an agent-basic result."""
        error_code = (
            "FIXTURE_WORKTREE_MISMATCH"
            if dependency.error_code == "FIXTURE_WORKTREE_MISMATCH"
            else "FIXTURE_AGENT_BASIC_DEVSERVER_NOT_READY"
        )
        return FixtureCommandResult(
            fixture_id=self.id,
            status=dependency.status,
            checks=(_dependency_check(dependency),),
            manifest=None,
            message=_message_for_code(
                error_code,
                overall=_overall_from_result_status(dependency.status),
            ),
            guidance=dependency.guidance or _guidance_for_code(error_code),
            error_code=error_code,
        )


@dataclass(frozen=True)
class _PrivateStateSnapshot:
    """Private fixture state check result."""

    state: State | None
    check: DoctorCheck


def _load_testenv_config(testenv_root: Path) -> TestenvConfig:
    """Load config used by setup subprocesses in the fixture provider."""
    env_path = testenv_root / ".env"
    if not env_path.exists():
        env_path = default_env_path()
    return TestenvConfig.load(env_path)


def _load_or_recreate_private_state(path: Path, current: WorktreeFingerprint) -> State:
    """Load private state or recreate it when owned by another worktree."""
    if not path.exists():
        return _new_private_state(path)
    state = load_state(path)
    owner = state.get_run("fixture.worktree_fingerprint")
    has_seeded_resources = any(state.has_provide(key) for key in _REQUIRED_STATE_KEYS)
    if owner == current.fingerprint:
        return state
    if owner is None and not has_seeded_resources:
        return state
    path.unlink()
    return _new_private_state(path)


def _new_private_state(path: Path) -> State:
    """Create a new State object for the private state path."""
    return State(
        path=path,
        run_id="fixture-agent-basic",
        started_at=dt.datetime.now(dt.UTC).isoformat(),
    )


def _record_private_state_worktree(state: State, current: WorktreeFingerprint) -> None:
    """Store the current worktree ownership marker in private state."""
    state.set_run("fixture.worktree_fingerprint", current.fingerprint)
    state.set_run("fixture.repo_root", current.repo_root)
    state.set_run("fixture.head_sha", current.head_sha)
    state.save()


def _dependency_check(result: FixtureCommandResult) -> DoctorCheck:
    """Convert a dependency fixture result into a doctor check."""
    status = cast(
        Literal["pass", "fail", "stale", "skip"],
        {
            _READY: _PASS,
            _STALE: _STALE,
            _ERROR: _FAIL,
        }[result.status],
    )
    return DoctorCheck(id="devserver", status=status, message=result.message)


def _worktree_check(
    current: WorktreeFingerprint,
    manifest: FixtureManifest | None,
) -> DoctorCheck:
    """Compare the manifest worktree fingerprint with the current worktree."""
    if manifest is None:
        return DoctorCheck(
            id="worktree",
            status=_SKIP,
            message="Worktree check skipped without manifest",
        )
    if manifest.worktree.fingerprint != current.fingerprint:
        return DoctorCheck(
            id="worktree",
            status=_FAIL,
            message="Fixture manifest belongs to a different worktree",
        )
    return DoctorCheck(id="worktree", status=_PASS, message="Worktree fingerprint matches")


def _manifest_resources(
    state: State,
    dependency_manifest: FixtureManifest,
) -> dict[str, JsonValue]:
    """Build the public manifest resources payload."""
    return {
        "devserver": _devserver_resource(dependency_manifest),
        "user": {"email": _require_run_value(state, "user.email")},
        "workspace": {
            "handle": _require_run_value(state, "ws.handle"),
            "name": _require_run_value(state, "ws.name"),
        },
        "integration": {
            "id": _require_run_value(state, "integration.id"),
            "provider": _require_run_value(state, "integration.provider"),
            "name": _require_run_value(state, "integration.name"),
        },
        "agent": {
            "id": _require_run_value(state, "agent.id"),
            "model_slug": _require_run_value(state, "agent.model_slug"),
        },
    }


def _manifest_provides(
    state: State,
    dependency_manifest: FixtureManifest,
) -> dict[str, JsonValue]:
    """Build the public manifest provides payload."""
    devserver = _devserver_resource(dependency_manifest)
    return {
        "user.email": _require_run_value(state, "user.email"),
        "ws.handle": _require_run_value(state, "ws.handle"),
        "ws.name": _require_run_value(state, "ws.name"),
        "integration.id": _require_run_value(state, "integration.id"),
        "integration.provider": _require_run_value(state, "integration.provider"),
        "integration.name": _require_run_value(state, "integration.name"),
        "agent.id": _require_run_value(state, "agent.id"),
        "agent.model_slug": _require_run_value(state, "agent.model_slug"),
        "devserver.public_url": devserver["public_url"],
        "devserver.admin_url": devserver["admin_url"],
        "devserver.session_name": devserver["session_name"],
    }


def _devserver_resource(dependency_manifest: FixtureManifest) -> dict[str, JsonValue]:
    """Extract a public-safe dependency summary from the devserver manifest."""
    resource = dependency_manifest.resources.get("devserver")
    if not isinstance(resource, dict):
        msg = "Dependency manifest does not contain devserver resource payload"
        raise ValueError(msg)
    session_name = resource.get("session_name")
    public_url = resource.get("public_url")
    admin_url = resource.get("admin_url")
    if (
        not isinstance(session_name, str)
        or not isinstance(public_url, str)
        or not isinstance(admin_url, str)
    ):
        msg = "Dependency manifest is missing devserver public identifiers"
        raise ValueError(msg)
    return {
        "session_name": session_name,
        "public_url": public_url,
        "admin_url": admin_url,
    }


def _require_run_value(state: State, key: str) -> str:
    """Return a required string value from the private state run bucket."""
    value = state.get_run(key)
    if not isinstance(value, str):
        msg = f"Fixture private state is missing required string: {key}"
        raise ValueError(msg)
    return value


def _load_manifest_check(
    fixture_id: str,
    testenv_root: Path,
) -> tuple[FixtureManifest | None, DoctorCheck]:
    """Load a manifest and return the matching doctor check."""
    try:
        manifest = load_fixture_manifest(fixture_id, testenv_root)
    except FixtureManifestNotFoundError:
        return None, DoctorCheck(
            id="manifest",
            status=_STALE,
            message="Fixture manifest is missing",
        )
    except (
        FixtureManifestReadError,
        FixtureManifestSchemaError,
        FixtureSecretValidationError,
    ) as exc:
        return None, DoctorCheck(id="manifest", status=_FAIL, message=str(exc))
    return manifest, DoctorCheck(id="manifest", status=_PASS, message="Fixture manifest is valid")


def _load_existing_manifest(fixture_id: str, testenv_root: Path) -> FixtureManifest | None:
    """Try to load an existing manifest and return None on failure."""
    try:
        return load_fixture_manifest(fixture_id, testenv_root)
    except (
        FixtureManifestNotFoundError,
        FixtureManifestReadError,
        FixtureManifestSchemaError,
        FixtureSecretValidationError,
    ):
        return None


def _delete_private_state(fixture_id: str, testenv_root: Path) -> bool:
    """Delete the fixture-private state file and return whether it was removed."""
    path = fixture_private_state_path(fixture_id, testenv_root)
    if not path.exists():
        return False
    path.unlink()
    return True


def _overall_result(checks: tuple[DoctorCheck, ...]) -> Literal["pass", "fail", "stale"]:
    """Convert doctor checks into an overall state."""
    if any(check.status == _FAIL for check in checks):
        return "fail"
    if any(check.status == _STALE for check in checks):
        return "stale"
    return "pass"


def _first_error_code(checks: tuple[DoctorCheck, ...]) -> str | None:
    """Return the error code for the first non-pass check."""
    for check in checks:
        if check.id == "worktree" and check.status == _FAIL:
            return "FIXTURE_WORKTREE_MISMATCH"
        if check.id == "manifest" and check.status == _STALE:
            return "FIXTURE_MANIFEST_NOT_READY"
        if check.id == "manifest" and check.status == _FAIL:
            return "FIXTURE_MANIFEST_NOT_READY"
        if check.id == "devserver" and check.status in {_STALE, _FAIL}:
            return "FIXTURE_AGENT_BASIC_DEVSERVER_NOT_READY"
        if check.id == "private_state":
            return _error_code_for_state_check(check)
    return None


def _error_code_for_state_check(check: DoctorCheck) -> str | None:
    """Return the error code for a private state check result."""
    if check.id != "private_state" or check.status == _PASS:
        return None
    if check.message == "Fixture private state file is missing":
        return "FIXTURE_AGENT_BASIC_STATE_MISSING"
    if check.message == "Fixture private state JSON is invalid":
        return "FIXTURE_AGENT_BASIC_STATE_INVALID"
    return "FIXTURE_AGENT_BASIC_STATE_INCOMPLETE"


def _message_for_code(
    error_code: str | None,
    *,
    overall: Literal["pass", "fail", "stale"] | None = None,
) -> str:
    """Return the summary message for an error code."""
    if error_code is None:
        return "Fixture agent-basic is ready"
    if error_code == "FIXTURE_WORKTREE_MISMATCH":
        return "Fixture agent-basic is unhealthy"
    if error_code in {
        "FIXTURE_MANIFEST_NOT_READY",
        "FIXTURE_AGENT_BASIC_DEVSERVER_NOT_READY",
        "FIXTURE_AGENT_BASIC_STATE_MISSING",
        "FIXTURE_AGENT_BASIC_STATE_INCOMPLETE",
    }:
        return "Fixture agent-basic is stale"
    if error_code in {
        "FIXTURE_AGENT_BASIC_RUNTIME_NOT_READY",
        "FIXTURE_AGENT_BASIC_STATE_INVALID",
        "FIXTURE_AGENT_BASIC_SETUP_BLOCKED",
    }:
        return "Fixture agent-basic is unhealthy"
    if overall == "stale":
        return "Fixture agent-basic is stale"
    return "Fixture agent-basic is unhealthy"


def _guidance_for_code(error_code: str | None) -> str | None:
    """Return user guidance for an error code."""
    if error_code is None:
        return None
    if error_code == "FIXTURE_MANIFEST_NOT_READY":
        return "Run `uv run testenv fixture up agent-basic` to seed the fixture in this worktree."
    if error_code == "FIXTURE_AGENT_BASIC_DEVSERVER_NOT_READY":
        return (
            "Ensure devserver fixture is ready with "
            "`uv run testenv fixture up devserver` before agent-basic."
        )
    if error_code == "FIXTURE_AGENT_BASIC_STATE_MISSING":
        return "Run `uv run testenv fixture up agent-basic` to recreate fixture private state."
    if error_code == "FIXTURE_AGENT_BASIC_STATE_INCOMPLETE":
        return (
            "Run `uv run testenv fixture reset agent-basic` and then "
            "`uv run testenv fixture up agent-basic`."
        )
    if error_code == "FIXTURE_AGENT_BASIC_STATE_INVALID":
        return (
            "Delete or reset the private state file, then rerun "
            "`uv run testenv fixture up agent-basic`."
        )
    if error_code == "FIXTURE_AGENT_BASIC_RUNTIME_NOT_READY":
        return (
            "Check docker runtime image readiness and rerun "
            "`uv run testenv fixture up agent-basic`."
        )
    if error_code == "FIXTURE_WORKTREE_MISMATCH":
        return (
            "Recreate the fixture from the current worktree instead of "
            "reusing another worktree state."
        )
    if error_code == "FIXTURE_AGENT_BASIC_SETUP_BLOCKED":
        return "Fix the blocked setup, then rerun `uv run testenv fixture up agent-basic`."
    return None


def _status_from_check(
    status: Literal["pass", "fail", "stale", "skip"],
) -> Literal["ready", "stale", "error"]:
    """Convert a doctor check state to a command state."""
    if status == _PASS:
        return _READY
    if status == _STALE:
        return _STALE
    return _ERROR


def _result_status(overall: Literal["pass", "fail", "stale"]) -> Literal["ready", "stale", "error"]:
    """Convert a doctor state to a command state."""
    if overall == "pass":
        return _READY
    if overall == "stale":
        return _STALE
    return _ERROR


def _manifest_status(
    overall: Literal["pass", "fail", "stale"],
) -> Literal["ready", "stale", "error"]:
    """Convert a doctor state to manifest.status."""
    return _result_status(overall)


def _overall_from_result_status(
    status: Literal["ready", "stale", "error"],
) -> Literal["pass", "stale", "fail"]:
    """Convert a command state to a doctor overall state."""
    if status == _READY:
        return "pass"
    if status == _STALE:
        return "stale"
    return "fail"
