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
