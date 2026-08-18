"""Container-log capture helpers for E2E diagnostics."""

import logging
from collections.abc import Callable
from typing import Protocol

logger = logging.getLogger(__name__)


class ContainerLogs(Protocol):
    """Minimal container interface needed for diagnostic log capture."""

    def get_logs(self) -> tuple[bytes, bytes]:
        """Return container stdout and stderr."""


def read_container_logs(container: ContainerLogs) -> str:
    """Read the complete container stdout and stderr."""
    stdout, stderr = container.get_logs()
    return stdout.decode(errors="replace") + stderr.decode(errors="replace")


def emit_container_logs(
    container: ContainerLogs,
    *,
    server_name: str,
    write_line: Callable[[str], None],
) -> None:
    """Best-effort emit complete server logs to the active test terminal."""
    try:
        logs = read_container_logs(container)
        write_line(f"=== {server_name} logs ===")
        for line in logs.splitlines():
            write_line(line)
    except Exception:
        # The container client and output callback may raise implementation-specific
        # errors, but diagnostics must not replace the original test outcome.
        logger.warning(
            "Failed to capture E2E container logs",
            exc_info=True,
            extra={"server_name": server_name},
        )
