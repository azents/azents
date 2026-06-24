"""Resource locks backed by filelock and unique lock tags.

Setup frontmatter can declare a ``locks:`` field with resource tags. To avoid
deadlocks, tags are deduplicated and acquired in sorted order, then released in
reverse order.

Example::

    with exclusive_resource(["shared-oauth-app"], timeout=300):
        # setup/probe work that needs this tag runs while the lock is held

The ``TESTENV_LOCK_DIR`` environment variable can override the lock directory.
The default is ``<cwd>/runs/_locks``.
"""

import logging
import os
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

from filelock import BaseFileLock, FileLock, Timeout

logger = logging.getLogger(__name__)


def default_lock_dir(workdir: Path | None = None) -> Path:
    """Return the default lock directory, usually ``runs/_locks/``."""
    env = os.environ.get("TESTENV_LOCK_DIR")
    if env:
        return Path(env)
    base = workdir if workdir is not None else Path.cwd()
    return base / "runs" / "_locks"


@contextmanager
def exclusive_resource(
    tags: list[str],
    timeout: int = 300,
    lock_dir: Path | None = None,
) -> Generator[None, None, None]:
    """Acquire exclusive locks for the given tags.

    :param tags: lock tag list. Duplicates are ignored.
    :param timeout: maximum time to wait for each lock, in seconds.
    :param lock_dir: directory for lock files. Defaults to :func:`default_lock_dir`.
    :yields: context that holds all acquired locks until exit.
    :raises filelock.Timeout: when a lock cannot be acquired within timeout.
    """
    base = lock_dir if lock_dir is not None else default_lock_dir()
    base.mkdir(parents=True, exist_ok=True)
    # Prevent deadlocks by acquiring locks in deterministic order.
    unique_sorted = sorted(set(tags))
    locks: list[BaseFileLock] = [
        FileLock(str(base / f"{tag}.lock"), timeout=timeout) for tag in unique_sorted
    ]
    acquired: list[BaseFileLock] = []
    try:
        for tag, lk in zip(unique_sorted, locks, strict=True):
            try:
                lk.acquire()
            except Timeout:
                logger.error("failed to acquire lock %s within %ds", tag, timeout)
                raise
            logger.debug("acquired lock %s", tag)
            acquired.append(lk)
        yield
    finally:
        for lk in reversed(acquired):
            try:
                lk.release()
            except Exception:  # noqa: BLE001
                logger.exception("failed to release lock %s", lk.lock_file)
