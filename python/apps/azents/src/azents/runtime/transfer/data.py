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


class RuntimeTransferFailure(enum.StrEnum):
    """Bounded failure classification without provider diagnostics."""

    ADMISSION = "admission"
    CANCELLED = "cancelled"
    EXPIRED = "expired"
    FENCED = "fenced"
    INTEGRITY = "integrity"
    STREAM = "stream"
    CONSUMER = "consumer"


@dataclass(frozen=True)
class RuntimeTransferConfig:
    """Explicit transfer-state limits selected by Runtime Control."""

    per_runtime_attempts: int
    per_runtime_bytes: int
    deployment_attempts: int
    deployment_bytes: int
    admission_lease: timedelta
    consumer_lease: timedelta
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
            min(self.admission_lease, self.consumer_lease, self.terminal_ttl)
            <= timedelta()
        ):
            raise ValueError("transfer durations must be positive")
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
        _required(self.transfer_id, "transfer_id")
        _required(self.attempt_id, "attempt_id")
        _required(self.runtime_id, "runtime_id")
        _required(self.operation_id, "operation_id")
        _required(self.runtime_path, "runtime_path")
        _required(self.resource_class, "resource_class")
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
    object: RuntimeTransferObject | None
    actual_size: int | None
    actual_sha256: str | None
    stream_claim_id: str | None
    cancellation_requested_at: datetime | None
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
        if self.actual_size is not None and self.actual_size < 0:
            raise ValueError("actual_size must not be negative")
        _sha(self.actual_sha256)
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
    if admission.source_expires_at is not None and admission.source_expires_at <= now:
        raise ValueError("source_expires_at must be in the future")


def _required(value: str, name: str) -> None:
    if not value:
        raise ValueError(f"{name} must not be empty")


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
