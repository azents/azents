"""Tests for sanitized E2E container-log artifacts."""

from pathlib import Path

from support.container_logs import (
    read_sanitized_container_logs,
    write_sanitized_container_logs_artifact,
)


class _Container:
    """Small fake container with deterministic stdout and stderr."""

    def __init__(self, stdout: bytes, stderr: bytes) -> None:
        self.stdout = stdout
        self.stderr = stderr

    def get_logs(self) -> tuple[bytes, bytes]:
        """Return configured output."""
        return self.stdout, self.stderr


def test_read_sanitized_container_logs_redacts_supplied_values() -> None:
    """Redaction applies to both container output streams."""
    logs = read_sanitized_container_logs(
        _Container(b"stdout secret-value", b"stderr secret-value"),
        secret_values=("secret-value",),
    )

    assert logs == "stdout <redacted>stderr <redacted>"


def test_write_sanitized_container_logs_artifact_writes_named_log(
    tmp_path: Path,
) -> None:
    """Configured artifacts retain only sanitized named server logs."""
    write_sanitized_container_logs_artifact(
        _Container(b"authorization token-value", b""),
        server_name="azents-public-server",
        artifact_root=tmp_path,
        secret_values=("token-value",),
    )

    artifact = tmp_path / "server-logs" / "azents-public-server.log"
    assert artifact.read_text() == "authorization <redacted>"


def test_write_sanitized_container_logs_artifact_is_a_noop_without_root() -> None:
    """Local runs without an artifact root do not write diagnostics."""
    write_sanitized_container_logs_artifact(
        _Container(b"output", b""),
        server_name="azents-public-server",
        artifact_root=None,
        secret_values=(),
    )
