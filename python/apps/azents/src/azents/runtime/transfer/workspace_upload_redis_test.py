"""Private Redis Workspace upload codec and key tests."""

import hashlib
import json
from datetime import datetime, timedelta, timezone

import pytest

from azents.runtime.transfer.workspace_upload import (
    WorkspaceUploadAdmission,
    WorkspaceUploadCleanupStatus,
    WorkspaceUploadDeliveryAttempt,
    WorkspaceUploadPhase,
    WorkspaceUploadRecord,
)
from azents.runtime.transfer.workspace_upload_redis import (
    _MAX_SERIALIZED_RECORD_BYTES,
    _decode_record,
    _encode_record,
    _RedisWorkspaceUploadKeys,
)

_NOW = datetime(2026, 9, 17, tzinfo=timezone.utc)


def _record() -> WorkspaceUploadRecord:
    """Return one record with all serializable domain branches populated."""
    return WorkspaceUploadRecord(
        admission=WorkspaceUploadAdmission(
            upload_id="upload",
            requester_user_id="requester",
            workspace_id="workspace",
            agent_id="agent",
            runtime_id="runtime",
            desired_generation=1,
            session_id="session",
            deadline_at=_NOW + timedelta(minutes=5),
            destination_directory="/workspace/agent",
            filename="report.csv",
            destination_path="/workspace/agent/report.csv",
            expected_size=3,
            media_type="text/csv",
            expected_sha256=hashlib.sha256(b"abc").hexdigest(),
        ),
        phase=WorkspaceUploadPhase.MOVING_TO_RUNTIME,
        revision=2,
        received_size=3,
        ingress_handle="ingress",
        source_handle="opaque-source",
        actual_size=3,
        actual_sha256="a" * 64,
        delivery_attempts=(
            WorkspaceUploadDeliveryAttempt(
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
            ),
        ),
        current_delivery_number=1,
        cancellation_requested_at=None,
        reconciliation_claim_id="reconcile",
        reconciliation_lease_expires_at=_NOW + timedelta(seconds=30),
        cleanup_claim_id=None,
        cleanup_lease_expires_at=None,
        cleanup_status=WorkspaceUploadCleanupStatus.NOT_REQUIRED,
        cleanup_failure=None,
        outcome=None,
        failure=None,
        created_at=_NOW,
        updated_at=_NOW,
        expires_at=_NOW + timedelta(hours=1),
        terminal_expires_at=None,
    )


def test_keys_are_namespaced_and_identifier_safe() -> None:
    """Redis keys isolate upload identifiers from key syntax."""
    keys = _RedisWorkspaceUploadKeys(namespace="azents:runtime:workspace-upload:test")

    record = keys.record("upload:one/two")

    assert "upload:one/two" not in record
    assert record == keys.record("upload:one/two")
    assert record != keys.record("upload:one")
    assert keys.active_index() == "azents:runtime:workspace-upload:test:index:retained"
    with pytest.raises(ValueError):
        _RedisWorkspaceUploadKeys(namespace="")


def test_record_codec_round_trips_exact_metadata_without_binary_body() -> None:
    """Redis stores bounded canonical metadata, not ingress bytes."""
    record = _record()

    encoded = _encode_record(record)

    assert len(encoded) <= _MAX_SERIALIZED_RECORD_BYTES
    assert _decode_record(encoded) == record
    payload: object = json.loads(encoded)
    assert isinstance(payload, dict)
    assert set(payload) == {"record", "version"}
    assert b"data" not in encoded


def test_record_codec_fails_closed_for_schema_and_domain_errors() -> None:
    """Malformed, unknown, and invalid records cannot regain upload authority."""
    encoded = _encode_record(_record())
    payload: object = json.loads(encoded)
    assert isinstance(payload, dict)
    malformed = dict(payload)
    malformed["unknown"] = None
    with pytest.raises(ValueError, match="schema"):
        _decode_record(json.dumps(malformed).encode())
    with pytest.raises(ValueError, match="malformed"):
        _decode_record(b"{")
    with pytest.raises(ValueError, match="maximum serialized"):
        _decode_record(b"x" * (_MAX_SERIALIZED_RECORD_BYTES + 1))


def test_record_codec_rejects_invalid_source_digest() -> None:
    """Redis decoding rejects invalid source metadata before restoring authority."""
    payload: object = json.loads(_encode_record(_record()))
    assert isinstance(payload, dict)
    record_payload = payload["record"]
    assert isinstance(record_payload, dict)
    record_payload["actual_sha256"] = "invalid"

    with pytest.raises(ValueError, match="SHA-256"):
        _decode_record(json.dumps(payload).encode())
