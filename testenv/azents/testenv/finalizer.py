"""Fixture setup finalizer stack, similar to pytest ``addfinalizer`` teardown.

When setup succeeds, its ``teardown`` command is pushed onto state.finalizers.
Finalizers clean up resources created during the run. Failures are logged as
warnings and the next finalizer still runs because cleanup is best-effort.

"""

import logging
import os
import subprocess
from dataclasses import dataclass

from .state import Finalizer, State

logger = logging.getLogger(__name__)

DEFAULT_TEARDOWN_TIMEOUT = 60
"""Default maximum time, in seconds, for one finalizer shell command."""


@dataclass
class FinalizerReport:
    """Result of one finalizer run."""

    setup_id: str
    cmd: str
    returncode: int
    stdout: str
    stderr: str


def register_teardown(state: State, setup_id: str, cmd: str, scope: str = "run") -> None:
    """Register a setup ``teardown`` command on the finalizer stack."""
    logger.info("registering teardown for setup=%s scope=%s", setup_id, scope)
    state.push_finalizer(setup_id, cmd, scope=scope)


def run_all_finalizers(
    state: State,
    timeout: int = DEFAULT_TEARDOWN_TIMEOUT,
    env: dict[str, str] | None = None,
) -> list[FinalizerReport]:
    """Run and remove stacked finalizers in LIFO order.

    :param state: state containing the run finalizer stack. The stack is cleared
        after finalizers are popped.
    :param timeout: maximum time for one finalizer.
    :param env: environment for finalizer subprocesses. ``None`` uses current
        ``os.environ`` plus ``STATE_FILE``.
    :returns: finalizer run reports, including success and failure results.
    """
    if not state.finalizers:
        return []

    fins = state.pop_all_finalizers()
    reports: list[FinalizerReport] = []
    exec_env = dict(os.environ if env is None else env)
    exec_env.setdefault("STATE_FILE", str(state.path))

    for fin in fins:
        report = _run_one(fin, timeout, exec_env)
        reports.append(report)

    state.save()
    return reports


def _run_one(fin: Finalizer, timeout: int, env: dict[str, str]) -> FinalizerReport:
    """Run one finalizer and convert exceptions into FinalizerReport."""
    logger.info("running finalizer setup=%s: %s", fin.setup_id, _summary(fin.cmd))
    try:
        result = subprocess.run(
            fin.cmd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
            check=False,
        )
        if result.returncode != 0:
            logger.warning(
                "finalizer failed setup=%s rc=%d stderr=%s",
                fin.setup_id,
                result.returncode,
                _summary(result.stderr),
            )
        return FinalizerReport(
            setup_id=fin.setup_id,
            cmd=fin.cmd,
            returncode=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
        )
    except subprocess.TimeoutExpired:
        logger.warning("finalizer timed out setup=%s after %ds", fin.setup_id, timeout)
        return FinalizerReport(
            setup_id=fin.setup_id,
            cmd=fin.cmd,
            returncode=-1,
            stdout="",
            stderr=f"timeout after {timeout}s",
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("finalizer crashed setup=%s", fin.setup_id)
        return FinalizerReport(
            setup_id=fin.setup_id,
            cmd=fin.cmd,
            returncode=-2,
            stdout="",
            stderr=str(exc),
        )


def _summary(s: str, limit: int = 200) -> str:
    """Return a shortened one-line string summary."""
    s = s.strip()
    if len(s) <= limit:
        return s
    return s[:limit] + "..."
