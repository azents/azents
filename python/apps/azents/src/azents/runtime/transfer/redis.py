"""Private Redis key and record serialization helpers for Runtime transfers.

This module intentionally contains no Redis client, commands, scripts, or store
implementation. Future adapters may use these bounded helpers without exposing
Redis concerns through the transfer domain or its public store protocol.
"""

import base64
import json
from dataclasses import dataclass
from datetime import datetime

from azents.runtime.transfer.data import (
    RuntimeTransferAdmission,
    RuntimeTransferCleanupStatus,
    RuntimeTransferDirection,
    RuntimeTransferFailure,
    RuntimeTransferObject,
    RuntimeTransferOutcome,
    RuntimeTransferPhase,
    RuntimeTransferProgress,
    RuntimeTransferRecord,
)

_DEFAULT_NAMESPACE = "azents:runtime:transfer"
_RECORD_SCHEMA_VERSION = 1
_MAX_SERIALIZED_RECORD_BYTES = 16 * 1024

_ENVELOPE_FIELDS = frozenset({"version", "record", "private"})
_PRIVATE_FIELDS = frozenset({"admission_released"})
_RECORD_FIELDS = frozenset(
    {
        "admission",
        "phase",
        "revision",
        "lease_id",
        "lease_expires_at",
        "created_at",
        "updated_at",
        "logical_expires_at",
        "accepted_runner_generation",
        "object",
        "actual_size",
        "actual_sha256",
        "stream_claim_id",
        "progress",
        "cancellation_requested_at",
        "consumer_claim_id",
        "consumer_lease_expires_at",
        "consumer_acknowledged_at",
        "terminal_outcome",
        "terminal_expires_at",
        "cleanup_status",
        "failure",
    }
)
_ADMISSION_FIELDS = frozenset(
    {
        "transfer_id",
        "attempt_id",
        "direction",
        "runtime_id",
        "desired_generation",
        "operation_id",
        "session_id",
        "runtime_path",
        "overwrite",
        "expected_size",
        "expected_sha256",
        "product_maximum_size",
        "provider_maximum_size",
        "deadline_at",
        "source_expires_at",
        "resource_class",
    }
)
_OBJECT_FIELDS = frozenset({"key", "size", "sha256"})
_PROGRESS_FIELDS = frozenset({"bytes_transferred", "observed_at"})


@dataclass(frozen=True)
class _RedisTransferKeys:  # pyright: ignore[reportUnusedClass]  # Tested private seam.
    """Deterministic Redis key names under one transfer-only namespace."""

    namespace: str = _DEFAULT_NAMESPACE

    def __post_init__(self) -> None:
        """Validate a non-empty transfer-specific namespace."""
        if not self.namespace or self.namespace.endswith(":"):
            raise ValueError(
                "Redis transfer namespace must be non-empty without ':' suffix"
            )

    def record(self, transfer_id: str, attempt_id: str) -> str:
        """Return one exact transfer attempt record key."""
        return ":".join(
            (
                self.namespace,
                "record",
                _key_component(transfer_id),
                _key_component(attempt_id),
            )
        )

    def current(self, transfer_id: str) -> str:
        """Return the current-attempt pointer key for one transfer."""
        return ":".join((self.namespace, "current", _key_component(transfer_id)))

    def stale_index(self) -> str:
        """Return the shared stale-attempt index key."""
        return f"{self.namespace}:index:stale"

    def terminal_index(self) -> str:
        """Return the shared terminal-attempt index key."""
        return f"{self.namespace}:index:terminal"

    def deployment_attempts_counter(self) -> str:
        """Return the deployment-wide active-attempt counter key."""
        return f"{self.namespace}:counter:deployment:attempts"

    def deployment_bytes_counter(self) -> str:
        """Return the deployment-wide reserved-byte counter key."""
        return f"{self.namespace}:counter:deployment:bytes"

    def runtime_attempts_counter(self, runtime_id: str) -> str:
        """Return one runtime's active-attempt counter key."""
        return ":".join(
            (
                self.namespace,
                "counter",
                "runtime",
                _key_component(runtime_id),
                "attempts",
            )
        )

    def runtime_bytes_counter(self, runtime_id: str) -> str:
        """Return one runtime's reserved-byte counter key."""
        return ":".join(
            (self.namespace, "counter", "runtime", _key_component(runtime_id), "bytes")
        )

    def admission_lease_index(self) -> str:
        """Return the admission-lease expiry index key."""
        return f"{self.namespace}:index:admission-lease"

    def consumer_lease_index(self) -> str:
        """Return the consumer-lease expiry index key."""
        return f"{self.namespace}:index:consumer-lease"


@dataclass(frozen=True)
class _RedisTransferRecordEnvelope:
    """One public record plus private Redis admission-release evidence."""

    record: RuntimeTransferRecord
    admission_released: bool


def _key_component(value: str) -> str:
    """Encode one identifier without exposing Redis key separators."""
    if not value:
        raise ValueError("Redis transfer key identifier must be non-empty")
    encoded = base64.urlsafe_b64encode(value.encode("utf-8")).decode("ascii")
    return encoded.rstrip("=")


def _encode_record_envelope(  # pyright: ignore[reportUnusedFunction]  # Tested private seam.
    envelope: _RedisTransferRecordEnvelope,
) -> bytes:
    """Encode one bounded record envelope as deterministic JSON bytes."""
    _require_bool(envelope.admission_released, "admission_released")
    value = {
        "version": _RECORD_SCHEMA_VERSION,
        "record": _record_to_value(envelope.record),
        "private": {"admission_released": envelope.admission_released},
    }
    encoded = json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    if len(encoded) > _MAX_SERIALIZED_RECORD_BYTES:
        raise ValueError("serialized Runtime transfer record exceeds maximum size")
    return encoded


def _decode_record_envelope(  # pyright: ignore[reportUnusedFunction]  # Tested private seam.
    payload: bytes,
) -> _RedisTransferRecordEnvelope:
    """Decode one bounded, schema-validated record envelope."""
    if len(payload) > _MAX_SERIALIZED_RECORD_BYTES:
        raise ValueError("serialized Runtime transfer record exceeds maximum size")
    try:
        value: object = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("malformed Runtime transfer record JSON") from exc
    envelope = _require_object(value, "record envelope", _ENVELOPE_FIELDS)
    if _require_int(envelope["version"], "version") != _RECORD_SCHEMA_VERSION:
        raise ValueError("unsupported Runtime transfer record schema version")
    private = _require_object(
        envelope["private"], "private record metadata", _PRIVATE_FIELDS
    )
    return _RedisTransferRecordEnvelope(
        record=_record_from_value(envelope["record"]),
        admission_released=_require_bool(
            private["admission_released"],
            "admission_released",
        ),
    )


def _record_to_value(record: RuntimeTransferRecord) -> dict[str, object]:
    """Return a JSON-compatible exact representation of one public record."""
    return {
        "admission": _admission_to_value(record.admission),
        "phase": record.phase.value,
        "revision": record.revision,
        "lease_id": record.lease_id,
        "lease_expires_at": _datetime_to_value(record.lease_expires_at),
        "created_at": _datetime_to_value(record.created_at),
        "updated_at": _datetime_to_value(record.updated_at),
        "logical_expires_at": _datetime_to_value(record.logical_expires_at),
        "accepted_runner_generation": record.accepted_runner_generation,
        "object": None if record.object is None else _object_to_value(record.object),
        "actual_size": record.actual_size,
        "actual_sha256": record.actual_sha256,
        "stream_claim_id": record.stream_claim_id,
        "progress": None
        if record.progress is None
        else _progress_to_value(record.progress),
        "cancellation_requested_at": _optional_datetime_to_value(
            record.cancellation_requested_at
        ),
        "consumer_claim_id": record.consumer_claim_id,
        "consumer_lease_expires_at": _optional_datetime_to_value(
            record.consumer_lease_expires_at
        ),
        "consumer_acknowledged_at": _optional_datetime_to_value(
            record.consumer_acknowledged_at
        ),
        "terminal_outcome": None
        if record.terminal_outcome is None
        else record.terminal_outcome.value,
        "terminal_expires_at": _optional_datetime_to_value(record.terminal_expires_at),
        "cleanup_status": record.cleanup_status.value,
        "failure": None if record.failure is None else record.failure.value,
    }


def _record_from_value(value: object) -> RuntimeTransferRecord:
    """Restore one public record through exact schema and domain validation."""
    record = _require_object(value, "record", _RECORD_FIELDS)
    terminal_outcome = record["terminal_outcome"]
    failure = record["failure"]
    return RuntimeTransferRecord(
        admission=_admission_from_value(record["admission"]),
        phase=RuntimeTransferPhase(_require_string(record["phase"], "phase")),
        revision=_require_int(record["revision"], "revision"),
        lease_id=_require_string(record["lease_id"], "lease_id"),
        lease_expires_at=_datetime_from_value(
            record["lease_expires_at"],
            "lease_expires_at",
        ),
        created_at=_datetime_from_value(record["created_at"], "created_at"),
        updated_at=_datetime_from_value(record["updated_at"], "updated_at"),
        logical_expires_at=_datetime_from_value(
            record["logical_expires_at"],
            "logical_expires_at",
        ),
        accepted_runner_generation=_optional_int(
            record["accepted_runner_generation"],
            "accepted_runner_generation",
        ),
        object=_optional_object_from_value(record["object"]),
        actual_size=_optional_int(record["actual_size"], "actual_size"),
        actual_sha256=_optional_string(record["actual_sha256"], "actual_sha256"),
        stream_claim_id=_optional_string(record["stream_claim_id"], "stream_claim_id"),
        progress=_optional_progress_from_value(record["progress"]),
        cancellation_requested_at=_optional_datetime_from_value(
            record["cancellation_requested_at"],
            "cancellation_requested_at",
        ),
        consumer_claim_id=_optional_string(
            record["consumer_claim_id"],
            "consumer_claim_id",
        ),
        consumer_lease_expires_at=_optional_datetime_from_value(
            record["consumer_lease_expires_at"],
            "consumer_lease_expires_at",
        ),
        consumer_acknowledged_at=_optional_datetime_from_value(
            record["consumer_acknowledged_at"],
            "consumer_acknowledged_at",
        ),
        terminal_outcome=None
        if terminal_outcome is None
        else RuntimeTransferOutcome(
            _require_string(terminal_outcome, "terminal_outcome")
        ),
        terminal_expires_at=_optional_datetime_from_value(
            record["terminal_expires_at"],
            "terminal_expires_at",
        ),
        cleanup_status=RuntimeTransferCleanupStatus(
            _require_string(record["cleanup_status"], "cleanup_status")
        ),
        failure=None
        if failure is None
        else RuntimeTransferFailure(_require_string(failure, "failure")),
    )


def _admission_to_value(admission: RuntimeTransferAdmission) -> dict[str, object]:
    """Return a JSON-compatible exact representation of one admission."""
    return {
        "transfer_id": admission.transfer_id,
        "attempt_id": admission.attempt_id,
        "direction": admission.direction.value,
        "runtime_id": admission.runtime_id,
        "desired_generation": admission.desired_generation,
        "operation_id": admission.operation_id,
        "session_id": admission.session_id,
        "runtime_path": admission.runtime_path,
        "overwrite": admission.overwrite,
        "expected_size": admission.expected_size,
        "expected_sha256": admission.expected_sha256,
        "product_maximum_size": admission.product_maximum_size,
        "provider_maximum_size": admission.provider_maximum_size,
        "deadline_at": _datetime_to_value(admission.deadline_at),
        "source_expires_at": _optional_datetime_to_value(admission.source_expires_at),
        "resource_class": admission.resource_class,
    }


def _admission_from_value(value: object) -> RuntimeTransferAdmission:
    """Restore one admission through exact schema and domain validation."""
    admission = _require_object(value, "admission", _ADMISSION_FIELDS)
    return RuntimeTransferAdmission(
        transfer_id=_require_string(admission["transfer_id"], "transfer_id"),
        attempt_id=_require_string(admission["attempt_id"], "attempt_id"),
        direction=RuntimeTransferDirection(
            _require_string(admission["direction"], "direction")
        ),
        runtime_id=_require_string(admission["runtime_id"], "runtime_id"),
        desired_generation=_require_int(
            admission["desired_generation"],
            "desired_generation",
        ),
        operation_id=_require_string(admission["operation_id"], "operation_id"),
        session_id=_optional_string(admission["session_id"], "session_id"),
        runtime_path=_require_string(admission["runtime_path"], "runtime_path"),
        overwrite=_require_bool(admission["overwrite"], "overwrite"),
        expected_size=_require_int(admission["expected_size"], "expected_size"),
        expected_sha256=_optional_string(
            admission["expected_sha256"],
            "expected_sha256",
        ),
        product_maximum_size=_require_int(
            admission["product_maximum_size"],
            "product_maximum_size",
        ),
        provider_maximum_size=_require_int(
            admission["provider_maximum_size"],
            "provider_maximum_size",
        ),
        deadline_at=_datetime_from_value(admission["deadline_at"], "deadline_at"),
        source_expires_at=_optional_datetime_from_value(
            admission["source_expires_at"],
            "source_expires_at",
        ),
        resource_class=_require_string(admission["resource_class"], "resource_class"),
    )


def _object_to_value(object: RuntimeTransferObject) -> dict[str, object]:
    """Return a JSON-compatible exact representation of one object handle."""
    return {
        "key": object.key,
        "size": object.size,
        "sha256": object.sha256,
    }


def _optional_object_from_value(value: object) -> RuntimeTransferObject | None:
    """Restore an optional object handle."""
    if value is None:
        return None
    object = _require_object(value, "object", _OBJECT_FIELDS)
    return RuntimeTransferObject(
        key=_require_string(object["key"], "object.key"),
        size=_require_int(object["size"], "object.size"),
        sha256=_require_string(object["sha256"], "object.sha256"),
    )


def _progress_to_value(progress: RuntimeTransferProgress) -> dict[str, object]:
    """Return a JSON-compatible exact representation of one progress observation."""
    return {
        "bytes_transferred": progress.bytes_transferred,
        "observed_at": _datetime_to_value(progress.observed_at),
    }


def _optional_progress_from_value(value: object) -> RuntimeTransferProgress | None:
    """Restore an optional progress observation."""
    if value is None:
        return None
    progress = _require_object(value, "progress", _PROGRESS_FIELDS)
    return RuntimeTransferProgress(
        bytes_transferred=_require_int(
            progress["bytes_transferred"],
            "progress.bytes_transferred",
        ),
        observed_at=_datetime_from_value(
            progress["observed_at"], "progress.observed_at"
        ),
    )


def _datetime_to_value(value: datetime) -> str:
    """Serialize one timezone-aware datetime as ISO-8601 text."""
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Runtime transfer datetime must be timezone-aware")
    return value.isoformat()


def _optional_datetime_to_value(value: datetime | None) -> str | None:
    """Serialize an optional timezone-aware datetime."""
    return None if value is None else _datetime_to_value(value)


def _datetime_from_value(value: object, name: str) -> datetime:
    """Restore one timezone-aware ISO-8601 datetime."""
    text = _require_string(value, name)
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"{name} must be an ISO-8601 datetime") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return parsed


def _optional_datetime_from_value(value: object, name: str) -> datetime | None:
    """Restore an optional timezone-aware ISO-8601 datetime."""
    return None if value is None else _datetime_from_value(value, name)


def _require_object(
    value: object,
    name: str,
    fields: frozenset[str],
) -> dict[str, object]:
    """Require an object with exactly the supplied fields."""
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be an object")
    result: dict[str, object] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            raise ValueError(f"{name} field names must be strings")
        result[key] = item
    if frozenset(result) != fields:
        raise ValueError(f"{name} fields do not match the schema")
    return result


def _require_string(value: object, name: str) -> str:
    """Require a string value."""
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a string")
    return value


def _optional_string(value: object, name: str) -> str | None:
    """Require an optional string value."""
    return None if value is None else _require_string(value, name)


def _require_int(value: object, name: str) -> int:
    """Require an integer but reject booleans."""
    if type(value) is not int:
        raise ValueError(f"{name} must be an integer")
    return value


def _optional_int(value: object, name: str) -> int | None:
    """Require an optional integer but reject booleans."""
    return None if value is None else _require_int(value, name)


def _require_bool(value: object, name: str) -> bool:
    """Require a boolean value."""
    if type(value) is not bool:
        raise ValueError(f"{name} must be a boolean")
    return value
