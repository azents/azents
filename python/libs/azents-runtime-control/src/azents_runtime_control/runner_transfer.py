"""Shared Runner Control transfer intent, cancellation, and result values."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class RunnerTransferDirection(StrEnum):
    """Direction of one Runner transfer task."""

    DOWNLOAD = "download"
    UPLOAD = "upload"


class RunnerTransferSourceTransport(StrEnum):
    """Physical source transport selected for a Runner transfer."""

    TRANSFER_OBJECT = "transfer_object"
    DIRECT_OBJECT = "direct_object"


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
    DESTINATION_CONFLICT = "destination_conflict"


@dataclass(frozen=True)
class RunnerTransferIdentity:
    """Runner-visible transfer identity without storage authority."""

    transfer_id: str
    attempt_id: str
    runtime_id: str
    runner_generation: int


@dataclass(frozen=True)
class RunnerTransferDestinationConflictEvidence:
    """Bounded safe metadata observed for one conflicting destination."""

    kind: str
    size: int | None
    modified_at: datetime

    def __post_init__(self) -> None:
        """Validate bounded, public-safe destination metadata."""
        _validate_bounded(self.kind, "destination conflict kind", maximum=64)
        if self.size is not None and self.size < 0:
            raise ValueError("destination conflict size must not be negative")
        if self.modified_at.tzinfo is None or self.modified_at.utcoffset() is None:
            raise ValueError("destination conflict modified_at must be timezone-aware")


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
    conflict_precondition: bytes | None
    source_transport: RunnerTransferSourceTransport = (
        RunnerTransferSourceTransport.TRANSFER_OBJECT
    )

    def __post_init__(self) -> None:
        """Validate bounded opaque overwrite-precondition transport."""
        if not isinstance(self.source_transport, RunnerTransferSourceTransport):
            raise ValueError("source_transport is invalid")
        if (
            self.source_transport is RunnerTransferSourceTransport.DIRECT_OBJECT
            and self.direction is not RunnerTransferDirection.DOWNLOAD
        ):
            raise ValueError("direct object source is download-only")
        if self.conflict_precondition is not None:
            _validate_conflict_precondition(self.conflict_precondition)


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
    conflict_precondition: bytes | None
    destination_conflict: RunnerTransferDestinationConflictEvidence | None

    def __post_init__(self) -> None:
        """Reject contradictory optional-field and outcome combinations."""
        _validate_id(self.identity.transfer_id, "transfer_id")
        _validate_id(self.identity.attempt_id, "attempt_id")
        _validate_id(self.identity.runtime_id, "runtime_id")
        _validate_id(self.operation_id, "operation_id")
        _validate_id(self.dispatch_id, "dispatch_id")
        if self.identity.runner_generation <= 0:
            raise ValueError("runner_generation must be positive")
        if self.actual_size is not None and self.actual_size < 0:
            raise ValueError("actual_size must not be negative")
        if self.sha256 is not None and (
            len(self.sha256) != 64
            or self.sha256.lower() != self.sha256
            or any(character not in "0123456789abcdef" for character in self.sha256)
        ):
            raise ValueError("sha256 must be lowercase hexadecimal")
        paired_manifest = (self.actual_size is None) == (self.sha256 is None)
        if not paired_manifest:
            raise ValueError("Runner transfer result manifest fields must be paired")
        if self.conflict_precondition is not None:
            _validate_conflict_precondition(self.conflict_precondition)
        if self.outcome is RunnerTransferOutcome.SUCCEEDED:
            if (
                self.actual_size is None
                or self.destination_committed is None
                or self.failure is not None
                or self.conflict_precondition is not None
                or self.destination_conflict is not None
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
            if (
                self.failure is not RunnerTransferFailure.CANCELLED
                or self.conflict_precondition is not None
                or self.destination_conflict is not None
            ):
                raise ValueError(
                    "Cancelled Runner transfer result requires cancellation"
                )
            return
        if self.failure is RunnerTransferFailure.CANCELLED:
            raise ValueError("Failed Runner transfer result cannot use cancellation")
        if self.failure is RunnerTransferFailure.DESTINATION_CONFLICT:
            if (
                self.direction is not RunnerTransferDirection.DOWNLOAD
                or self.conflict_precondition is None
                or self.destination_conflict is None
            ):
                raise ValueError(
                    "Destination conflict requires download conflict evidence"
                )
            return
        if (
            self.conflict_precondition is not None
            or self.destination_conflict is not None
        ):
            raise ValueError(
                "Only destination conflict results carry conflict evidence"
            )
        if self.failure is RunnerTransferFailure.DESTINATION_FAILED:
            if self.direction is not RunnerTransferDirection.DOWNLOAD:
                raise ValueError("Destination failure is download-only")


def _validate_id(value: str, name: str) -> None:
    _validate_bounded(value, name, maximum=128)


def _validate_bounded(value: str, name: str, *, maximum: int) -> None:
    size = len(value.encode())
    if size < 1 or size > maximum:
        raise ValueError(f"{name} must be between 1 and {maximum} UTF-8 bytes")


def _validate_conflict_precondition(value: bytes) -> None:
    if not 1 <= len(value) <= 512:
        raise ValueError("conflict_precondition must be between 1 and 512 bytes")
