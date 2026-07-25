"""Shared Runner Control transfer intent, cancellation, and result values."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class RunnerTransferDirection(StrEnum):
    """Direction of one Runner transfer task."""

    DOWNLOAD = "download"
    UPLOAD = "upload"


class RunnerTransferCancelReason(StrEnum):
    """Reason a Runner transfer task must stop."""

    CALLER = "caller"
    DEADLINE = "deadline"
    SUPERSEDED = "superseded"
    SHUTDOWN = "shutdown"


class RunnerTransferOutcome(StrEnum):
    """Bounded Runner transfer task outcome."""

    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class RunnerTransferFailure(StrEnum):
    """Bounded Runner transfer task failure classification."""

    UNAVAILABLE = "unavailable"
    ALREADY_CLAIMED = "already_claimed"
    RESOURCE_EXHAUSTED = "resource_exhausted"
    DEADLINE_EXCEEDED = "deadline_exceeded"
    CANCELLED = "cancelled"
    INTEGRITY_FAILED = "integrity_failed"
    PROTOCOL_VIOLATION = "protocol_violation"
    STREAM_FAILED = "stream_failed"
    DESTINATION_FAILED = "destination_failed"


@dataclass(frozen=True)
class RunnerTransferIdentity:
    """Runner-visible transfer identity without storage authority."""

    transfer_id: str
    attempt_id: str
    runtime_id: str
    runner_generation: int


@dataclass(frozen=True)
class RunnerTransferIntent:
    """Metadata-only instruction to start one Runner transfer task."""

    identity: RunnerTransferIdentity
    direction: RunnerTransferDirection
    operation_id: str
    owner_session_id: str | None
    runtime_path: str
    overwrite: bool | None
    expected_size: int | None
    expected_sha256: str | None
    deadline_at: datetime
    protocol_version: str
    capability: str
    dispatch_id: str


@dataclass(frozen=True)
class RunnerTransferCancel:
    """Metadata-only instruction to cancel one Runner transfer task."""

    identity: RunnerTransferIdentity
    operation_id: str
    dispatch_id: str
    reason: RunnerTransferCancelReason


@dataclass(frozen=True)
class RunnerTransferResult:
    """Bounded completion report for one Runner transfer task."""

    identity: RunnerTransferIdentity
    operation_id: str
    dispatch_id: str
    direction: RunnerTransferDirection
    outcome: RunnerTransferOutcome
    actual_size: int | None
    sha256: str | None
    destination_committed: bool | None
    failure: RunnerTransferFailure | None

    def __post_init__(self) -> None:
        """Reject contradictory optional-field and outcome combinations."""
        paired_manifest = (self.actual_size is None) == (self.sha256 is None)
        if not paired_manifest:
            raise ValueError("Runner transfer result manifest fields must be paired")
        if self.outcome is RunnerTransferOutcome.SUCCEEDED:
            if (
                self.actual_size is None
                or self.destination_committed is None
                or self.failure is not None
                or (
                    self.direction is RunnerTransferDirection.DOWNLOAD
                    and not self.destination_committed
                )
                or (
                    self.direction is RunnerTransferDirection.UPLOAD
                    and self.destination_committed
                )
            ):
                raise ValueError("Invalid successful Runner transfer result")
            return
        if self.destination_committed is not False or self.failure is None:
            raise ValueError("Failed Runner transfer result requires failure evidence")
        if self.outcome is RunnerTransferOutcome.CANCELLED:
            if self.failure is not RunnerTransferFailure.CANCELLED:
                raise ValueError(
                    "Cancelled Runner transfer result requires cancellation"
                )
            return
        if self.failure is RunnerTransferFailure.CANCELLED:
            raise ValueError("Failed Runner transfer result cannot use cancellation")
        if (
            self.failure is RunnerTransferFailure.DESTINATION_FAILED
            and self.direction is not RunnerTransferDirection.DOWNLOAD
        ):
            raise ValueError("Destination failure is download-only")
