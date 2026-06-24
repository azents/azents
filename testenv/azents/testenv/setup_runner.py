"""Fixture setup runner: DAG resolver plus three execution cases.

Three-case model:

    Case 1 — ``provides: []`` and no verify command → always run
    Case 2 — ``provides: []`` and verify exists
        verify exit 0 → skip
        verify failure + idempotent → run
        verify failure + not idempotent → block (BLOCKED)
    Case 3 — ``provides`` has entries
        existing provides in state and ``not stale`` → skip
        missing or stale provides → reclaim, then run

This is used by fixture providers to run internal Python setup handlers.
"""

import graphlib
import logging
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .config import TestenvConfig
from .finalizer import register_teardown
from .frontmatter import load_all_setups
from .reclaim import try_reclaim
from .state import State
from .types import SetupOutcome, SetupSpec

logger = logging.getLogger(__name__)


DEFAULT_SHELL_TIMEOUT = 300
STALE_SECONDS = 3600
"""Default stale threshold, one hour. See design §14."""


class SetupHandlerExecutionError(RuntimeError):
    """Setup handler invocation failure."""


@dataclass(frozen=True)
class SetupHandlerResult:
    """Setup handler subprocess run result."""

    returncode: int
    stdout: str
    stderr: str


class SetupResolveError(ValueError):
    """DAG cycle or unknown setup reference error."""


# ----- DAG resolution --------------------------------------------------------


def resolve_setup_dag(
    wanted: list[str],
    all_setups: dict[str, SetupSpec],
) -> list[SetupSpec]:
    """Topologically sort setup ids with their dependencies.

    :param wanted: setup ids requested by a fixture provider.
    :param all_setups: mapping of setup id → SetupSpec, usually from
        ``load_all_setups``.
    :returns: :class:`SetupSpec` objects in execution order.
    :raises SetupResolveError: when a setup reference is unknown or cyclic.
    """
    # Collect the transitive dependency closure.
    needed: set[str] = set()
    stack = list(wanted)
    while stack:
        sid = stack.pop()
        if sid in needed:
            continue
        if sid not in all_setups:
            raise SetupResolveError(f"unknown setup: {sid}")
        needed.add(sid)
        stack.extend(all_setups[sid].requires)

    graph: dict[str, set[str]] = {sid: set(all_setups[sid].requires) for sid in needed}
    # Keep dependency nodes present so graphlib can sort the full closure.
    for deps in list(graph.values()):
        for dep in deps:
            if dep not in graph:
                graph[dep] = set()

    try:
        sorter = graphlib.TopologicalSorter(graph)
        order = list(sorter.static_order())
    except graphlib.CycleError as exc:
        raise SetupResolveError(f"setup dependency cycle: {exc.args[1:]}") from exc

    return [all_setups[sid] for sid in order if sid in all_setups]


# ----- individual setup execution --------------------------------------------


def run_setup(
    spec: SetupSpec,
    state: State,
    tc_id: str | None = None,
    stale_seconds: int = STALE_SECONDS,
    config: TestenvConfig | None = None,
) -> SetupOutcome:
    """Run one setup using the three-case model.

    :param spec: setup spec to run.
    :param state: current run state.
    :param tc_id: logical id used when the setup has TC scope.
    :param stale_seconds: stale threshold.
    :param config: :class:`TestenvConfig` supplying subprocess env values.
    :returns: :class:`SetupOutcome` — ``ran`` / ``skipped`` / ``reclaimed`` / ``blocked``.
    """
    has_provides = bool(spec.provides)

    if not has_provides:
        return _run_case_1_or_2(spec, state, config)

    # Case 3
    return _run_case_3(spec, state, tc_id, stale_seconds, config)


def _run_case_1_or_2(spec: SetupSpec, state: State, config: TestenvConfig | None) -> SetupOutcome:
    """Handle ``provides: []`` cases, optionally using verify."""
    if spec.verify is None:
        # Case 1: always run.
        return _execute(spec, state, config)

    # Case 2: verify decides skip/run/block.
    if _run_verify(spec, state) == 0:
        logger.info("setup %s: verify passed, skipping", spec.id)
        return SetupOutcome(setup_id=spec.id, outcome="skipped", reason="verify passed")

    if spec.idempotent:
        logger.info("setup %s: verify failed + idempotent → running", spec.id)
        return _execute(spec, state, config)

    return SetupOutcome(
        setup_id=spec.id,
        outcome="blocked",
        reason="verify failed and setup is not idempotent — manual escalation",
    )


def _run_case_3(
    spec: SetupSpec,
    state: State,
    tc_id: str | None,
    stale_seconds: int,
    config: TestenvConfig | None,
) -> SetupOutcome:
    """Handle ``provides: [...]`` cases using state and stale checks."""
    scope_tc = spec.scope == "tc" and tc_id is not None
    all_present = all(state.has_provide(key, tc_id if scope_tc else None) for key in spec.provides)

    if all_present:
        # Revalidate stale provides with verify.
        if spec.verify is not None:
            is_stale_any = any(state.is_stale(key, stale_seconds) for key in spec.provides)
            if is_stale_any:
                if _run_verify(spec, state) == 0:
                    for key in spec.provides:
                        state.mark_verified(key)
                    state.save()
                    logger.info("setup %s: provides present + verify passed, skipping", spec.id)
                    return SetupOutcome(
                        setup_id=spec.id, outcome="skipped", reason="provides present + verify ok"
                    )
                # verify failed with provides present
                if spec.idempotent:
                    logger.info(
                        "setup %s: verify failed on stale check + idempotent → reclaim + run",
                        spec.id,
                    )
                    try_reclaim(spec, state)
                    return _execute(spec, state, config)
                return SetupOutcome(
                    setup_id=spec.id,
                    outcome="blocked",
                    reason="verify failed (stale) and setup is not idempotent",
                )
            logger.info("setup %s: provides present + within stale threshold, skipping", spec.id)
            return SetupOutcome(
                setup_id=spec.id, outcome="skipped", reason="provides present (not stale)"
            )
        logger.info("setup %s: provides present (no verify), skipping", spec.id)
        return SetupOutcome(setup_id=spec.id, outcome="skipped", reason="provides present")

    # Provides missing: try reclaim first, then run.
    reclaim_report = try_reclaim(spec, state)
    reclaimed = reclaim_report.attempted and reclaim_report.returncode == 0
    if reclaimed:
        logger.info("setup %s: reclaim ok, will run", spec.id)
    outcome = _execute(spec, state, config)
    if reclaimed:
        # Preserve execution output while reporting that reclaim preceded the run.
        return SetupOutcome(
            setup_id=spec.id,
            outcome="reclaimed",
            reason=f"{outcome.reason} (preceded by reclaim)",
            stdout=outcome.stdout,
            stderr=outcome.stderr,
        )
    return outcome


# ----- actual run -------------------------------------------------------------


def _execute(spec: SetupSpec, state: State, config: TestenvConfig | None) -> SetupOutcome:
    """Handler Python run + teardown register."""
    try:
        if spec.handler is None:
            return SetupOutcome(
                setup_id=spec.id,
                outcome="blocked",
                reason="setup handler is required",
            )
        env_extra: dict[str, str] = {"SETUP_ID": spec.id}
        if config is not None:
            for key, value in config.env_vars.items():
                env_extra.setdefault(key, value)
        result = _run_setup_handler(
            handler=spec.handler,
            state_file=state.path,
            env_extra=env_extra,
            timeout=DEFAULT_SHELL_TIMEOUT,
        )
        stdout = result.stdout
        stderr = result.stderr
        rc = result.returncode
        # Subprocess handlers may update state.json, so reload before saving again.
        # Otherwise the caller could overwrite fresh file state with stale memory.
        if rc == 0:
            state.reload()

        if rc != 0:
            return SetupOutcome(
                setup_id=spec.id,
                outcome="blocked",
                reason=f"setup execution failed (rc={rc})",
                stdout=stdout,
                stderr=stderr,
            )

        # Mark provided keys as verified after a successful handler run.
        for key in spec.provides:
            state.mark_verified(key)

        # teardown register
        if spec.teardown:
            register_teardown(state, spec.id, spec.teardown, scope=spec.scope)
        state.save()

        return SetupOutcome(
            setup_id=spec.id,
            outcome="ran",
            reason="executed",
            stdout=stdout,
            stderr=stderr,
        )

    except SetupHandlerExecutionError as exc:
        return SetupOutcome(
            setup_id=spec.id,
            outcome="blocked",
            reason=f"handler invocation error: {exc}",
        )


def _run_verify(spec: SetupSpec, state: State) -> int:
    """Run setup verify. Return 0 for pass and non-zero for failure.

    Verify failures are logged. Exceptions become return code 1 so they behave
    like verify failures.
    """
    if spec.verify is None:
        return 0
    env = dict(os.environ)
    env["STATE_FILE"] = str(state.path)
    try:
        result = subprocess.run(
            spec.verify,
            shell=True,
            capture_output=True,
            text=True,
            timeout=60,
            env=env,
            check=False,
        )
        if result.returncode != 0:
            logger.info("setup %s: verify failed rc=%d", spec.id, result.returncode)
        return result.returncode
    except subprocess.TimeoutExpired:
        logger.warning("setup %s: verify timed out", spec.id)
        return 1
    except Exception:  # noqa: BLE001
        logger.exception("setup %s: verify crashed", spec.id)
        return 1


def _run_setup_handler(
    handler: Path,
    state_file: Path,
    env_extra: dict[str, str],
    timeout: int,
) -> SetupHandlerResult:
    """Run a setup handler Python file with ``uv run python``."""
    if not handler.exists():
        raise SetupHandlerExecutionError(f"handler not found: {handler}")

    env = dict(os.environ)
    env["STATE_FILE"] = str(state_file)
    env.setdefault("AZ_LLM_CASSETTE_MODE", "live")
    env.update(env_extra)

    try:
        result = subprocess.run(
            ["uv", "run", "python", str(handler)],
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
            cwd=str(_default_cwd()),
            check=False,
        )
    except FileNotFoundError as exc:
        raise SetupHandlerExecutionError(f"uv binary not found: {exc}") from exc
    except subprocess.TimeoutExpired as exc:
        return SetupHandlerResult(
            returncode=-1,
            stdout=_bytes_or_str_to_str(exc.stdout),
            stderr=_bytes_or_str_to_str(exc.stderr) + f"\n[handler timed out after {timeout}s]",
        )
    return SetupHandlerResult(
        returncode=result.returncode,
        stdout=result.stdout,
        stderr=result.stderr,
    )


def _bytes_or_str_to_str(value: object) -> str:
    """Convert TimeoutExpired stdout/stderr values to strings."""
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _default_cwd() -> Path:
    """Return ``testenv/azents`` when discoverable, otherwise current cwd."""
    candidate = Path(__file__).resolve().parent.parent
    if (candidate / "pyproject.toml").exists():
        return candidate
    return Path.cwd()


# ----- Convenience ----------------------------------------------------------


def run_required_setups(
    tc_requires: list[str],
    setups_dir: Path,
    state: State,
    tc_id: str | None = None,
    config: TestenvConfig | None = None,
) -> list[SetupOutcome]:
    """Resolve a setup DAG and run required setups."""
    all_setups = load_all_setups(setups_dir)
    order = resolve_setup_dag(tc_requires, all_setups)
    results: list[SetupOutcome] = []
    for spec in order:
        outcome = run_setup(spec, state, tc_id=tc_id, config=config)
        results.append(outcome)
        if outcome.outcome == "blocked":
            # Stop on the first blocked setup so later dependent setups do not run.
            logger.warning("setup chain blocked at %s — stopping further setups", spec.id)
            break
    return results
