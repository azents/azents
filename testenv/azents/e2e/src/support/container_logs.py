"""Container-log capture helpers for E2E diagnostics."""

from collections.abc import Callable
from typing import Protocol


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
        # Diagnostic capture must never conceal the original test outcome.
        return
