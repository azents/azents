"""Focused Workspace upload domain tests."""

import hashlib
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from azents.runtime.transfer.workspace_upload import (
    WorkspaceUploadAdmission,
    WorkspaceUploadCleanupStatus,
    WorkspaceUploadConfig,
    WorkspaceUploadDeliveryAttempt,
    WorkspaceUploadDeliveryOutcome,
    WorkspaceUploadFailure,
    WorkspaceUploadOutcome,
    WorkspaceUploadPhase,
    WorkspaceUploadRecord,
)

_NOW = datetime(2026, 9, 17, tzinfo=timezone.utc)


def _admission() -> WorkspaceUploadAdmission:
    """Return one bounded requester-bound upload admission."""
    return WorkspaceUploadAdmission(
        upload_id="upload",
        requester_user_id="requester",
        workspace_id="workspace",
        agent_id="agent",
        runtime_id="runtime",
        desired_generation=1,
        session_id=None,
        deadline_at=_NOW + timedelta(minutes=5),
        destination_directory="/workspace/agent",
        filename="report.csv",
        destination_path="/workspace/agent/report.csv",
        expected_size=3,
        media_type="text/csv",
        expected_sha256=hashlib.sha256(b"abc").hexdigest(),
    )


def _record(
    *,
    phase: WorkspaceUploadPhase = WorkspaceUploadPhase.QUEUED,
    source_handle: str | None = None,
    actual_size: int | None = None,
    actual_sha256: str | None = None,
    delivery_attempts: tuple[WorkspaceUploadDeliveryAttempt, ...] = (),
    current_delivery_number: int | None = None,
    outcome: WorkspaceUploadOutcome | None = None,
    failure: WorkspaceUploadFailure | None = None,
    terminal_expires_at: datetime | None = None,
) -> WorkspaceUploadRecord:
    """Return one valid upload record with selected fields replaced."""
    return WorkspaceUploadRecord(
        admission=_admission(),
        phase=phase,
        revision=1,
        received_size=0,
        ingress_handle=None,
        source_handle=source_handle,
        actual_size=actual_size,
        actual_sha256=actual_sha256,
        delivery_attempts=delivery_attempts,
        current_delivery_number=current_delivery_number,
        cancellation_requested_at=None,
        reconciliation_claim_id=None,
        reconciliation_lease_expires_at=None,
        cleanup_claim_id=None,
        cleanup_lease_expires_at=None,
        cleanup_status=WorkspaceUploadCleanupStatus.NOT_REQUIRED,
        cleanup_failure=None,
        outcome=outcome,
        failure=failure,
        created_at=_NOW,
        updated_at=_NOW,
        expires_at=_NOW + timedelta(hours=1),
        terminal_expires_at=terminal_expires_at,
    )


def test_config_rejects_unbounded_retention_and_invalid_limits() -> None:
    """Upload metadata remains bounded by the existing one-hour lifetime."""
    with pytest.raises(ValueError, match="one hour"):
        WorkspaceUploadConfig(
            maximum_file_size=10,
            maximum_active_uploads_per_requester_agent=1,
            maximum_active_bytes_per_requester_agent=10,
            maximum_active_uploads=1,
            maximum_active_bytes=10,
            ingress_lease=timedelta(seconds=1),
            reconciliation_lease=timedelta(seconds=1),
            cleanup_lease=timedelta(seconds=1),
            upload_ttl=timedelta(hours=1, seconds=1),
            terminal_ttl=timedelta(seconds=1),
            list_page_size=1,
        )
    with pytest.raises(ValueError, match="positive"):
        WorkspaceUploadConfig(
            maximum_file_size=0,
            maximum_active_uploads_per_requester_agent=1,
            maximum_active_bytes_per_requester_agent=10,
            maximum_active_uploads=1,
            maximum_active_bytes=10,
            ingress_lease=timedelta(seconds=1),
            reconciliation_lease=timedelta(seconds=1),
            cleanup_lease=timedelta(seconds=1),
            upload_ttl=timedelta(seconds=1),
            terminal_ttl=timedelta(seconds=1),
            list_page_size=1,
        )


def test_admission_rejects_pathlike_filenames() -> None:
    """Filename remains a basename rather than a second path authority."""
    with pytest.raises(ValueError, match="basename"):
        replace(_admission(), filename="../report.csv")


def test_record_requires_verified_source_and_ordered_delivery_attempts() -> None:
    """Source manifest and delivery identity cannot become ambiguous."""
    with pytest.raises(ValueError, match="source handle"):
        _record(actual_size=3, actual_sha256="a" * 64)
    first = WorkspaceUploadDeliveryAttempt(
        number=1,
        attempt_id="delivery",
        transfer_id="transfer",
        transfer_attempt_id="transfer-attempt",
        overwrite=False,
        conflict_precondition=None,
        created_at=_NOW,
        completed_at=None,
        outcome=None,
        failure=None,
        conflict_revision=None,
        destination_evidence=None,
    )
    with pytest.raises(ValueError, match="latest delivery"):
        _record(delivery_attempts=(first,), current_delivery_number=None)


def test_conflicted_delivery_requires_opaque_conflict_evidence() -> None:
    """A conflict outcome cannot authorize overwrite without exact evidence."""
    with pytest.raises(ValueError, match="conflict evidence"):
        WorkspaceUploadDeliveryAttempt(
            number=1,
            attempt_id="delivery",
            transfer_id="transfer",
            transfer_attempt_id="transfer-attempt",
            overwrite=False,
            conflict_precondition=None,
            created_at=_NOW,
            completed_at=_NOW + timedelta(seconds=1),
            outcome=WorkspaceUploadDeliveryOutcome.CONFLICTED,
            failure=WorkspaceUploadFailure.DESTINATION_CONFLICT,
            conflict_revision=None,
            destination_evidence=None,
        )


def test_terminal_record_requires_outcome_and_retention_expiry() -> None:
    """Final operation state remains explicit and bounded."""
    with pytest.raises(ValueError, match="terminal upload"):
        _record(phase=WorkspaceUploadPhase.FAILED)
    record = _record(
        phase=WorkspaceUploadPhase.FAILED,
        outcome=WorkspaceUploadOutcome.FAILED,
        failure=WorkspaceUploadFailure.INGRESS,
        terminal_expires_at=_NOW + timedelta(minutes=1),
    )
    assert record.phase is WorkspaceUploadPhase.FAILED
