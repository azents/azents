"""Frozen metadata-only Workspace upload domain values."""

import enum
from dataclasses import dataclass
from datetime import datetime, timedelta

WORKSPACE_UPLOAD_MAXIMUM_AGE = timedelta(hours=1)
WORKSPACE_UPLOAD_MAXIMUM_PAGE_SIZE = 1_000
WORKSPACE_UPLOAD_MAXIMUM_DELIVERY_ATTEMPTS = 100
WORKSPACE_UPLOAD_MAXIMUM_CLEANUP_FAILURE_ATTEMPTS = 100


class WorkspaceUploadPhase(enum.StrEnum):
    """Publicly observable Workspace upload lifecycle phase."""

    QUEUED = "queued"
    UPLOADING = "uploading"
    MOVING_TO_RUNTIME = "moving_to_runtime"
    SUCCEEDED = "succeeded"
    CANCELLED = "cancelled"
    CONFLICTED = "conflicted"
    RETRYABLE_FAILURE = "retryable_failure"
    FAILED = "failed"
    EXPIRED = "expired"


class WorkspaceUploadOutcome(enum.StrEnum):
    """Final upload outcome independent from source cleanup."""

    SUCCEEDED = "succeeded"
    CANCELLED = "cancelled"
    FAILED = "failed"
    EXPIRED = "expired"


class WorkspaceUploadFailure(enum.StrEnum):
    """Bounded upload failure classification without provider diagnostics."""

    ADMISSION = "admission"
    AUTHORIZATION = "authorization"
    CANCELLED = "cancelled"
    DESTINATION_CONFLICT = "destination_conflict"
    FENCED = "fenced"
    INGRESS = "ingress"
    INTEGRITY = "integrity"
    RUNTIME = "runtime"
    SIZE = "size"
    EXPIRED = "expired"


class WorkspaceUploadDeliveryOutcome(enum.StrEnum):
    """Immutable terminal result for one Runtime delivery attempt."""

    SUCCEEDED = "succeeded"
    CANCELLED = "cancelled"
    CONFLICTED = "conflicted"
    RETRYABLE_FAILURE = "retryable_failure"
    FAILED = "failed"
    EXPIRED = "expired"


class WorkspaceUploadCleanupStatus(enum.StrEnum):
    """Temporary source cleanup state owned by one upload operation."""

    NOT_REQUIRED = "not_required"
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETE = "complete"
    RETRYABLE_FAILURE = "retryable_failure"


class WorkspaceUploadCleanupArtifact(enum.StrEnum):
    """Stable source artifact classification for cleanup failure evidence."""

    INGRESS_OBJECT_DELETE = "ingress_object_delete"
    SNAPSHOT_OBJECT_DELETE = "snapshot_object_delete"
    MULTIPART_ABORT = "multipart_abort"
    SOURCE_OBJECT_DELETE = "source_object_delete"


@dataclass(frozen=True)
class WorkspaceUploadDestinationEvidence:
    """Bounded safe destination metadata captured at one failed commit."""

    kind: str
    size: int | None
    modified_at: datetime

    def __post_init__(self) -> None:
        """Validate public-safe conflict display metadata."""
        _bounded(self.kind, "destination_evidence.kind", 64)
        if self.size is not None and self.size < 0:
            raise ValueError("destination evidence size must not be negative")
        _aware(self.modified_at, "destination_evidence.modified_at")


@dataclass(frozen=True)
class WorkspaceUploadConfig:
    """Explicit bounded Workspace upload limits selected by Runtime Control."""

    maximum_file_size: int
    maximum_active_uploads_per_requester_agent: int
    maximum_active_bytes_per_requester_agent: int
    maximum_active_uploads: int
    maximum_active_bytes: int
    ingress_lease: timedelta
    reconciliation_lease: timedelta
    cleanup_lease: timedelta
    upload_ttl: timedelta
    terminal_ttl: timedelta
    list_page_size: int

    def __post_init__(self) -> None:
        """Validate positive bounded metadata-store limits."""
        if (
            min(
                self.maximum_file_size,
                self.maximum_active_uploads_per_requester_agent,
                self.maximum_active_bytes_per_requester_agent,
                self.maximum_active_uploads,
                self.maximum_active_bytes,
                self.list_page_size,
            )
            <= 0
        ):
            raise ValueError("Workspace upload limits must be positive")
        if (
            min(
                self.ingress_lease,
                self.reconciliation_lease,
                self.cleanup_lease,
                self.upload_ttl,
                self.terminal_ttl,
            )
            <= timedelta()
        ):
            raise ValueError("Workspace upload durations must be positive")
        if self.upload_ttl > WORKSPACE_UPLOAD_MAXIMUM_AGE:
            raise ValueError("upload_ttl must not exceed one hour")
        if self.terminal_ttl > WORKSPACE_UPLOAD_MAXIMUM_AGE:
            raise ValueError("terminal_ttl must not exceed one hour")
        if self.list_page_size > WORKSPACE_UPLOAD_MAXIMUM_PAGE_SIZE:
            raise ValueError("list_page_size must not exceed 1000")


@dataclass(frozen=True)
class WorkspaceUploadAdmission:
    """Trusted metadata required to create one upload operation."""

    upload_id: str
    requester_user_id: str
    workspace_id: str
    agent_id: str
    runtime_id: str
    desired_generation: int
    session_id: str | None
    deadline_at: datetime
    destination_directory: str
    filename: str
    destination_path: str
    expected_size: int
    media_type: str | None
    expected_sha256: str

    def __post_init__(self) -> None:
        """Validate bounded trusted operation metadata."""
        for value, name in (
            (self.upload_id, "upload_id"),
            (self.requester_user_id, "requester_user_id"),
            (self.workspace_id, "workspace_id"),
            (self.agent_id, "agent_id"),
            (self.runtime_id, "runtime_id"),
        ):
            _bounded(value, name, 128)
        if self.session_id is not None:
            _bounded(self.session_id, "session_id", 128)
        _aware(self.deadline_at, "deadline_at")
        _bounded(self.destination_directory, "destination_directory", 4_096)
        _bounded(self.destination_path, "destination_path", 4_096)
        _bounded(self.filename, "filename", 255)
        if self.filename in {".", ".."} or any(
            separator in self.filename for separator in ("/", "\\", "\x00")
        ):
            raise ValueError("filename must be one basename")
        if self.desired_generation <= 0:
            raise ValueError("desired_generation must be positive")
        if self.expected_size < 0:
            raise ValueError("expected_size must not be negative")
        _sha256(self.expected_sha256)
        if self.media_type is not None:
            _bounded(self.media_type, "media_type", 255)


@dataclass(frozen=True)
class WorkspaceUploadDeliveryAttempt:
    """One ordered Runtime delivery attempt owned by a Workspace upload."""

    number: int
    attempt_id: str
    transfer_id: str
    transfer_attempt_id: str
    overwrite: bool
    conflict_precondition: str | None
    created_at: datetime
    completed_at: datetime | None
    outcome: WorkspaceUploadDeliveryOutcome | None
    failure: WorkspaceUploadFailure | None
    conflict_revision: str | None
    destination_evidence: WorkspaceUploadDestinationEvidence | None

    def __post_init__(self) -> None:
        """Validate one immutable delivery-attempt summary."""
        if not 1 <= self.number <= WORKSPACE_UPLOAD_MAXIMUM_DELIVERY_ATTEMPTS:
            raise ValueError("delivery attempt number is out of bounds")
        for value, name in (
            (self.attempt_id, "attempt_id"),
            (self.transfer_id, "transfer_id"),
            (self.transfer_attempt_id, "transfer_attempt_id"),
        ):
            _bounded(value, name, 128)
        if self.conflict_precondition is not None:
            _bounded(self.conflict_precondition, "conflict_precondition", 512)
        elif self.overwrite:
            raise ValueError("overwrite delivery requires a conflict precondition")
        elif self.overwrite is False and self.conflict_precondition is not None:
            raise ValueError(
                "non-overwrite delivery must not retain a conflict precondition"
            )
        if self.conflict_revision is not None:
            _bounded(self.conflict_revision, "conflict_revision", 512)
        _aware(self.created_at, "created_at")
        if self.completed_at is None:
            if (
                self.outcome is not None
                or self.failure is not None
                or self.conflict_revision is not None
                or self.destination_evidence is not None
            ):
                raise ValueError(
                    "active delivery attempt must not retain terminal state"
                )
            return
        _aware(self.completed_at, "completed_at")
        if self.completed_at < self.created_at:
            raise ValueError("completed_at must not precede created_at")
        if self.outcome is None:
            raise ValueError("completed delivery attempt requires an outcome")
        if self.outcome is WorkspaceUploadDeliveryOutcome.CONFLICTED:
            if (
                self.failure is not WorkspaceUploadFailure.DESTINATION_CONFLICT
                or self.conflict_revision is None
                or self.destination_evidence is None
            ):
                raise ValueError("conflicted delivery requires conflict evidence")
        elif (
            self.conflict_revision is not None or self.destination_evidence is not None
        ):
            raise ValueError("only conflicted delivery may retain conflict evidence")


@dataclass(frozen=True)
class WorkspaceUploadCleanupFailureEvidence:
    """Bounded latest observation for one retryable source-cleanup failure."""

    artifact: WorkspaceUploadCleanupArtifact
    observed_at: datetime
    attempts: int

    def __post_init__(self) -> None:
        """Validate bounded failure evidence."""
        _aware(self.observed_at, "observed_at")
        if not 0 < self.attempts <= WORKSPACE_UPLOAD_MAXIMUM_CLEANUP_FAILURE_ATTEMPTS:
            raise ValueError("cleanup failure attempts must be positive and bounded")


@dataclass(frozen=True)
class WorkspaceUploadRecord:
    """Complete volatile metadata for one requester-bound Workspace upload."""

    admission: WorkspaceUploadAdmission
    phase: WorkspaceUploadPhase
    revision: int
    received_size: int
    ingress_handle: str | None
    source_handle: str | None
    actual_size: int | None
    actual_sha256: str | None
    delivery_attempts: tuple[WorkspaceUploadDeliveryAttempt, ...]
    current_delivery_number: int | None
    cancellation_requested_at: datetime | None
    reconciliation_claim_id: str | None
    reconciliation_lease_expires_at: datetime | None
    cleanup_claim_id: str | None
    cleanup_lease_expires_at: datetime | None
    cleanup_status: WorkspaceUploadCleanupStatus
    cleanup_failure: WorkspaceUploadCleanupFailureEvidence | None
    outcome: WorkspaceUploadOutcome | None
    failure: WorkspaceUploadFailure | None
    created_at: datetime
    updated_at: datetime
    expires_at: datetime
    terminal_expires_at: datetime | None
    ingress_claim_id: str | None = None
    ingress_lease_expires_at: datetime | None = None
    pending_source_handle: str | None = None

    def __post_init__(self) -> None:
        """Validate metadata isolation and lifecycle invariants."""
        if self.revision <= 0:
            raise ValueError("revision must be positive")
        if not 0 <= self.received_size <= self.admission.expected_size:
            raise ValueError("received_size must be within the expected manifest")
        for value, name in (
            (self.created_at, "created_at"),
            (self.updated_at, "updated_at"),
            (self.expires_at, "expires_at"),
        ):
            _aware(value, name)
        if self.updated_at < self.created_at:
            raise ValueError("updated_at must not precede created_at")
        if self.expires_at < self.created_at:
            raise ValueError("expires_at must not precede created_at")
        if self.cancellation_requested_at is not None:
            _aware(self.cancellation_requested_at, "cancellation_requested_at")
        if self.source_handle is None:
            if self.actual_size is not None or self.actual_sha256 is not None:
                raise ValueError("source manifest requires a source handle")
        else:
            _bounded(self.source_handle, "source_handle", 512)
            if self.actual_size is None or self.actual_sha256 is None:
                raise ValueError("source handle requires a verified source manifest")
            if self.actual_size != self.admission.expected_size:
                raise ValueError(
                    "verified source size must match the expected manifest"
                )
            _sha256(self.actual_sha256)
        if self.actual_size is not None and self.actual_size < 0:
            raise ValueError("actual_size must not be negative")
        if self.ingress_handle is not None:
            _bounded(self.ingress_handle, "ingress_handle", 128)
        if self.pending_source_handle is not None:
            _bounded(self.pending_source_handle, "pending_source_handle", 128)
            if self.source_handle is not None:
                raise ValueError(
                    "pending source handle must be cleared before source handle"
                )
        _validate_delivery_attempts(
            self.delivery_attempts,
            self.current_delivery_number,
        )
        _validate_lease(
            self.reconciliation_claim_id,
            self.reconciliation_lease_expires_at,
            "reconciliation",
        )
        _validate_lease(
            self.cleanup_claim_id,
            self.cleanup_lease_expires_at,
            "cleanup",
        )
        _validate_lease(
            self.ingress_claim_id,
            self.ingress_lease_expires_at,
            "ingress",
        )
        if self.cleanup_status is WorkspaceUploadCleanupStatus.IN_PROGRESS:
            if self.cleanup_claim_id is None:
                raise ValueError("cleanup in progress requires a cleanup claim")
        elif self.cleanup_claim_id is not None:
            raise ValueError("cleanup claim requires cleanup in progress")
        if self.cleanup_failure is not None and (
            self.cleanup_status is not WorkspaceUploadCleanupStatus.RETRYABLE_FAILURE
        ):
            raise ValueError(
                "cleanup failure evidence requires retryable cleanup state"
            )
        terminal = workspace_upload_phase_terminal(self.phase)
        if terminal:
            if self.outcome is None or self.terminal_expires_at is None:
                raise ValueError(
                    "terminal upload requires outcome and retention expiry"
                )
            _aware(self.terminal_expires_at, "terminal_expires_at")
        elif self.outcome is not None or self.terminal_expires_at is not None:
            raise ValueError("active upload must not retain terminal outcome")


@dataclass(frozen=True)
class WorkspaceUploadPage:
    """One bounded deterministic Workspace upload store page."""

    records: tuple[WorkspaceUploadRecord, ...]
    cursor: str | None


def workspace_upload_phase_terminal(phase: WorkspaceUploadPhase) -> bool:
    """Return whether an upload phase cannot become retryable again."""
    return phase in {
        WorkspaceUploadPhase.SUCCEEDED,
        WorkspaceUploadPhase.CANCELLED,
        WorkspaceUploadPhase.FAILED,
        WorkspaceUploadPhase.EXPIRED,
    }


def workspace_upload_terminal_expiry(
    now: datetime,
    terminal_ttl: timedelta,
) -> datetime:
    """Return the bounded retention expiry for one terminal upload."""
    _aware(now, "now")
    return now + terminal_ttl


def _bounded(value: str, name: str, maximum: int) -> None:
    """Require one non-empty bounded string."""
    if not value or len(value) > maximum:
        raise ValueError(f"{name} must be non-empty and at most {maximum} characters")


def _aware(value: datetime, name: str) -> None:
    """Require one timezone-aware datetime."""
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")


def _sha256(value: str) -> None:
    """Require one lower-case hexadecimal SHA-256 digest."""
    if len(value) != 64 or any(
        character not in "0123456789abcdef" for character in value
    ):
        raise ValueError("actual_sha256 must be a lower-case SHA-256 digest")


def _validate_delivery_attempts(
    attempts: tuple[WorkspaceUploadDeliveryAttempt, ...],
    current_delivery_number: int | None,
) -> None:
    """Require ordered unique delivery attempts and an exact current child."""
    if len(attempts) > WORKSPACE_UPLOAD_MAXIMUM_DELIVERY_ATTEMPTS:
        raise ValueError("delivery attempt count is out of bounds")
    expected_numbers = tuple(range(1, len(attempts) + 1))
    if tuple(attempt.number for attempt in attempts) != expected_numbers:
        raise ValueError("delivery attempts must be ordered from one without gaps")
    if not attempts:
        if current_delivery_number is not None:
            raise ValueError("current delivery number requires a delivery attempt")
        return
    if current_delivery_number != attempts[-1].number:
        raise ValueError("current delivery number must identify the latest delivery")


def _validate_lease(
    claim_id: str | None,
    expires_at: datetime | None,
    name: str,
) -> None:
    """Require complete claim lease evidence when a claim exists."""
    if claim_id is None:
        if expires_at is not None:
            raise ValueError(f"{name} lease expiry requires a claim")
        return
    _bounded(claim_id, f"{name}_claim_id", 128)
    if expires_at is None:
        raise ValueError(f"{name} claim requires a lease expiry")
    _aware(expires_at, f"{name}_lease_expires_at")
