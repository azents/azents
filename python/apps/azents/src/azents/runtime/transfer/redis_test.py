"""Private Redis Runtime transfer codec and key tests."""

import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from azents.runtime.transfer.data import (
    RuntimeTransferAdmission,
    RuntimeTransferCleanupStatus,
    RuntimeTransferDirection,
    RuntimeTransferDispatchStatus,
    RuntimeTransferFailure,
    RuntimeTransferObject,
    RuntimeTransferOutcome,
    RuntimeTransferPhase,
    RuntimeTransferProgress,
    RuntimeTransferRecord,
    terminal_expiry,
)
from azents.runtime.transfer.redis import (
    _MAX_SERIALIZED_RECORD_BYTES,  # pyright: ignore[reportPrivateUsage]  # Private test seam.
    _decode_record_envelope,  # pyright: ignore[reportPrivateUsage]  # Private test seam.
    _encode_record_envelope,  # pyright: ignore[reportPrivateUsage]  # Private test seam.
    _RedisTransferKeys,  # pyright: ignore[reportPrivateUsage]  # Private test seam.
    _RedisTransferRecordEnvelope,  # pyright: ignore[reportPrivateUsage]  # Private test seam.
    _terminal_bucket_epochs,  # pyright: ignore[reportPrivateUsage]  # Private test seam.
)

_NOW = datetime(2026, 7, 25, 12, tzinfo=timezone(timedelta(hours=9)))
_DIGEST = "a" * 64


def _record() -> RuntimeTransferRecord:
    """Return one record with all optional public fields populated."""
    admission = RuntimeTransferAdmission(
        transfer_id="transfer",
        attempt_id="attempt",
        direction=RuntimeTransferDirection.UPLOAD,
        runtime_id="runtime",
        desired_generation=3,
        operation_id="operation",
        session_id="session",
        agent_id="agent",
        runtime_path="/workspace/file",
        overwrite=True,
        expected_size=3,
        expected_sha256=_DIGEST,
        product_maximum_size=5,
        provider_maximum_size=4,
        deadline_at=_NOW + timedelta(minutes=5),
        source_expires_at=_NOW + timedelta(minutes=30),
        resource_class="default",
    )
    return RuntimeTransferRecord(
        admission=admission,
        phase=RuntimeTransferPhase.TERMINAL,
        revision=7,
        lease_id="lease",
        lease_expires_at=_NOW + timedelta(minutes=1),
        created_at=_NOW,
        updated_at=_NOW + timedelta(minutes=2),
        logical_expires_at=_NOW + timedelta(minutes=30),
        accepted_runner_generation=4,
        dispatch_id="dispatch",
        dispatch_status=RuntimeTransferDispatchStatus.ENQUEUED,
        dispatch_request_id="request",
        object=RuntimeTransferObject("object-key", 3, _DIGEST),
        actual_size=3,
        actual_sha256=_DIGEST,
        stream_claim_id="stream",
        stream_owner_replica_id="replica",
        stream_lease_expires_at=_NOW + timedelta(seconds=30),
        multipart_cleanup_handle="cleanup",
        progress=RuntimeTransferProgress(2, _NOW + timedelta(seconds=30)),
        cancellation_requested_at=_NOW + timedelta(seconds=10),
        consumer_claim_id="consumer",
        consumer_lease_expires_at=_NOW + timedelta(minutes=1),
        consumer_acknowledged_at=_NOW + timedelta(minutes=1, seconds=30),
        terminal_outcome=RuntimeTransferOutcome.CANCELLED,
        terminal_expires_at=_NOW + timedelta(minutes=7),
        cleanup_status=RuntimeTransferCleanupStatus.RETRYABLE_FAILURE,
        failure=RuntimeTransferFailure.CANCELLED,
    )


def _json_payload(record: RuntimeTransferRecord) -> dict[str, object]:
    """Return the encoded envelope JSON as a mutable object."""
    value: object = json.loads(
        _encode_record_envelope(
            _RedisTransferRecordEnvelope(record=record, admission_released=True)
        )
    )
    assert isinstance(value, dict)
    return {str(key): item for key, item in value.items()}


def _record_value(payload: dict[str, object]) -> dict[str, object]:
    """Return the nested record object for one test payload."""
    record = payload["record"]
    assert isinstance(record, dict)
    return record


def _admission_value(payload: dict[str, object]) -> dict[str, object]:
    """Return the nested admission object for one test payload."""
    admission = _record_value(payload)["admission"]
    assert isinstance(admission, dict)
    return admission


def test_keys_are_namespaced_deterministic_and_identifier_safe() -> None:
    """Keys cover transfer state without exposing raw identifier separators."""
    keys = _RedisTransferKeys(namespace="azents:runtime:transfer:test")
    transfer_id = "transfer:one/two"
    attempt_id = "attempt:one/two"
    runtime_id = "runtime:one/two"

    exact = keys.record(transfer_id, attempt_id)
    assert exact == keys.record(transfer_id, attempt_id)
    assert transfer_id not in exact
    assert attempt_id not in exact
    assert runtime_id not in keys.runtime_attempts_counter(runtime_id)
    assert exact != keys.record("transfer", "one/two")
    assert exact != keys.record("transfer:one", "two")
    assert keys.current(transfer_id).startswith("azents:runtime:transfer:test:current:")
    assert keys.stale_index() == "azents:runtime:transfer:test:index:stale"
    assert keys.terminal_bucket(_NOW + timedelta(minutes=7)) == (
        "azents:runtime:transfer:test:index:terminal:"
        f"{int((_NOW + timedelta(minutes=7)).timestamp())}"
    )
    assert (
        keys.deployment_attempts_counter()
        == "azents:runtime:transfer:test:counter:deployment:attempts"
    )
    assert (
        keys.deployment_bytes_counter()
        == "azents:runtime:transfer:test:counter:deployment:bytes"
    )
    assert keys.runtime_attempts_counter(runtime_id).endswith(":attempts")
    assert keys.runtime_bytes_counter(runtime_id).endswith(":bytes")
    assert (
        keys.admission_lease_index()
        == "azents:runtime:transfer:test:index:admission-lease"
    )
    assert (
        keys.consumer_lease_index()
        == "azents:runtime:transfer:test:index:consumer-lease"
    )
    with pytest.raises(ValueError):
        _RedisTransferKeys(namespace="")
    with pytest.raises(ValueError):
        keys.current("")


def test_record_envelope_round_trips_all_public_and_private_evidence() -> None:
    """Codec returns the exact frozen record and private release evidence."""
    record = _record()
    encoded = _encode_record_envelope(
        _RedisTransferRecordEnvelope(record=record, admission_released=True)
    )

    assert len(encoded) <= _MAX_SERIALIZED_RECORD_BYTES
    decoded_json: object = json.loads(encoded)
    assert isinstance(decoded_json, dict)
    assert set(decoded_json) == {"private", "record", "version"}
    assert decoded_json["private"] == {"admission_released": True}
    assert _decode_record_envelope(encoded) == _RedisTransferRecordEnvelope(
        record=record,
        admission_released=True,
    )


def test_fractional_terminal_ttl_bucket_range_includes_aligned_expiry() -> None:
    """Fractional TTLs cannot place live terminal state outside scanned buckets."""
    now = datetime.fromtimestamp(100.9, tz=timezone.utc)
    terminal_ttl = timedelta(seconds=1.5)
    expiry = terminal_expiry(now, terminal_ttl)

    assert int(expiry.timestamp()) in _terminal_bucket_epochs(
        now,
        terminal_ttl,
        expired=False,
    )
    assert int(expiry.timestamp()) in _terminal_bucket_epochs(
        expiry,
        terminal_ttl,
        expired=True,
    )


def test_record_codec_rejects_schema_and_domain_failures() -> None:
    """Malformed, unknown, incomplete, naïve, or invalid state fails closed."""
    record = _record()

    malformed = b"{"
    with pytest.raises(ValueError, match="malformed"):
        _decode_record_envelope(malformed)

    unknown = _json_payload(record)
    unknown["unknown"] = None
    with pytest.raises(ValueError, match="schema"):
        _decode_record_envelope(json.dumps(unknown).encode())

    missing = _json_payload(record)
    del missing["private"]
    with pytest.raises(ValueError, match="schema"):
        _decode_record_envelope(json.dumps(missing).encode())

    wrong_version = _json_payload(record)
    wrong_version["version"] = 3
    with pytest.raises(ValueError, match="version"):
        _decode_record_envelope(json.dumps(wrong_version).encode())

    naive = _json_payload(record)
    _record_value(naive)["created_at"] = "2026-07-25T12:00:00"
    with pytest.raises(ValueError, match="timezone-aware"):
        _decode_record_envelope(json.dumps(naive).encode())

    invalid_enum = _json_payload(record)
    _record_value(invalid_enum)["phase"] = "unknown"
    with pytest.raises(ValueError):
        _decode_record_envelope(json.dumps(invalid_enum).encode())

    invalid_hash = _json_payload(record)
    _admission_value(invalid_hash)["expected_sha256"] = "invalid"
    with pytest.raises(ValueError, match="SHA-256"):
        _decode_record_envelope(json.dumps(invalid_hash).encode())

    invalid_size = _json_payload(record)
    _admission_value(invalid_size)["expected_size"] = -1
    with pytest.raises(ValueError, match="negative"):
        _decode_record_envelope(json.dumps(invalid_size).encode())


def test_record_codec_rejects_oversized_serialization() -> None:
    """Codec rejects records that exceed the conservative byte limit."""
    record = _record()
    oversized = replace(
        record,
        admission=replace(
            record.admission,
            runtime_path="/" + "x" * _MAX_SERIALIZED_RECORD_BYTES,
        ),
    )

    with pytest.raises(ValueError, match="maximum size"):
        _encode_record_envelope(
            _RedisTransferRecordEnvelope(
                record=oversized,
                admission_released=False,
            )
        )
    with pytest.raises(ValueError, match="maximum size"):
        _decode_record_envelope(b"x" * (_MAX_SERIALIZED_RECORD_BYTES + 1))
