"""Reclaim helpers for cleaning up stale real-world state.

When a previous fixture setup crashed before finalizers ran, external resources
may remain. A setup can define reclaim to clean them before rerunning.
"""

import logging
import os
import subprocess
from dataclasses import dataclass

from .state import State
from .types import SetupSpec

logger = logging.getLogger(__name__)

DEFAULT_RECLAIM_TIMEOUT = 120


@dataclass
class ReclaimReport:
    """Reclaim run result."""

    setup_id: str
    attempted: bool
    returncode: int
    stdout: str
    stderr: str


def try_reclaim(
    spec: SetupSpec,
    state: State,
    timeout: int = DEFAULT_RECLAIM_TIMEOUT,
) -> ReclaimReport:
    """Run a setup's ``reclaim`` command if present.

    Missing ``reclaim`` is a no-op with attempted=False.

    :param spec: setup spec.
    :param state: current state; its path is passed as ``STATE_FILE``.
    :param timeout: maximum shell run time.
    :returns: :class:`ReclaimReport`. Failures and exceptions are returned as reports.
    """
    if not spec.reclaim:
        return ReclaimReport(setup_id=spec.id, attempted=False, returncode=0, stdout="", stderr="")

    logger.info("reclaiming setup=%s", spec.id)
    env = dict(os.environ)
    env["STATE_FILE"] = str(state.path)

    try:
        result = subprocess.run(
            spec.reclaim,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
            check=False,
        )
        return ReclaimReport(
            setup_id=spec.id,
            attempted=True,
            returncode=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
        )
    except subprocess.TimeoutExpired:
        logger.warning("reclaim timed out for setup=%s", spec.id)
        return ReclaimReport(
            setup_id=spec.id,
            attempted=True,
            returncode=-1,
            stdout="",
            stderr=f"timeout after {timeout}s",
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("reclaim crashed for setup=%s", spec.id)
        return ReclaimReport(
            setup_id=spec.id,
            attempted=True,
            returncode=-2,
            stdout="",
            stderr=str(exc),
        )
