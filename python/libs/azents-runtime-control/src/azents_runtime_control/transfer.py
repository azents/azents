"""Shared Runtime File Transfer protocol values."""

from dataclasses import dataclass

RUNNER_TRANSFER_PROTOCOL_VERSION = "2026-07-25"
RUNNER_TRANSFER_CAPABILITY = "file.transfer.v1"
RUNTIME_TRANSFER_COORDINATOR_AUDIENCE = "azents-runtime-transfer-coordinator"
MAX_TRANSFER_CHUNK_BYTES = 256 * 1024
MULTIPART_PART_BYTES = 5 * 1024 * 1024
STREAM_OWNER_LEASE_SECONDS = 30
STREAM_OWNER_RENEWAL_SECONDS = 10
TRANSFER_REPAIR_INTERVAL_SECONDS = 5


@dataclass(frozen=True)
class TransferIdentity:
    """One Runner-visible transfer identity without storage authority."""

    transfer_id: str
    attempt_id: str
    runtime_id: str
    runner_generation: int

    def __post_init__(self) -> None:
        """Validate bounded Runner-visible identity metadata."""
        for value, name in (
            (self.transfer_id, "transfer_id"),
            (self.attempt_id, "attempt_id"),
            (self.runtime_id, "runtime_id"),
        ):
            _bounded(value, name, 128)
        if self.runner_generation <= 0:
            raise ValueError("runner_generation must be positive")


@dataclass(frozen=True)
class CoordinatorTransferIdentity:
    """One trusted coordinator identity scoped to a transfer attempt."""

    transfer_id: str
    attempt_id: str
    runtime_id: str
    desired_generation: int
    direction: str
    operation_id: str
    session_id: str | None
    agent_id: str | None

    def __post_init__(self) -> None:
        """Validate bounded trusted coordinator identity metadata."""
        for value, name in (
            (self.transfer_id, "transfer_id"),
            (self.attempt_id, "attempt_id"),
            (self.runtime_id, "runtime_id"),
            (self.operation_id, "operation_id"),
        ):
            _bounded(value, name, 128)
        if self.session_id is not None:
            _bounded(self.session_id, "session_id", 128)
        if self.agent_id is not None:
            _bounded(self.agent_id, "agent_id", 128)
        if self.desired_generation <= 0:
            raise ValueError("desired_generation must be positive")
        if self.direction not in {"download", "upload"}:
            raise ValueError("direction must be download or upload")


def _bounded(value: str, name: str, maximum_bytes: int) -> None:
    if not value:
        raise ValueError(f"{name} must not be empty")
    if len(value.encode("utf-8")) > maximum_bytes:
        raise ValueError(f"{name} exceeds {maximum_bytes} UTF-8 bytes")
