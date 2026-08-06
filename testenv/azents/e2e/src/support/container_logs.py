"""Sanitized container-log capture helpers for E2E diagnostics."""

from pathlib import Path
from typing import Protocol


class ContainerLogs(Protocol):
    """Minimal container interface needed for diagnostic log capture."""

    def get_logs(self) -> tuple[bytes, bytes]:
        """Return container stdout and stderr."""


def read_sanitized_container_logs(
    container: ContainerLogs,
    *,
    secret_values: tuple[str, ...],
) -> str:
    """Read container output while redacting every supplied secret value."""
    stdout, stderr = container.get_logs()
    logs = stdout.decode(errors="replace") + stderr.decode(errors="replace")
    for secret_value in secret_values:
        if secret_value:
            logs = logs.replace(secret_value, "<redacted>")
    return logs


def write_sanitized_container_logs_artifact(
    container: ContainerLogs,
    *,
    server_name: str,
    artifact_root: Path | None,
    secret_values: tuple[str, ...],
) -> None:
    """Best-effort write sanitized server logs to the configured E2E artifact."""
    if artifact_root is None:
        return
    try:
        logs = read_sanitized_container_logs(
            container,
            secret_values=secret_values,
        )
        destination = artifact_root / "server-logs" / f"{server_name}.log"
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(logs, encoding="utf-8")
    except Exception:
        # Diagnostic capture must never conceal the original test outcome.
        return
