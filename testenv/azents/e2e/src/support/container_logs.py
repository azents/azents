"""Container-log capture helpers for E2E diagnostics."""

import logging
from collections import deque
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

logger = logging.getLogger(__name__)
_FAILURE_LOG_CHARACTERS = 1_048_576


class FailureLogTail:
    """Retain a bounded diagnostic tail independently of pytest's terminal."""

    def __init__(self) -> None:
        self.lines: deque[str] = deque()
        self.characters = 0

    def append(self, line: str) -> None:
        text = (line + "\n")[-_FAILURE_LOG_CHARACTERS:]
        self.lines.append(text)
        self.characters += len(text)
        while self.characters > _FAILURE_LOG_CHARACTERS:
            self.characters -= len(self.lines.popleft())

    def save(self, path: Path, *, node_id: str) -> None:
        """Persist the tail without replacing the original test failure."""
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                f"Test: {node_id}\nBounded active-server diagnostic tail:\n"
                + "".join(self.lines),
                encoding="utf-8",
            )
        except OSError:
            logger.warning("Failed to persist E2E server diagnostics", exc_info=True)


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
