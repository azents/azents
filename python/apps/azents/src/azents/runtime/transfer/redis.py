"""Redis-backed metadata-only Runtime transfer state."""

import asyncio
import base64
import dataclasses
import json
import math
import secrets
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import AsyncContextManager, Protocol, cast

from redis.asyncio import Redis
from redis.exceptions import WatchError

from azents.runtime.transfer.data import (
    RuntimeTransferAdmission,
    RuntimeTransferCleanupStatus,
    RuntimeTransferConfig,
    RuntimeTransferDirection,
    RuntimeTransferFailure,
    RuntimeTransferObject,
    RuntimeTransferOutcome,
    RuntimeTransferPage,
    RuntimeTransferPhase,
    RuntimeTransferProgress,
    RuntimeTransferRecord,
    logical_expiry,
    terminal_expiry,
    validate_admission_time,
)
from azents.runtime.transfer.policy import phase_transition_allowed

_DEFAULT_NAMESPACE = "azents:runtime:transfer"
_RECORD_SCHEMA_VERSION = 1
_MAX_SERIALIZED_RECORD_BYTES = 16 * 1024
_LOCK_TTL_MILLISECONDS = 5_000
_LOCK_ACQUIRE_TIMEOUT_SECONDS = 5.0
_LOCK_RETRY_SECONDS = 0.01
_RELEASE_LOCK_SCRIPT = """
if redis.call("GET", KEYS[1]) == ARGV[1] then
  return redis.call("DEL", KEYS[1])
end
return 0
"""


class _RedisTransferPipeline(Protocol):
    """Redis pipeline methods used by the transfer adapter."""

    async def __aenter__(self) -> "_RedisTransferPipeline": ...

    async def __aexit__(
        self,
        exc_type: object,
        exc_value: object,
        traceback: object,
    ) -> bool | None: ...

    async def watch(self, *keys: str) -> object: ...

    async def get(self, name: str) -> object: ...

    def multi(self) -> None: ...

    def set(
        self,
        name: str,
        value: str | bytes,
        *,
        keepttl: bool = False,
    ) -> object: ...

    def pexpire(self, name: str, time: int, *, lt: bool) -> object: ...

    def delete(self, *names: str) -> object: ...

    def zadd(self, name: str, mapping: dict[str, float]) -> object: ...

    def zrem(self, name: str, *values: str) -> object: ...

    async def execute(self) -> object: ...


class _RedisTransferClient(Protocol):
    """Redis commands used by the transfer adapter."""

    async def set(
        self,
        name: str,
        value: str | bytes,
        *,
        nx: bool,
        px: int,
    ) -> bool | None: ...

    async def get(self, name: str) -> object: ...

    async def mget(self, keys: list[str]) -> list[object]: ...

    async def zrange(self, name: str, start: int, end: int) -> list[object]: ...

    async def zrangebylex(
        self,
        name: str,
        minimum: str,
        maximum: str,
        *,
        start: int,
        num: int,
    ) -> list[object]: ...

    async def eval(self, script: str, numkeys: int, *keys_and_args: str) -> object: ...

    def pipeline(
        self, *, transaction: bool
    ) -> AsyncContextManager[_RedisTransferPipeline]: ...


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
class _RedisTransferKeys:
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

    def terminal_bucket(self, expires_at: datetime) -> str:
        """Return one TTL-bound terminal-attempt index bucket."""
        return f"{self.namespace}:index:terminal:{int(expires_at.timestamp())}"

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

    def active_index(self) -> str:
        """Return the bounded active-attempt index key."""
        return f"{self.namespace}:index:active"

    def mutation_lock(self) -> str:
        """Return the namespace-wide mutation lock key."""
        return f"{self.namespace}:lock:mutation"


@dataclass(frozen=True)
class _RedisTransferRecordEnvelope:
    """One public record plus private Redis admission-release evidence."""

    record: RuntimeTransferRecord
    admission_released: bool


@dataclass(frozen=True)
class _RedisStaleCursor:
    """Opaque stale-list continuation state."""

    kind: str
    member: str
    bucket_epoch: int | None


def _key_component(value: str) -> str:
    """Encode one identifier without exposing Redis key separators."""
    if not value:
        raise ValueError("Redis transfer key identifier must be non-empty")
    encoded = base64.urlsafe_b64encode(value.encode("utf-8")).decode("ascii")
    return encoded.rstrip("=")


def _encode_record_envelope(
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


def _decode_record_envelope(
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


class RedisRuntimeTransferStateStore:
    """Redis implementation of metadata-only Runtime transfer state.

    A token-owned namespace lock serializes bounded state changes across processes.
    Each write is committed through ``WATCH``/``MULTI``/``EXEC`` against that lock,
    so ownership expiry aborts rather than allowing an unfenced mutation.
    """

    def __init__(
        self,
        *,
        redis: Redis,
        config: RuntimeTransferConfig,
        clock: Callable[[], datetime],
        namespace: str = _DEFAULT_NAMESPACE,
    ) -> None:
        """Initialize transfer state dependencies."""
        self.redis = cast(_RedisTransferClient, redis)
        self.config = config
        self.clock = clock
        self.keys = _RedisTransferKeys(namespace)

    async def admit(
        self, admission: RuntimeTransferAdmission, *, lease_id: str
    ) -> RuntimeTransferRecord | None:
        """Atomically admit one new transfer attempt."""
        now = self._now()
        async with self._locked() as token:
            entries = await self._load_reclaimed_entries(now)
            record_key = self.keys.record(admission.transfer_id, admission.attempt_id)
            existing = await self._load_entry(entries, record_key, now)
            if existing is not None:
                await self._commit(token, entries, now)
                return existing.record
            try:
                validate_admission_time(admission, now)
            except ValueError:
                await self._commit(token, entries, now)
                return None
            current = await self._load_current_entry(
                entries,
                admission.transfer_id,
                now,
            )
            if (
                current is not None
                and current[1].record.phase is not RuntimeTransferPhase.TERMINAL
            ):
                await self._commit(token, entries, now)
                return None
            if admission.expected_size > min(
                admission.product_maximum_size,
                admission.provider_maximum_size,
            ) or not self._has_capacity(entries, admission):
                await self._commit(token, entries, now)
                return None
            record = RuntimeTransferRecord(
                admission=admission,
                phase=RuntimeTransferPhase.PREPARING,
                revision=1,
                lease_id=lease_id,
                lease_expires_at=now + self.config.admission_lease,
                created_at=now,
                updated_at=now,
                logical_expires_at=logical_expiry(now, admission.source_expires_at),
                accepted_runner_generation=None,
                object=None,
                actual_size=None,
                actual_sha256=None,
                stream_claim_id=None,
                progress=None,
                cancellation_requested_at=None,
                consumer_claim_id=None,
                consumer_lease_expires_at=None,
                consumer_acknowledged_at=None,
                terminal_outcome=None,
                terminal_expires_at=None,
                cleanup_status=RuntimeTransferCleanupStatus.NOT_REQUIRED,
                failure=None,
            )
            entries[record_key] = _RedisTransferRecordEnvelope(
                record=record,
                admission_released=False,
            )
            await self._commit(
                token,
                entries,
                now,
                pointer_sets={self.keys.current(admission.transfer_id): record_key},
            )
            return record

    async def get(self, transfer_id: str) -> RuntimeTransferRecord | None:
        """Return the current attempt while reclaiming due bounded state."""
        now = self._now()
        async with self._locked() as token:
            entries = await self._load_reclaimed_entries(now)
            current_key = await self._current_key(transfer_id)
            if current_key is None:
                await self._commit(token, entries, now)
                return None
            stored = await self._load_record(current_key)
            expired_bucket_removals: dict[str, set[str]] = {}
            if stored is not None and _terminal_expired(stored.record, now):
                terminal_expiry_at = stored.record.terminal_expires_at
                assert terminal_expiry_at is not None
                expired_bucket_removals[
                    self.keys.terminal_bucket(terminal_expiry_at)
                ] = {current_key}
            envelope = await self._load_entry(entries, current_key, now)
            if envelope is None:
                await self._commit(
                    token,
                    entries,
                    now,
                    pointer_deletes={self.keys.current(transfer_id)},
                    record_deletes={current_key},
                    terminal_bucket_removals=expired_bucket_removals,
                )
                return None
            await self._commit(token, entries, now)
            return envelope.record

    async def mark_ready(
        self,
        transfer_id: str,
        *,
        attempt_id: str,
        runtime_id: str,
        desired_generation: int,
        expected_revision: int,
        object: RuntimeTransferObject,
    ) -> RuntimeTransferRecord | None:
        """Move a PREPARING attempt to READY under runtime fencing."""
        return await self._move(
            transfer_id,
            attempt_id=attempt_id,
            expected_revision=expected_revision,
            current=RuntimeTransferPhase.PREPARING,
            target=RuntimeTransferPhase.READY,
            runtime_id=runtime_id,
            desired_generation=desired_generation,
            object=object,
            claim_id=None,
            accepted_runner_generation=None,
        )

    async def claim_stream(
        self,
        transfer_id: str,
        *,
        attempt_id: str,
        runtime_id: str,
        desired_generation: int,
        accepted_runner_generation: int,
        expected_revision: int,
        claim_id: str,
    ) -> RuntimeTransferRecord | None:
        """Claim a READY attempt for one Runner stream."""
        return await self._move(
            transfer_id,
            attempt_id=attempt_id,
            expected_revision=expected_revision,
            current=RuntimeTransferPhase.READY,
            target=RuntimeTransferPhase.STREAMING,
            runtime_id=runtime_id,
            desired_generation=desired_generation,
            object=None,
            claim_id=claim_id,
            accepted_runner_generation=accepted_runner_generation,
        )

    async def record_progress(
        self,
        transfer_id: str,
        *,
        attempt_id: str,
        runtime_id: str,
        desired_generation: int,
        accepted_runner_generation: int,
        claim_id: str,
        expected_revision: int,
        bytes_transferred: int,
    ) -> RuntimeTransferRecord | None:
        """Store the latest monotonic stream progress."""
        now = self._now()
        async with self._locked() as token:
            entries = await self._load_reclaimed_entries(now)
            key, envelope = await self._load_exact_entry(
                entries,
                transfer_id,
                attempt_id,
                now,
            )
            if not await self._active_matches(
                transfer_id,
                key,
                envelope,
                expected_revision,
                RuntimeTransferPhase.STREAMING,
                now,
                runtime_id=runtime_id,
                desired_generation=desired_generation,
                accepted_runner_generation=accepted_runner_generation,
                claim_id=claim_id,
            ) or (
                envelope is not None
                and (
                    bytes_transferred > envelope.record.admission.expected_size
                    or (
                        envelope.record.progress is not None
                        and bytes_transferred
                        < envelope.record.progress.bytes_transferred
                    )
                )
            ):
                await self._commit(token, entries, now)
                return None
            assert key is not None and envelope is not None
            record = dataclasses.replace(
                envelope.record,
                revision=envelope.record.revision + 1,
                updated_at=now,
                progress=RuntimeTransferProgress(bytes_transferred, now),
            )
            entries[key] = dataclasses.replace(envelope, record=record)
            await self._commit(token, entries, now)
            return record

    async def request_cancellation(
        self, transfer_id: str, *, attempt_id: str, expected_revision: int
    ) -> RuntimeTransferRecord | None:
        """Record idempotent cancellation evidence for one exact attempt."""
        now = self._now()
        async with self._locked() as token:
            entries = await self._load_reclaimed_entries(now)
            key, envelope = await self._load_exact_entry(
                entries,
                transfer_id,
                attempt_id,
                now,
            )
            if envelope is None:
                await self._commit(token, entries, now)
                return None
            if envelope.record.cancellation_requested_at is not None:
                await self._commit(token, entries, now)
                return (
                    envelope.record
                    if expected_revision <= envelope.record.revision
                    else None
                )
            if envelope.record.revision != expected_revision:
                await self._commit(token, entries, now)
                return None
            if envelope.record.phase is RuntimeTransferPhase.TERMINAL:
                await self._commit(token, entries, now)
                return envelope.record
            assert key is not None
            record = dataclasses.replace(
                envelope.record,
                revision=envelope.record.revision + 1,
                updated_at=now,
                cancellation_requested_at=now,
            )
            entries[key] = dataclasses.replace(envelope, record=record)
            await self._commit(token, entries, now)
            return record

    async def begin_verification(
        self,
        transfer_id: str,
        *,
        attempt_id: str,
        runtime_id: str,
        desired_generation: int,
        accepted_runner_generation: int,
        claim_id: str,
        expected_revision: int,
    ) -> RuntimeTransferRecord | None:
        """Move a STREAMING attempt to VERIFYING."""
        return await self._move(
            transfer_id,
            attempt_id=attempt_id,
            expected_revision=expected_revision,
            current=RuntimeTransferPhase.STREAMING,
            target=RuntimeTransferPhase.VERIFYING,
            runtime_id=None,
            desired_generation=None,
            object=None,
            claim_id=None,
            accepted_runner_generation=None,
            required_runtime_id=runtime_id,
            required_desired_generation=desired_generation,
            required_runner_generation=accepted_runner_generation,
            required_claim_id=claim_id,
        )

    async def publish_available(
        self,
        transfer_id: str,
        *,
        attempt_id: str,
        runtime_id: str,
        desired_generation: int,
        accepted_runner_generation: int,
        claim_id: str,
        expected_revision: int,
        actual_size: int,
        actual_sha256: str,
    ) -> RuntimeTransferRecord | None:
        """Complete upload verification as AVAILABLE."""
        return await self._complete_phase(
            transfer_id,
            attempt_id=attempt_id,
            expected_revision=expected_revision,
            target=RuntimeTransferPhase.AVAILABLE,
            actual_size=actual_size,
            actual_sha256=actual_sha256,
            runtime_id=runtime_id,
            desired_generation=desired_generation,
            accepted_runner_generation=accepted_runner_generation,
            claim_id=claim_id,
        )

    async def mark_committed(
        self,
        transfer_id: str,
        *,
        attempt_id: str,
        runtime_id: str,
        desired_generation: int,
        accepted_runner_generation: int,
        claim_id: str,
        expected_revision: int,
        actual_size: int,
        actual_sha256: str,
    ) -> RuntimeTransferRecord | None:
        """Complete download verification as COMMITTED."""
        return await self._complete_phase(
            transfer_id,
            attempt_id=attempt_id,
            expected_revision=expected_revision,
            target=RuntimeTransferPhase.COMMITTED,
            actual_size=actual_size,
            actual_sha256=actual_sha256,
            runtime_id=runtime_id,
            desired_generation=desired_generation,
            accepted_runner_generation=accepted_runner_generation,
            claim_id=claim_id,
        )

    async def claim_consumer(
        self,
        transfer_id: str,
        *,
        attempt_id: str,
        expected_revision: int,
        claim_id: str,
    ) -> RuntimeTransferRecord | None:
        """Claim one AVAILABLE upload for a consumer."""
        now = self._now()
        async with self._locked() as token:
            entries = await self._load_reclaimed_entries(now)
            key, envelope = await self._load_exact_entry(
                entries,
                transfer_id,
                attempt_id,
                now,
            )
            if not await self._active_matches(
                transfer_id,
                key,
                envelope,
                expected_revision,
                RuntimeTransferPhase.AVAILABLE,
                now,
            ) or (
                envelope is not None and envelope.record.consumer_claim_id is not None
            ):
                await self._commit(token, entries, now)
                return None
            assert key is not None and envelope is not None
            record = dataclasses.replace(
                envelope.record,
                phase=RuntimeTransferPhase.CONSUMING,
                revision=envelope.record.revision + 1,
                updated_at=now,
                consumer_claim_id=claim_id,
                consumer_lease_expires_at=now + self.config.consumer_lease,
            )
            entries[key] = dataclasses.replace(envelope, record=record)
            await self._commit(token, entries, now)
            return record

    async def acknowledge_consumer(
        self,
        transfer_id: str,
        *,
        attempt_id: str,
        expected_revision: int,
        claim_id: str,
    ) -> RuntimeTransferRecord | None:
        """Acknowledge one correctly claimed consumer transfer."""
        return await self._resolve_consumer(
            transfer_id,
            attempt_id=attempt_id,
            expected_revision=expected_revision,
            claim_id=claim_id,
            target=RuntimeTransferPhase.CONSUMED,
            acknowledged=True,
        )

    async def abandon_consumer(
        self,
        transfer_id: str,
        *,
        attempt_id: str,
        expected_revision: int,
        claim_id: str,
    ) -> RuntimeTransferRecord | None:
        """Return one correctly claimed consumer transfer to AVAILABLE."""
        return await self._resolve_consumer(
            transfer_id,
            attempt_id=attempt_id,
            expected_revision=expected_revision,
            claim_id=claim_id,
            target=RuntimeTransferPhase.AVAILABLE,
            acknowledged=False,
        )

    async def settle(
        self,
        transfer_id: str,
        *,
        attempt_id: str,
        expected_revision: int,
        outcome: RuntimeTransferOutcome,
        failure: RuntimeTransferFailure | None,
    ) -> RuntimeTransferRecord | None:
        """Settle one exact attempt without touching a newer current attempt."""
        now = self._now()
        async with self._locked() as token:
            entries = await self._load_reclaimed_entries(now)
            key, envelope = await self._load_exact_entry(
                entries,
                transfer_id,
                attempt_id,
                now,
            )
            if envelope is None:
                await self._commit(token, entries, now)
                return None
            record = envelope.record
            if record.phase is RuntimeTransferPhase.TERMINAL:
                await self._commit(token, entries, now)
                return (
                    record
                    if expected_revision <= record.revision
                    and record.terminal_outcome is outcome
                    and record.failure is failure
                    else None
                )
            if record.revision != expected_revision:
                await self._commit(token, entries, now)
                return None
            if (
                record.cancellation_requested_at is not None
                and outcome is RuntimeTransferOutcome.SUCCEEDED
            ):
                await self._commit(token, entries, now)
                return None
            if outcome is RuntimeTransferOutcome.SUCCEEDED and (
                key is None
                or await self._current_key(transfer_id) != key
                or envelope.admission_released
                or record.lease_expires_at <= now
                or record.logical_expires_at <= now
                or (
                    record.admission.direction is RuntimeTransferDirection.DOWNLOAD
                    and record.phase is not RuntimeTransferPhase.COMMITTED
                )
                or (
                    record.admission.direction is RuntimeTransferDirection.UPLOAD
                    and record.phase is not RuntimeTransferPhase.CONSUMED
                )
            ):
                await self._commit(token, entries, now)
                return None
            assert key is not None
            settled = dataclasses.replace(
                record,
                phase=RuntimeTransferPhase.TERMINAL,
                revision=record.revision + 1,
                updated_at=now,
                terminal_outcome=outcome,
                failure=failure,
                terminal_expires_at=terminal_expiry(now, self.config.terminal_ttl),
            )
            entries[key] = dataclasses.replace(envelope, record=settled)
            await self._commit(token, entries, now)
            return settled

    async def record_cleanup(
        self,
        transfer_id: str,
        *,
        attempt_id: str,
        expected_revision: int,
        status: RuntimeTransferCleanupStatus,
    ) -> RuntimeTransferRecord | None:
        """Record cleanup evidence independently from transfer terminal state."""
        now = self._now()
        async with self._locked() as token:
            entries = await self._load_reclaimed_entries(now)
            key, envelope = await self._load_exact_entry(
                entries,
                transfer_id,
                attempt_id,
                now,
            )
            if envelope is None:
                await self._commit(token, entries, now)
                return None
            if envelope.record.cleanup_status is status:
                await self._commit(token, entries, now)
                return (
                    envelope.record
                    if expected_revision <= envelope.record.revision
                    else None
                )
            if envelope.record.revision != expected_revision:
                await self._commit(token, entries, now)
                return None
            assert key is not None
            record = dataclasses.replace(
                envelope.record,
                revision=envelope.record.revision + 1,
                updated_at=now,
                cleanup_status=status,
            )
            entries[key] = dataclasses.replace(envelope, record=record)
            await self._commit(token, entries, now)
            return record

    async def release_admission(
        self, transfer_id: str, *, attempt_id: str, lease_id: str
    ) -> RuntimeTransferRecord | None:
        """Release one exact admission lease idempotently."""
        now = self._now()
        async with self._locked() as token:
            entries = await self._load_reclaimed_entries(now)
            key, envelope = await self._load_exact_entry(
                entries,
                transfer_id,
                attempt_id,
                now,
            )
            if envelope is None or envelope.record.lease_id != lease_id:
                await self._commit(token, entries, now)
                return None
            if envelope.admission_released:
                await self._commit(token, entries, now)
                return envelope.record
            assert key is not None
            entries[key] = dataclasses.replace(envelope, admission_released=True)
            await self._commit(token, entries, now)
            return envelope.record

    async def list_stale(
        self, *, cursor: str | None, limit: int
    ) -> RuntimeTransferPage:
        """List one bounded stale page across live and TTL-bound indexes."""
        now = self._now()
        async with self._locked() as token:
            entries = await self._load_reclaimed_entries(now)
            if limit <= 0 or limit > self.config.list_page_size:
                await self._commit(token, entries, now)
                raise ValueError("invalid page limit")
            state = None if cursor is None else _decode_stale_cursor(cursor)
            await self._commit(token, entries, now)
            records: list[RuntimeTransferRecord] = []
            deleted: set[str] = set()
            pointer_deletes: set[str] = set()
            bucket_removals: dict[str, set[str]] = {}
            next_cursor: str | None = None

            if state is None or state.kind == "stale":
                minimum = "-" if state is None else f"({state.member}"
                members = _decode_redis_texts(
                    await self.redis.zrangebylex(
                        self.keys.stale_index(),
                        minimum,
                        "+",
                        start=0,
                        num=limit + 1,
                    )
                )
                last_member: str | None = None
                for member in members:
                    if len(records) == limit:
                        break
                    last_member = member
                    envelope = await self._load_entry(entries, member, now)
                    if envelope is None:
                        deleted.add(member)
                        continue
                    if envelope.record.phase is RuntimeTransferPhase.TERMINAL:
                        continue
                    records.append(envelope.record)
                if last_member is not None and (
                    len(records) == limit or len(members) == limit + 1
                ):
                    next_cursor = _encode_stale_cursor(
                        _RedisStaleCursor("stale", last_member, None)
                    )

            if (
                next_cursor is None
                and len(records) < limit
                and (state is None or state.kind in {"stale", "terminal"})
            ):
                for bucket_epoch in _terminal_bucket_epochs(
                    now,
                    self.config.terminal_ttl,
                    expired=False,
                ):
                    if (
                        state is not None
                        and state.kind == "terminal"
                        and state.bucket_epoch is not None
                        and bucket_epoch < state.bucket_epoch
                    ):
                        continue
                    bucket = self.keys.terminal_bucket(
                        datetime.fromtimestamp(bucket_epoch, tz=now.tzinfo)
                    )
                    minimum = (
                        f"({state.member}"
                        if (
                            state is not None
                            and state.kind == "terminal"
                            and state.bucket_epoch == bucket_epoch
                        )
                        else "-"
                    )
                    remaining = limit - len(records)
                    members = _decode_redis_texts(
                        await self.redis.zrangebylex(
                            bucket,
                            minimum,
                            "+",
                            start=0,
                            num=remaining + 1,
                        )
                    )
                    last_member = None
                    for member in members:
                        if len(records) == limit:
                            break
                        last_member = member
                        envelope = await self._load_entry(entries, member, now)
                        if envelope is None:
                            deleted.add(member)
                            bucket_removals.setdefault(bucket, set()).add(member)
                            transfer_id = self._record_transfer_id(member)
                            if await self._current_key(transfer_id) == member:
                                pointer_deletes.add(self.keys.current(transfer_id))
                            continue
                        if envelope.record.phase is not RuntimeTransferPhase.TERMINAL:
                            bucket_removals.setdefault(bucket, set()).add(member)
                            continue
                        records.append(envelope.record)
                    if last_member is not None and (
                        len(records) == limit or len(members) == remaining + 1
                    ):
                        next_cursor = _encode_stale_cursor(
                            _RedisStaleCursor(
                                "terminal",
                                last_member,
                                bucket_epoch,
                            )
                        )
                        break

            await self._commit(
                token,
                entries,
                now,
                pointer_deletes=pointer_deletes,
                record_deletes=deleted,
                terminal_bucket_removals=bucket_removals,
            )
            return RuntimeTransferPage(records=tuple(records), cursor=next_cursor)

    async def purge_terminal(self, *, limit: int) -> int:
        """Purge at most ``limit`` terminal records whose retention has elapsed."""
        now = self._now()
        async with self._locked() as token:
            entries = await self._load_reclaimed_entries(now)
            if limit <= 0:
                await self._commit(token, entries, now)
                raise ValueError("limit must be positive")
            deleted: set[str] = set()
            pointer_deletes: set[str] = set()
            bucket_removals: dict[str, set[str]] = {}
            bucket_deletes: set[str] = set()
            for bucket_epoch in _terminal_bucket_epochs(
                now,
                self.config.terminal_ttl,
                expired=True,
            ):
                remaining = limit - len(deleted)
                if remaining <= 0:
                    break
                bucket = self.keys.terminal_bucket(
                    datetime.fromtimestamp(bucket_epoch, tz=now.tzinfo)
                )
                members = _decode_redis_texts(
                    await self.redis.zrangebylex(
                        bucket,
                        "-",
                        "+",
                        start=0,
                        num=remaining,
                    )
                )
                for member in members:
                    envelope = await self._load_record(member)
                    bucket_removals.setdefault(bucket, set()).add(member)
                    if envelope is not None and not _terminal_expired(
                        envelope.record,
                        now,
                    ):
                        continue
                    transfer_id = (
                        self._record_transfer_id(member)
                        if envelope is None
                        else envelope.record.admission.transfer_id
                    )
                    if await self._current_key(transfer_id) == member:
                        pointer_deletes.add(self.keys.current(transfer_id))
                    entries.pop(member, None)
                    deleted.add(member)
                if len(members) < remaining:
                    bucket_deletes.add(bucket)
            await self._commit(
                token,
                entries,
                now,
                pointer_deletes=pointer_deletes,
                record_deletes=deleted,
                terminal_bucket_removals=bucket_removals,
                terminal_bucket_deletes=bucket_deletes,
            )
            return len(deleted)

    async def _move(
        self,
        transfer_id: str,
        *,
        attempt_id: str,
        expected_revision: int,
        current: RuntimeTransferPhase,
        target: RuntimeTransferPhase,
        runtime_id: str | None,
        desired_generation: int | None,
        object: RuntimeTransferObject | None,
        claim_id: str | None,
        accepted_runner_generation: int | None,
        required_runtime_id: str | None = None,
        required_desired_generation: int | None = None,
        required_runner_generation: int | None = None,
        required_claim_id: str | None = None,
    ) -> RuntimeTransferRecord | None:
        """Apply one runtime-fenced phase transition."""
        now = self._now()
        async with self._locked() as token:
            entries = await self._load_reclaimed_entries(now)
            key, envelope = await self._load_exact_entry(
                entries,
                transfer_id,
                attempt_id,
                now,
            )
            if (
                not await self._active_matches(
                    transfer_id,
                    key,
                    envelope,
                    expected_revision,
                    current,
                    now,
                    runtime_id=required_runtime_id,
                    desired_generation=required_desired_generation,
                    accepted_runner_generation=required_runner_generation,
                    claim_id=required_claim_id,
                )
                or (
                    envelope is not None
                    and (
                        runtime_id is not None
                        and envelope.record.admission.runtime_id != runtime_id
                    )
                )
                or (
                    envelope is not None
                    and (
                        desired_generation is not None
                        and envelope.record.admission.desired_generation
                        != desired_generation
                    )
                )
                or (
                    envelope is not None
                    and target is RuntimeTransferPhase.READY
                    and (
                        object is None
                        or object.size != envelope.record.admission.expected_size
                        or (
                            envelope.record.admission.expected_sha256 is not None
                            and object.sha256
                            != envelope.record.admission.expected_sha256
                        )
                    )
                )
                or (
                    envelope is not None
                    and not phase_transition_allowed(
                        envelope.record.admission.direction,
                        current,
                        target,
                    )
                )
            ):
                await self._commit(token, entries, now)
                return None
            assert key is not None and envelope is not None
            record = dataclasses.replace(
                envelope.record,
                phase=target,
                revision=envelope.record.revision + 1,
                updated_at=now,
                object=object if object is not None else envelope.record.object,
                stream_claim_id=claim_id
                if claim_id is not None
                else envelope.record.stream_claim_id,
                accepted_runner_generation=accepted_runner_generation
                if accepted_runner_generation is not None
                else envelope.record.accepted_runner_generation,
            )
            entries[key] = dataclasses.replace(envelope, record=record)
            await self._commit(token, entries, now)
            return record

    async def _complete_phase(
        self,
        transfer_id: str,
        *,
        attempt_id: str,
        expected_revision: int,
        target: RuntimeTransferPhase,
        actual_size: int,
        actual_sha256: str,
        runtime_id: str,
        desired_generation: int,
        accepted_runner_generation: int,
        claim_id: str,
    ) -> RuntimeTransferRecord | None:
        """Complete one VERIFYING attempt on its direction-valid path."""
        now = self._now()
        async with self._locked() as token:
            entries = await self._load_reclaimed_entries(now)
            key, envelope = await self._load_exact_entry(
                entries,
                transfer_id,
                attempt_id,
                now,
            )
            if not await self._active_matches(
                transfer_id,
                key,
                envelope,
                expected_revision,
                RuntimeTransferPhase.VERIFYING,
                now,
                runtime_id=runtime_id,
                desired_generation=desired_generation,
                accepted_runner_generation=accepted_runner_generation,
                claim_id=claim_id,
            ) or (
                envelope is not None
                and (
                    actual_size != envelope.record.admission.expected_size
                    or envelope.record.object is None
                    or actual_size != envelope.record.object.size
                    or actual_sha256 != envelope.record.object.sha256
                    or (
                        envelope.record.admission.expected_sha256 is not None
                        and actual_sha256 != envelope.record.admission.expected_sha256
                    )
                    or not phase_transition_allowed(
                        envelope.record.admission.direction,
                        envelope.record.phase,
                        target,
                    )
                )
            ):
                await self._commit(token, entries, now)
                return None
            assert key is not None and envelope is not None
            record = dataclasses.replace(
                envelope.record,
                phase=target,
                revision=envelope.record.revision + 1,
                updated_at=now,
                actual_size=actual_size,
                actual_sha256=actual_sha256,
            )
            entries[key] = dataclasses.replace(envelope, record=record)
            await self._commit(token, entries, now)
            return record

    async def _resolve_consumer(
        self,
        transfer_id: str,
        *,
        attempt_id: str,
        expected_revision: int,
        claim_id: str,
        target: RuntimeTransferPhase,
        acknowledged: bool,
    ) -> RuntimeTransferRecord | None:
        """Resolve one CONSUMING attempt as consumed or available."""
        now = self._now()
        async with self._locked() as token:
            entries = await self._load_reclaimed_entries(now)
            key, envelope = await self._load_exact_entry(
                entries,
                transfer_id,
                attempt_id,
                now,
            )
            if not await self._active_matches(
                transfer_id,
                key,
                envelope,
                expected_revision,
                RuntimeTransferPhase.CONSUMING,
                now,
            ) or (
                envelope is not None and envelope.record.consumer_claim_id != claim_id
            ):
                await self._commit(token, entries, now)
                return None
            assert key is not None and envelope is not None
            record = dataclasses.replace(
                envelope.record,
                phase=target,
                revision=envelope.record.revision + 1,
                updated_at=now,
                consumer_claim_id=(
                    envelope.record.consumer_claim_id if acknowledged else None
                ),
                consumer_lease_expires_at=None,
                consumer_acknowledged_at=now if acknowledged else None,
            )
            entries[key] = dataclasses.replace(envelope, record=record)
            await self._commit(token, entries, now)
            return record

    def _now(self) -> datetime:
        """Capture one authoritative timezone-aware time value."""
        now = self.clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("clock must return timezone-aware datetime")
        return now

    @asynccontextmanager
    async def _locked(self) -> AsyncIterator[str]:
        """Acquire one bounded token-owned cross-process mutation lock."""
        token = secrets.token_urlsafe(32)
        deadline = asyncio.get_running_loop().time() + _LOCK_ACQUIRE_TIMEOUT_SECONDS
        while True:
            acquired = await self.redis.set(
                self.keys.mutation_lock(),
                token,
                nx=True,
                px=_LOCK_TTL_MILLISECONDS,
            )
            if acquired:
                break
            if asyncio.get_running_loop().time() >= deadline:
                raise TimeoutError("timed out acquiring Runtime transfer mutation lock")
            await asyncio.sleep(_LOCK_RETRY_SECONDS)
        operation_failed = False
        try:
            yield token
        except BaseException:
            operation_failed = True
            raise
        finally:
            released = await self.redis.eval(
                _RELEASE_LOCK_SCRIPT,
                1,
                self.keys.mutation_lock(),
                token,
            )
            if (
                _redis_integer(released, "mutation lock release") != 1
                and not operation_failed
            ):
                raise RuntimeError("Runtime transfer mutation lock ownership was lost")

    async def _load_reclaimed_entries(
        self,
        now: datetime,
    ) -> dict[str, _RedisTransferRecordEnvelope]:
        """Load the bounded active set and apply due lease reclamation."""
        members = _decode_redis_texts(
            await self.redis.zrange(
                self.keys.active_index(),
                0,
                self.config.deployment_attempts,
            )
        )
        if len(members) > self.config.deployment_attempts:
            raise RuntimeError("Runtime transfer active index exceeds configured bound")
        if not members:
            return {}
        raw_records = await self.redis.mget(members)
        if len(raw_records) != len(members):
            raise RuntimeError(
                "Redis returned an incomplete Runtime transfer active set"
            )
        entries: dict[str, _RedisTransferRecordEnvelope] = {}
        for member, raw in zip(members, raw_records, strict=True):
            if raw is None:
                raise RuntimeError(
                    "Runtime transfer active index references a missing record"
                )
            entries[member] = _decode_record_envelope(_redis_bytes(raw))
        for key, envelope in tuple(entries.items()):
            entries[key] = self._reclaim(envelope, now)
        return entries

    async def _load_exact_entry(
        self,
        entries: dict[str, _RedisTransferRecordEnvelope],
        transfer_id: str,
        attempt_id: str,
        now: datetime,
    ) -> tuple[str | None, _RedisTransferRecordEnvelope | None]:
        """Load one exact attempt and add it to the mutation state."""
        key = self.keys.record(transfer_id, attempt_id)
        return key, await self._load_entry(entries, key, now)

    async def _load_current_entry(
        self,
        entries: dict[str, _RedisTransferRecordEnvelope],
        transfer_id: str,
        now: datetime,
    ) -> tuple[str, _RedisTransferRecordEnvelope] | None:
        """Load one current pointer target and add it to mutation state."""
        key = await self._current_key(transfer_id)
        if key is None:
            return None
        envelope = await self._load_entry(entries, key, now)
        if envelope is None:
            return None
        return key, envelope

    async def _current_key(self, transfer_id: str) -> str | None:
        """Return one validated current record key."""
        value = await self.redis.get(self.keys.current(transfer_id))
        if value is None:
            return None
        key = _decode_redis_text(value)
        if not key.startswith(f"{self.keys.namespace}:record:"):
            raise RuntimeError(
                "Runtime transfer current pointer is outside its namespace"
            )
        return key

    async def _load_entry(
        self,
        entries: dict[str, _RedisTransferRecordEnvelope],
        key: str,
        now: datetime,
    ) -> _RedisTransferRecordEnvelope | None:
        """Load one record at most once and apply due direct expiry."""
        existing = entries.get(key)
        if existing is not None:
            return existing
        envelope = await self._load_record(key)
        if envelope is None:
            return None
        if _terminal_expired(envelope.record, now):
            return None
        reclaimed = self._reclaim(envelope, now)
        entries[key] = reclaimed
        return reclaimed

    def _record_transfer_id(self, key: str) -> str:
        """Decode the transfer identifier from one namespaced record key."""
        prefix = f"{self.keys.namespace}:record:"
        if not key.startswith(prefix):
            raise RuntimeError("Runtime transfer record key is outside its namespace")
        components = key[len(prefix) :].split(":")
        if len(components) != 2:
            raise RuntimeError("Runtime transfer record key is malformed")
        return _decode_key_component(components[0])

    async def _load_record(self, key: str) -> _RedisTransferRecordEnvelope | None:
        """Load one exact bounded record envelope."""
        value = await self.redis.get(key)
        return None if value is None else _decode_record_envelope(_redis_bytes(value))

    def _reclaim(
        self,
        envelope: _RedisTransferRecordEnvelope,
        now: datetime,
    ) -> _RedisTransferRecordEnvelope:
        """Apply all due logical, consumer, and admission lease expiry."""
        record = envelope.record
        admission_released = envelope.admission_released
        if (
            record.phase is not RuntimeTransferPhase.TERMINAL
            and record.logical_expires_at <= now
        ):
            record = dataclasses.replace(
                record,
                phase=RuntimeTransferPhase.TERMINAL,
                revision=record.revision + 1,
                updated_at=now,
                terminal_outcome=RuntimeTransferOutcome.EXPIRED,
                failure=RuntimeTransferFailure.EXPIRED,
                terminal_expires_at=terminal_expiry(now, self.config.terminal_ttl),
            )
            admission_released = True
        if (
            record.phase is RuntimeTransferPhase.CONSUMING
            and record.consumer_lease_expires_at is not None
            and record.consumer_lease_expires_at <= now
        ):
            record = dataclasses.replace(
                record,
                phase=RuntimeTransferPhase.AVAILABLE,
                revision=record.revision + 1,
                updated_at=now,
                consumer_claim_id=None,
                consumer_lease_expires_at=None,
            )
        if record.lease_expires_at <= now:
            admission_released = True
        return dataclasses.replace(
            envelope,
            record=record,
            admission_released=admission_released,
        )

    async def _active_matches(
        self,
        transfer_id: str,
        key: str | None,
        envelope: _RedisTransferRecordEnvelope | None,
        expected_revision: int,
        phase: RuntimeTransferPhase,
        now: datetime,
        *,
        runtime_id: str | None = None,
        desired_generation: int | None = None,
        accepted_runner_generation: int | None = None,
        claim_id: str | None = None,
    ) -> bool:
        """Return whether one exact current attempt remains active and fenced."""
        if key is None or envelope is None:
            return False
        if await self._current_key(transfer_id) != key:
            return False
        return (
            key == self.keys.record(transfer_id, envelope.record.admission.attempt_id)
            and not envelope.admission_released
            and envelope.record.revision == expected_revision
            and envelope.record.phase is phase
            and envelope.record.lease_expires_at > now
            and envelope.record.logical_expires_at > now
            and envelope.record.cancellation_requested_at is None
            and (
                runtime_id is None or envelope.record.admission.runtime_id == runtime_id
            )
            and (
                desired_generation is None
                or envelope.record.admission.desired_generation == desired_generation
            )
            and (
                accepted_runner_generation is None
                or envelope.record.accepted_runner_generation
                == accepted_runner_generation
            )
            and (claim_id is None or envelope.record.stream_claim_id == claim_id)
        )

    def _has_capacity(
        self,
        entries: dict[str, _RedisTransferRecordEnvelope],
        admission: RuntimeTransferAdmission,
    ) -> bool:
        """Return whether one admission fits bounded active counters."""
        active = [
            envelope.record
            for envelope in entries.values()
            if _capacity_active(envelope)
        ]
        runtime = [
            record
            for record in active
            if record.admission.runtime_id == admission.runtime_id
        ]
        return (
            len(active) < self.config.deployment_attempts
            and len(runtime) < self.config.per_runtime_attempts
            and sum(record.admission.expected_size for record in active)
            + admission.expected_size
            <= self.config.deployment_bytes
            and sum(record.admission.expected_size for record in runtime)
            + admission.expected_size
            <= self.config.per_runtime_bytes
        )

    async def _commit(
        self,
        token: str,
        entries: dict[str, _RedisTransferRecordEnvelope],
        now: datetime,
        *,
        pointer_sets: dict[str, str] | None = None,
        pointer_deletes: set[str] | None = None,
        record_deletes: set[str] | None = None,
        terminal_bucket_removals: dict[str, set[str]] | None = None,
        terminal_bucket_deletes: set[str] | None = None,
    ) -> None:
        """Persist bounded records, indexes, and counters under lock ownership."""
        active = {
            key: envelope
            for key, envelope in entries.items()
            if _capacity_active(envelope)
        }
        if len(active) > self.config.deployment_attempts:
            raise RuntimeError("Runtime transfer active state exceeds configured bound")
        runtime_ids = {
            envelope.record.admission.runtime_id for envelope in entries.values()
        }
        runtime_records: dict[str, list[RuntimeTransferRecord]] = {}
        for envelope in active.values():
            runtime_records.setdefault(
                envelope.record.admission.runtime_id,
                [],
            ).append(envelope.record)
        pending_pointer_sets = pointer_sets or {}
        pointer_expiries: dict[str, int] = {}
        for key, envelope in entries.items():
            record = envelope.record
            pointer = self.keys.current(record.admission.transfer_id)
            if (
                record.phase is RuntimeTransferPhase.TERMINAL
                and record.terminal_expires_at is not None
                and pointer not in pending_pointer_sets
                and await self._current_key(record.admission.transfer_id) == key
            ):
                pointer_expiries[pointer] = _terminal_retention_milliseconds(
                    record,
                    now,
                )
        await self._owned_transaction(
            token,
            lambda pipeline: self._queue_commit(
                pipeline,
                entries,
                now,
                active,
                runtime_ids,
                runtime_records,
                pending_pointer_sets,
                pointer_deletes or set(),
                record_deletes or set(),
                pointer_expiries,
                terminal_bucket_removals or {},
                terminal_bucket_deletes or set(),
            ),
        )

    async def _owned_transaction(
        self,
        token: str,
        queue: Callable[[_RedisTransferPipeline], None],
    ) -> None:
        """Execute queued writes only while the mutation lock token is owned."""
        async with self.redis.pipeline(transaction=True) as pipeline:
            await pipeline.watch(self.keys.mutation_lock())
            owner = await pipeline.get(self.keys.mutation_lock())
            if owner is None or _decode_redis_text(owner) != token:
                raise RuntimeError("Runtime transfer mutation lock ownership was lost")
            pipeline.multi()
            queue(pipeline)
            try:
                await pipeline.execute()
            except WatchError as exc:
                raise RuntimeError(
                    "Runtime transfer mutation lock changed before commit"
                ) from exc

    def _queue_commit(
        self,
        pipeline: _RedisTransferPipeline,
        entries: dict[str, _RedisTransferRecordEnvelope],
        now: datetime,
        active: dict[str, _RedisTransferRecordEnvelope],
        runtime_ids: set[str],
        runtime_records: dict[str, list[RuntimeTransferRecord]],
        pointer_sets: dict[str, str],
        pointer_deletes: set[str],
        record_deletes: set[str],
        pointer_expiries: dict[str, int],
        terminal_bucket_removals: dict[str, set[str]],
        terminal_bucket_deletes: set[str],
    ) -> None:
        """Queue one owner-fenced bounded state rewrite."""
        for key, envelope in entries.items():
            pipeline.set(key, _encode_record_envelope(envelope), keepttl=True)
            if envelope.record.terminal_expires_at is not None:
                pipeline.pexpire(
                    key,
                    _terminal_retention_milliseconds(envelope.record, now),
                    lt=True,
                )
            self._queue_indexes(pipeline, key, envelope, key in active, now)
        for key in record_deletes:
            pipeline.delete(key)
            pipeline.zrem(self.keys.active_index(), key)
            pipeline.zrem(self.keys.stale_index(), key)
            pipeline.zrem(self.keys.admission_lease_index(), key)
            pipeline.zrem(self.keys.consumer_lease_index(), key)
        for bucket, members in terminal_bucket_removals.items():
            if members:
                pipeline.zrem(bucket, *members)
        for bucket in terminal_bucket_deletes:
            pipeline.delete(bucket)
        pipeline.delete(
            self.keys.deployment_attempts_counter(),
            self.keys.deployment_bytes_counter(),
        )
        if active:
            records = [envelope.record for envelope in active.values()]
            pipeline.set(self.keys.deployment_attempts_counter(), str(len(records)))
            pipeline.set(
                self.keys.deployment_bytes_counter(),
                str(sum(record.admission.expected_size for record in records)),
            )
        for runtime_id in runtime_ids:
            pipeline.delete(
                self.keys.runtime_attempts_counter(runtime_id),
                self.keys.runtime_bytes_counter(runtime_id),
            )
        for runtime_id, records in runtime_records.items():
            pipeline.set(
                self.keys.runtime_attempts_counter(runtime_id), str(len(records))
            )
            pipeline.set(
                self.keys.runtime_bytes_counter(runtime_id),
                str(sum(record.admission.expected_size for record in records)),
            )
        for pointer, record_key in pointer_sets.items():
            pipeline.set(pointer, record_key)
        for pointer, retention_milliseconds in pointer_expiries.items():
            pipeline.pexpire(pointer, retention_milliseconds, lt=True)
        for pointer in pointer_deletes:
            pipeline.delete(pointer)

    def _queue_indexes(
        self,
        pipeline: _RedisTransferPipeline,
        key: str,
        envelope: _RedisTransferRecordEnvelope,
        active: bool,
        now: datetime,
    ) -> None:
        """Queue all exact index membership for one record envelope."""
        record = envelope.record
        if active:
            pipeline.zadd(
                self.keys.active_index(), {key: record.created_at.timestamp()}
            )
            pipeline.zadd(
                self.keys.admission_lease_index(),
                {key: record.lease_expires_at.timestamp()},
            )
        else:
            pipeline.zrem(self.keys.active_index(), key)
            pipeline.zrem(self.keys.admission_lease_index(), key)
        if (
            record.phase is RuntimeTransferPhase.TERMINAL
            and record.terminal_expires_at is not None
        ):
            pipeline.zrem(self.keys.stale_index(), key)
            terminal_bucket = self.keys.terminal_bucket(record.terminal_expires_at)
            pipeline.zadd(terminal_bucket, {key: 0.0})
            pipeline.pexpire(
                terminal_bucket,
                _terminal_retention_milliseconds(record, now),
                lt=True,
            )
        else:
            if (
                envelope.admission_released
                or record.cleanup_status
                is not RuntimeTransferCleanupStatus.NOT_REQUIRED
            ):
                pipeline.zadd(self.keys.stale_index(), {key: 0.0})
            else:
                pipeline.zrem(self.keys.stale_index(), key)
        if (
            active
            and record.consumer_lease_expires_at is not None
            and record.phase is RuntimeTransferPhase.CONSUMING
        ):
            pipeline.zadd(
                self.keys.consumer_lease_index(),
                {key: record.consumer_lease_expires_at.timestamp()},
            )
        else:
            pipeline.zrem(self.keys.consumer_lease_index(), key)


def _capacity_active(envelope: _RedisTransferRecordEnvelope) -> bool:
    """Return whether one envelope reserves capacity and belongs in active state."""
    return (
        not envelope.admission_released
        and envelope.record.phase is not RuntimeTransferPhase.TERMINAL
    )


def _terminal_expired(record: RuntimeTransferRecord, now: datetime) -> bool:
    """Return whether content-free terminal metadata reached its expiry."""
    return (
        record.phase is RuntimeTransferPhase.TERMINAL
        and record.terminal_expires_at is not None
        and record.terminal_expires_at <= now
    )


def _terminal_retention_milliseconds(
    record: RuntimeTransferRecord,
    now: datetime,
) -> int:
    """Return non-extending relative Redis retention for terminal metadata."""
    if record.terminal_expires_at is None:
        raise ValueError("terminal record requires terminal_expires_at")
    remaining = record.terminal_expires_at - now
    return max(1, int(remaining.total_seconds() * 1000))


def _decode_redis_text(value: object) -> str:
    """Decode one Redis binary or decoded text response."""
    if isinstance(value, str):
        return value
    if isinstance(value, bytes):
        return value.decode("utf-8")
    raise RuntimeError("Redis returned an unexpected text response type")


def _decode_key_component(value: str) -> str:
    """Decode one URL-safe base64 Redis key component."""
    padding = "=" * (-len(value) % 4)
    try:
        return base64.urlsafe_b64decode(f"{value}{padding}").decode("utf-8")
    except (UnicodeDecodeError, ValueError) as exc:
        raise RuntimeError("Runtime transfer record key is malformed") from exc


def _decode_redis_texts(values: object) -> list[str]:
    """Decode one bounded Redis response sequence."""
    if not isinstance(values, list):
        raise RuntimeError("Redis returned an unexpected sequence response type")
    return [_decode_redis_text(value) for value in values]


def _redis_bytes(value: object) -> bytes:
    """Normalize one Redis record payload to bytes for the bounded codec."""
    if isinstance(value, bytes):
        return value
    if isinstance(value, str):
        return value.encode("utf-8")
    raise RuntimeError("Redis returned an unexpected record response type")


def _redis_integer(value: object, name: str) -> int:
    """Require one Redis integer response."""
    if type(value) is not int:
        raise RuntimeError(f"Redis returned an unexpected {name} response")
    return value


def _terminal_bucket_epochs(
    now: datetime,
    terminal_ttl: timedelta,
    *,
    expired: bool,
) -> range:
    """Return bounded terminal bucket epochs around the authoritative time."""
    quantum = max(1, int(terminal_ttl.total_seconds()) // 60)
    now_epoch = int(now.timestamp())
    ttl_seconds = math.ceil(terminal_ttl.total_seconds())
    if expired:
        start = (now_epoch - ttl_seconds) // quantum * quantum
        end = now_epoch // quantum * quantum
    else:
        start = (now_epoch // quantum + 1) * quantum
        end = (now_epoch + ttl_seconds) // quantum * quantum
    return range(start, end + quantum, quantum)


def _encode_stale_cursor(state: _RedisStaleCursor) -> str:
    """Encode one opaque stable stale-page cursor."""
    payload = json.dumps(
        {
            "bucket_epoch": state.bucket_epoch,
            "kind": state.kind,
            "member": state.member,
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii")


def _decode_stale_cursor(cursor: str) -> _RedisStaleCursor:
    """Decode one opaque stable stale-page cursor."""
    try:
        value: object = json.loads(
            base64.b64decode(
                cursor.encode("ascii"),
                altchars=b"-_",
                validate=True,
            ).decode("utf-8")
        )
    except (UnicodeDecodeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError("invalid stale page cursor") from exc
    if not isinstance(value, dict) or set(value) != {
        "bucket_epoch",
        "kind",
        "member",
    }:
        raise ValueError("invalid stale page cursor")
    kind = value["kind"]
    member = value["member"]
    bucket_epoch = value["bucket_epoch"]
    if (
        kind not in {"stale", "terminal"}
        or not isinstance(member, str)
        or (
            bucket_epoch is not None
            and (not isinstance(bucket_epoch, int) or isinstance(bucket_epoch, bool))
        )
        or (kind == "stale" and bucket_epoch is not None)
        or (kind == "terminal" and bucket_epoch is None)
    ):
        raise ValueError("invalid stale page cursor")
    return _RedisStaleCursor(kind, member, bucket_epoch)
