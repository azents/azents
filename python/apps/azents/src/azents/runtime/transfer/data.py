"""Frozen metadata-only Runtime transfer domain values."""

import enum
from dataclasses import dataclass
from datetime import datetime, timedelta


class RuntimeTransferDirection(enum.StrEnum):
    """Direction between Control and Runner."""

    DOWNLOAD = "download"
    UPLOAD = "upload"


class RuntimeTransferPhase(enum.StrEnum):
    """Transfer attempt lifecycle phase."""

    PREPARING = "preparing"
    READY = "ready"
    STREAMING = "streaming"
    VERIFYING = "verifying"
    AVAILABLE = "available"
    CONSUMING = "consuming"
    CONSUMED = "consumed"
    COMMITTED = "committed"
    TERMINAL = "terminal"


class RuntimeTransferOutcome(enum.StrEnum):
    """Terminal outcome independent from cleanup."""

    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"
    SUPERSEDED = "superseded"


class RuntimeTransferCleanupStatus(enum.StrEnum):
    """Physical object cleanup outcome."""

    NOT_REQUIRED = "not_required"
    PENDING = "pending"
    COMPLETE = "complete"
    RETRYABLE_FAILURE = "retryable_failure"


class RuntimeTransferDispatchStatus(enum.StrEnum):
    """Durable metadata-only dispatch delivery state."""

    NOT_BOUND = "not_bound"
    BOUND = "bound"
    DELIVERABLE = "deliverable"
    ENQUEUED = "enqueued"


class RuntimeTransferFailure(enum.StrEnum):
    """Bounded failure classification without provider diagnostics."""

    ADMISSION = "admission"
    CANCELLED = "cancelled"
    EXPIRED = "expired"
    FENCED = "fenced"
    INTEGRITY = "integrity"
    STREAM = "stream"
    CONSUMER = "consumer"


class RuntimeTransferCancellationReason(enum.StrEnum):
    """Bounded reason for stopping one transfer attempt."""

    CALLER = "caller"
    DEADLINE = "deadline"
    SUPERSEDED = "superseded"
    SHUTDOWN = "shutdown"


@dataclass(frozen=True)
class RuntimeTransferConfig:
    """Explicit transfer-state limits selected by Runtime Control."""

    per_runtime_attempts: int
    per_runtime_bytes: int
    deployment_attempts: int
    deployment_bytes: int
    admission_lease: timedelta
    consumer_lease: timedelta
    stream_lease: timedelta
    terminal_ttl: timedelta
    list_page_size: int

    def __post_init__(self) -> None:
        """Validate positive bounded limits."""
        if (
            min(
                self.per_runtime_attempts,
                self.per_runtime_bytes,
                self.deployment_attempts,
                self.deployment_bytes,
                self.list_page_size,
            )
            <= 0
        ):
            raise ValueError("transfer limits must be positive")
        if (
            min(
                self.admission_lease,
                self.consumer_lease,
                self.stream_lease,
                self.terminal_ttl,
            )
            <= timedelta()
        ):
            raise ValueError("transfer durations must be positive")
        if self.terminal_ttl < timedelta(seconds=1):
            raise ValueError("terminal_ttl must be at least one second")
        if self.terminal_ttl > timedelta(hours=1):
            raise ValueError("terminal_ttl must not exceed one hour")


@dataclass(frozen=True)
class RuntimeTransferAdmission:
    """Metadata necessary to atomically admit one attempt."""

    transfer_id: str
    attempt_id: str
    direction: RuntimeTransferDirection
    runtime_id: str
    desired_generation: int
    operation_id: str
    session_id: str | None
    agent_id: str | None
    runtime_path: str
    overwrite: bool
    expected_size: int
    expected_sha256: str | None
    product_maximum_size: int
    provider_maximum_size: int
    deadline_at: datetime
    source_expires_at: datetime | None
    resource_class: str

    def __post_init__(self) -> None:
        """Validate trusted admission metadata."""
        _bounded(self.transfer_id, "transfer_id", 128)
        _bounded(self.attempt_id, "attempt_id", 128)
        _bounded(self.runtime_id, "runtime_id", 128)
        _bounded(self.operation_id, "operation_id", 128)
        _bounded(self.runtime_path, "runtime_path", 4096)
        _bounded(self.resource_class, "resource_class", 64)
        if self.session_id is not None:
            _bounded(self.session_id, "session_id", 128)
        if self.agent_id is not None:
            _bounded(self.agent_id, "agent_id", 128)
        if (
            min(
                self.desired_generation,
                self.expected_size,
                self.product_maximum_size,
                self.provider_maximum_size,
            )
            < 0
        ):
            raise ValueError("generations and sizes must not be negative")
        _sha(self.expected_sha256)
        _aware(self.deadline_at, "deadline_at")
        if self.source_expires_at is not None:
            _aware(self.source_expires_at, "source_expires_at")


@dataclass(frozen=True)
class RuntimeTransferObject:
    """Internal object handle with no storage authority."""

    key: str
    size: int
    sha256: str

    def __post_init__(self) -> None:
        _required(self.key, "key")
        if self.size < 0:
            raise ValueError("object size must not be negative")
        _sha(self.sha256)


@dataclass(frozen=True)
class RuntimeTransferProgress:
    """Latest coalesced progress and heartbeat evidence."""

    bytes_transferred: int
    observed_at: datetime

    def __post_init__(self) -> None:
        if self.bytes_transferred < 0:
            raise ValueError("bytes_transferred must not be negative")
        _aware(self.observed_at, "observed_at")


@dataclass(frozen=True)
class RuntimeTransferSettlement:
    """Canonical terminal outcome and failure pair."""

    outcome: RuntimeTransferOutcome
    failure: RuntimeTransferFailure | None


@dataclass(frozen=True)
class RuntimeTransferRecord:
    """Complete metadata-only attempt state."""

    admission: RuntimeTransferAdmission
    phase: RuntimeTransferPhase
    revision: int
    lease_id: str
    lease_expires_at: datetime
    created_at: datetime
    updated_at: datetime
    logical_expires_at: datetime
    accepted_runner_generation: int | None
    dispatch_id: str | None
    dispatch_status: RuntimeTransferDispatchStatus
    dispatch_request_id: str | None
    object: RuntimeTransferObject | None
    actual_size: int | None
    actual_sha256: str | None
    stream_claim_id: str | None
    stream_owner_replica_id: str | None
    stream_lease_expires_at: datetime | None
    multipart_cleanup_handle: str | None
    completed_object_cleanup_required: bool
    progress: RuntimeTransferProgress | None
    upload_response_committed_at: datetime | None
    runner_result_confirmed_at: datetime | None
    runner_commit_expires_at: datetime | None
    cancellation_requested_at: datetime | None
    cancellation_reason: RuntimeTransferCancellationReason | None
    consumer_claim_id: str | None
    consumer_lease_expires_at: datetime | None
    consumer_acknowledged_at: datetime | None
    terminal_outcome: RuntimeTransferOutcome | None
    terminal_expires_at: datetime | None
    cleanup_status: RuntimeTransferCleanupStatus
    failure: RuntimeTransferFailure | None

    def __post_init__(self) -> None:
        if self.revision <= 0:
            raise ValueError("revision must be positive")
        _required(self.lease_id, "lease_id")
        for value, name in (
            (self.lease_expires_at, "lease_expires_at"),
            (self.created_at, "created_at"),
            (self.updated_at, "updated_at"),
            (self.logical_expires_at, "logical_expires_at"),
        ):
            _aware(value, name)
        if self.logical_expires_at != logical_expiry(
            self.created_at, self.admission.source_expires_at
        ):
            raise ValueError(
                "logical_expires_at must be the authoritative absolute expiry"
            )
        if self.accepted_runner_generation is not None and (
            self.accepted_runner_generation <= 0
        ):
            raise ValueError("accepted_runner_generation must be positive")
        if self.dispatch_status is RuntimeTransferDispatchStatus.NOT_BOUND:
            if (
                self.dispatch_id is not None
                or self.dispatch_request_id is not None
                or self.accepted_runner_generation is not None
            ):
                raise ValueError("unbound dispatch must not retain dispatch authority")
        elif (
            self.dispatch_id is None
            or self.dispatch_request_id is None
            or self.accepted_runner_generation is None
        ):
            raise ValueError("bound dispatch requires complete dispatch authority")
        if self.stream_claim_id is None:
            if (
                self.stream_owner_replica_id is not None
                or self.stream_lease_expires_at is not None
            ):
                raise ValueError("stream lease requires a stream claim")
        elif (
            self.stream_owner_replica_id is None or self.stream_lease_expires_at is None
        ):
            raise ValueError("stream claim requires complete owner lease")
        if self.stream_owner_replica_id is not None:
            _required(self.stream_owner_replica_id, "stream_owner_replica_id")
        if self.stream_lease_expires_at is not None:
            _aware(self.stream_lease_expires_at, "stream_lease_expires_at")
        if self.multipart_cleanup_handle is not None:
            _opaque_handle(self.multipart_cleanup_handle, "multipart_cleanup_handle")
        if self.completed_object_cleanup_required and (
            self.object is None
            or self.cleanup_status is not RuntimeTransferCleanupStatus.RETRYABLE_FAILURE
        ):
            raise ValueError(
                "completed object cleanup requires retryable object evidence"
            )
        if self.upload_response_committed_at is not None:
            _aware(
                self.upload_response_committed_at,
                "upload_response_committed_at",
            )
            if (
                self.admission.direction is not RuntimeTransferDirection.UPLOAD
                or self.phase
                not in {
                    RuntimeTransferPhase.AVAILABLE,
                    RuntimeTransferPhase.CONSUMING,
                    RuntimeTransferPhase.CONSUMED,
                    RuntimeTransferPhase.TERMINAL,
                }
                or self.cancellation_requested_at is not None
            ):
                raise ValueError(
                    "Upload response commit requires durable uncancelled availability"
                )
        if self.runner_result_confirmed_at is not None:
            _aware(self.runner_result_confirmed_at, "runner_result_confirmed_at")
            if (
                self.admission.direction is not RuntimeTransferDirection.UPLOAD
                or self.phase
                not in {
                    RuntimeTransferPhase.AVAILABLE,
                    RuntimeTransferPhase.CONSUMING,
                    RuntimeTransferPhase.CONSUMED,
                    RuntimeTransferPhase.TERMINAL,
                }
                or self.cancellation_requested_at is not None
                or self.upload_response_committed_at is None
            ):
                raise ValueError(
                    "Runner result confirmation requires an uncancelled upload"
                )
        if self.runner_commit_expires_at is not None:
            _aware(self.runner_commit_expires_at, "runner_commit_expires_at")
            if self.admission.direction is not RuntimeTransferDirection.DOWNLOAD:
                raise ValueError("Download commit expiry requires a download")
        if (self.cancellation_requested_at is None) != (
            self.cancellation_reason is None
        ):
            raise ValueError("cancellation evidence must be complete")
        if self.actual_size is not None and self.actual_size < 0:
            raise ValueError("actual_size must not be negative")
        _sha(self.actual_sha256)
        if (
            self.progress is not None
            and self.progress.bytes_transferred > self.admission.expected_size
        ):
            raise ValueError("progress must not exceed expected_size")
        if self.terminal_expires_at is not None:
            _aware(self.terminal_expires_at, "terminal_expires_at")
            if self.terminal_expires_at > self.updated_at + timedelta(hours=1):
                raise ValueError("terminal metadata expiry must not exceed one hour")


@dataclass(frozen=True)
class RuntimeTransferPage:
    """Bounded page of metadata records."""

    records: tuple[RuntimeTransferRecord, ...]
    cursor: str | None


def logical_expiry(
    created_at: datetime, source_expires_at: datetime | None
) -> datetime:
    """Return the non-extendable absolute content expiry."""
    _aware(created_at, "created_at")
    expiry = created_at + timedelta(hours=1)
    if source_expires_at is None:
        return expiry
    _aware(source_expires_at, "source_expires_at")
    return min(expiry, source_expires_at)


def validate_admission_time(admission: RuntimeTransferAdmission, now: datetime) -> None:
    """Reject an admission whose authoritative source is already expired."""
    _aware(now, "now")
    if admission.deadline_at <= now:
        raise ValueError("deadline_at must be in the future")
    if admission.source_expires_at is not None and admission.source_expires_at <= now:
        raise ValueError("source_expires_at must be in the future")


def cancellation_settlement(
    reason: RuntimeTransferCancellationReason,
) -> RuntimeTransferSettlement:
    """Return the canonical terminal authority for one cancellation reason."""
    match reason:
        case (
            RuntimeTransferCancellationReason.CALLER
            | RuntimeTransferCancellationReason.SHUTDOWN
        ):
            return RuntimeTransferSettlement(
                RuntimeTransferOutcome.CANCELLED,
                RuntimeTransferFailure.CANCELLED,
            )
        case RuntimeTransferCancellationReason.DEADLINE:
            return RuntimeTransferSettlement(
                RuntimeTransferOutcome.EXPIRED,
                RuntimeTransferFailure.EXPIRED,
            )
        case RuntimeTransferCancellationReason.SUPERSEDED:
            return RuntimeTransferSettlement(
                RuntimeTransferOutcome.SUPERSEDED,
                RuntimeTransferFailure.FENCED,
            )


def valid_settlement(
    outcome: RuntimeTransferOutcome,
    failure: RuntimeTransferFailure | None,
) -> bool:
    """Return whether one terminal pair is canonical."""
    if outcome is RuntimeTransferOutcome.SUCCEEDED:
        return failure is None
    if outcome is RuntimeTransferOutcome.CANCELLED:
        return failure is RuntimeTransferFailure.CANCELLED
    if outcome is RuntimeTransferOutcome.EXPIRED:
        return failure is RuntimeTransferFailure.EXPIRED
    if outcome is RuntimeTransferOutcome.SUPERSEDED:
        return failure is RuntimeTransferFailure.FENCED
    return failure in {
        RuntimeTransferFailure.ADMISSION,
        RuntimeTransferFailure.FENCED,
        RuntimeTransferFailure.INTEGRITY,
        RuntimeTransferFailure.STREAM,
        RuntimeTransferFailure.CONSUMER,
    }


def terminal_expiry(now: datetime, terminal_ttl: timedelta) -> datetime:
    """Return one bucket-aligned terminal metadata expiry."""
    _aware(now, "now")
    raw_expiry = now + terminal_ttl
    quantum_seconds = max(1, int(terminal_ttl.total_seconds()) // 60)
    aligned_epoch = int(raw_expiry.timestamp()) // quantum_seconds * quantum_seconds
    aligned = datetime.fromtimestamp(aligned_epoch, tz=now.tzinfo)
    return aligned if aligned > now else raw_expiry


def _required(value: str, name: str) -> None:
    if not value:
        raise ValueError(f"{name} must not be empty")


def _bounded(value: str, name: str, maximum_bytes: int) -> None:
    _required(value, name)
    if len(value.encode("utf-8")) > maximum_bytes:
        raise ValueError(f"{name} exceeds {maximum_bytes} UTF-8 bytes")


def _aware(value: datetime, name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")


def _sha(value: str | None) -> None:
    if value is not None and (
        len(value) != 64
        or value.lower() != value
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError("SHA-256 must be lowercase hexadecimal")


def _opaque_handle(value: str, name: str) -> None:
    if not value or len(value.encode("utf-8")) > 512 or "://" in value:
        raise ValueError(f"{name} must be a bounded opaque handle")
