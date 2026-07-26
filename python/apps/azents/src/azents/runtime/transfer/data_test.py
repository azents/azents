"""Pure Runtime transfer domain tests."""

from datetime import datetime, timedelta, timezone

import pytest

from azents.runtime.transfer.data import (
    RuntimeTransferAdmission,
    RuntimeTransferCleanupStatus,
    RuntimeTransferConfig,
    RuntimeTransferDirection,
    RuntimeTransferDispatchStatus,
    RuntimeTransferPhase,
    RuntimeTransferProgress,
    RuntimeTransferRecord,
    logical_expiry,
    validate_admission_time,
)
from azents.runtime.transfer.policy import phase_transition_allowed

_NOW = datetime(2026, 7, 25, tzinfo=timezone.utc)
_DIGEST = "a" * 64


def _admission(
    *,
    deadline_at: datetime = _NOW + timedelta(minutes=5),
    source_expires_at: datetime | None = None,
) -> RuntimeTransferAdmission:
    return RuntimeTransferAdmission(
        transfer_id="transfer",
        attempt_id="attempt",
        direction=RuntimeTransferDirection.UPLOAD,
        runtime_id="runtime",
        desired_generation=1,
        operation_id="operation",
        session_id=None,
        agent_id=None,
        runtime_path="/workspace/agent/file",
        overwrite=False,
        expected_size=1,
        expected_sha256=_DIGEST,
        product_maximum_size=2,
        provider_maximum_size=2,
        deadline_at=deadline_at,
        source_expires_at=source_expires_at,
        resource_class="default",
    )


def test_logical_expiry_uses_one_hour_or_source_ceiling() -> None:
    """Logical expiry is absolute and source-authoritative."""
    assert logical_expiry(_NOW, None) == _NOW + timedelta(hours=1)
    assert logical_expiry(_NOW, _NOW + timedelta(minutes=10)) == _NOW + timedelta(
        minutes=10
    )
    assert logical_expiry(_NOW, _NOW + timedelta(hours=2)) == _NOW + timedelta(hours=1)


def test_admission_rejects_expired_source_and_invalid_hash() -> None:
    """Admission metadata fails closed for source expiry and invalid SHA values."""
    with pytest.raises(ValueError, match="future"):
        validate_admission_time(_admission(source_expires_at=_NOW), _NOW)
    with pytest.raises(ValueError, match="deadline_at"):
        validate_admission_time(_admission(deadline_at=_NOW), _NOW)
    with pytest.raises(ValueError, match="SHA-256"):
        _admission.__func__ if False else RuntimeTransferAdmission(
            transfer_id="t",
            attempt_id="a",
            direction=RuntimeTransferDirection.UPLOAD,
            runtime_id="r",
            desired_generation=1,
            operation_id="o",
            session_id=None,
            agent_id=None,
            runtime_path="/x",
            overwrite=False,
            expected_size=1,
            expected_sha256="UPPER",
            product_maximum_size=1,
            provider_maximum_size=1,
            deadline_at=_NOW,
            source_expires_at=None,
            resource_class="d",
        )


def test_record_enforces_authoritative_expiry_and_terminal_ceiling() -> None:
    """Records cannot extend logical or terminal metadata expiry."""
    admission = _admission()
    with pytest.raises(ValueError, match="authoritative"):
        RuntimeTransferRecord(
            admission=admission,
            phase=RuntimeTransferPhase.PREPARING,
            revision=1,
            lease_id="lease",
            lease_expires_at=_NOW,
            created_at=_NOW,
            updated_at=_NOW,
            logical_expires_at=_NOW + timedelta(minutes=1),
            accepted_runner_generation=None,
            dispatch_id=None,
            dispatch_status=RuntimeTransferDispatchStatus.NOT_BOUND,
            dispatch_request_id=None,
            object=None,
            actual_size=None,
            actual_sha256=None,
            stream_claim_id=None,
            stream_owner_replica_id=None,
            stream_lease_expires_at=None,
            multipart_cleanup_handle=None,
            completed_object_cleanup_required=False,
            progress=None,
            upload_response_committed_at=None,
            runner_result_confirmed_at=None,
            runner_commit_expires_at=None,
            cancellation_requested_at=None,
            cancellation_reason=None,
            consumer_claim_id=None,
            consumer_lease_expires_at=None,
            consumer_acknowledged_at=None,
            terminal_outcome=None,
            terminal_expires_at=None,
            cleanup_status=RuntimeTransferCleanupStatus.NOT_REQUIRED,
            failure=None,
        )


def test_progress_is_timezone_aware_and_bounded_by_expected_size() -> None:
    """Latest progress evidence remains bounded metadata."""
    progress = RuntimeTransferProgress(bytes_transferred=1, observed_at=_NOW)
    assert progress.bytes_transferred == 1
    with pytest.raises(ValueError, match="negative"):
        RuntimeTransferProgress(bytes_transferred=-1, observed_at=_NOW)

    admission = _admission()
    with pytest.raises(ValueError, match="expected_size"):
        RuntimeTransferRecord(
            admission=admission,
            phase=RuntimeTransferPhase.STREAMING,
            revision=1,
            lease_id="lease",
            lease_expires_at=_NOW + timedelta(minutes=1),
            created_at=_NOW,
            updated_at=_NOW,
            logical_expires_at=_NOW + timedelta(hours=1),
            accepted_runner_generation=1,
            dispatch_id="dispatch",
            dispatch_status=RuntimeTransferDispatchStatus.ENQUEUED,
            dispatch_request_id="request",
            object=None,
            actual_size=None,
            actual_sha256=None,
            stream_claim_id="stream",
            stream_owner_replica_id="replica",
            stream_lease_expires_at=_NOW + timedelta(seconds=30),
            multipart_cleanup_handle=None,
            completed_object_cleanup_required=False,
            progress=RuntimeTransferProgress(bytes_transferred=2, observed_at=_NOW),
            upload_response_committed_at=None,
            runner_result_confirmed_at=None,
            runner_commit_expires_at=None,
            cancellation_requested_at=None,
            cancellation_reason=None,
            consumer_claim_id=None,
            consumer_lease_expires_at=None,
            consumer_acknowledged_at=None,
            terminal_outcome=None,
            terminal_expires_at=None,
            cleanup_status=RuntimeTransferCleanupStatus.NOT_REQUIRED,
            failure=None,
        )


def test_direction_phase_policy_and_cleanup_are_independent() -> None:
    """Upload/download paths differ while terminal cleanup remains separate."""
    assert phase_transition_allowed(
        RuntimeTransferDirection.UPLOAD,
        RuntimeTransferPhase.VERIFYING,
        RuntimeTransferPhase.AVAILABLE,
    )
    assert not phase_transition_allowed(
        RuntimeTransferDirection.DOWNLOAD,
        RuntimeTransferPhase.VERIFYING,
        RuntimeTransferPhase.AVAILABLE,
    )
    assert phase_transition_allowed(
        RuntimeTransferDirection.DOWNLOAD,
        RuntimeTransferPhase.VERIFYING,
        RuntimeTransferPhase.COMMITTED,
    )
    assert phase_transition_allowed(
        RuntimeTransferDirection.UPLOAD,
        RuntimeTransferPhase.CONSUMED,
        RuntimeTransferPhase.TERMINAL,
    )


def test_config_requires_positive_bounded_values() -> None:
    """Transfer configuration rejects invalid limits and retention."""
    with pytest.raises(ValueError, match="positive"):
        RuntimeTransferConfig(
            per_runtime_attempts=0,
            per_runtime_bytes=1,
            deployment_attempts=1,
            deployment_bytes=1,
            admission_lease=timedelta(seconds=1),
            consumer_lease=timedelta(seconds=1),
            stream_lease=timedelta(seconds=1),
            terminal_ttl=timedelta(seconds=1),
            list_page_size=1,
        )
