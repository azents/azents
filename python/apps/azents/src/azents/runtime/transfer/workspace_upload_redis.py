"""Redis-backed metadata-only Workspace upload state."""

import asyncio
import base64
import dataclasses
import json
import secrets
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import Awaitable, Protocol, runtime_checkable

from redis.exceptions import WatchError

from azents.runtime.transfer.workspace_upload import (
    WorkspaceUploadAdmission,
    WorkspaceUploadCleanupArtifact,
    WorkspaceUploadCleanupFailureEvidence,
    WorkspaceUploadCleanupStatus,
    WorkspaceUploadConfig,
    WorkspaceUploadDeliveryAttempt,
    WorkspaceUploadDeliveryOutcome,
    WorkspaceUploadDestinationEvidence,
    WorkspaceUploadFailure,
    WorkspaceUploadOutcome,
    WorkspaceUploadPage,
    WorkspaceUploadPhase,
    WorkspaceUploadRecord,
    workspace_upload_phase_terminal,
    workspace_upload_terminal_expiry,
)
from azents.runtime.transfer.workspace_upload_object import (
    WorkspaceUploadObjectHandles,
)

_DEFAULT_NAMESPACE = "azents:runtime:workspace-upload:v1"
_RECORD_SCHEMA_VERSION = 3
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


@runtime_checkable
class _RedisPipeline(Protocol):
    """Redis pipeline methods used by the Workspace upload adapter."""

    async def __aenter__(self) -> "_RedisPipeline": ...

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

    def delete(self, *names: str) -> object: ...

    def zadd(self, name: str, mapping: dict[str, float]) -> object: ...

    def zrem(self, name: str, *values: str) -> object: ...

    async def execute(self) -> object: ...


class _RedisPipelineContext(Protocol):
    """Async context manager returned by Redis pipeline creation."""

    async def __aenter__(self) -> object: ...

    async def __aexit__(
        self,
        exc_type: object,
        exc_value: object,
        traceback: object,
    ) -> bool | None: ...


class _RedisClient(Protocol):
    """Redis commands used by the Workspace upload adapter."""

    def set(
        self,
        name: str,
        value: str | bytes,
        *,
        nx: bool,
        px: int,
    ) -> Awaitable[bool | str | bytes | None]: ...

    def get(self, name: str) -> Awaitable[bytes | str | None]: ...

    def zrange(
        self,
        name: str,
        start: int,
        end: int,
    ) -> Awaitable[list[bytes | str]]: ...

    def eval(
        self,
        script: str,
        numkeys: int,
        *keys_and_args: str,
    ) -> Awaitable[object]: ...

    def pipeline(self, *, transaction: bool) -> _RedisPipelineContext: ...


@dataclass(frozen=True)
class _RedisWorkspaceUploadKeys:
    """Deterministic Redis key names under one upload-only namespace."""

    namespace: str = _DEFAULT_NAMESPACE

    def __post_init__(self) -> None:
        """Validate a non-empty upload-specific namespace."""
        if not self.namespace or self.namespace.endswith(":"):
            raise ValueError(
                "Redis Workspace upload namespace must be non-empty without ':' suffix"
            )

    def record(self, upload_id: str) -> str:
        """Return one exact Workspace upload record key."""
        return ":".join((self.namespace, "record", _key_component(upload_id)))

    def active_index(self) -> str:
        """Return the bounded retained-record index key."""
        return f"{self.namespace}:index:retained"

    def mutation_lock(self) -> str:
        """Return the namespace-wide mutation lock key."""
        return f"{self.namespace}:lock:mutation"


def _key_component(value: str) -> str:
    """Encode one identifier without exposing Redis key separators."""
    if not value:
        raise ValueError("Redis Workspace upload key identifier must be non-empty")
    return base64.urlsafe_b64encode(value.encode("utf-8")).decode("ascii").rstrip("=")


def _encode_record(record: WorkspaceUploadRecord) -> bytes:
    """Encode one bounded Workspace upload record as deterministic JSON bytes."""
    encoded = json.dumps(
        {
            "version": _RECORD_SCHEMA_VERSION,
            "record": _record_to_value(record),
        },
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    if len(encoded) > _MAX_SERIALIZED_RECORD_BYTES:
        raise ValueError("Workspace upload record exceeds maximum serialized size")
    return encoded


def _decode_record(value: bytes) -> WorkspaceUploadRecord:
    """Decode one exact Workspace upload JSON envelope through domain validation."""
    if len(value) > _MAX_SERIALIZED_RECORD_BYTES:
        raise ValueError("Workspace upload record exceeds maximum serialized size")
    try:
        decoded: object = json.loads(value)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("Workspace upload record is malformed") from error
    envelope = _object(decoded, "envelope", frozenset({"version", "record"}))
    if _integer(envelope["version"], "version") != _RECORD_SCHEMA_VERSION:
        raise ValueError("Workspace upload record schema version is unsupported")
    return _record_from_value(envelope["record"])


class RedisWorkspaceUploadStore:
    """Redis Workspace upload state with a token-owned mutation lock."""

    def __init__(
        self,
        *,
        redis: _RedisClient,
        config: WorkspaceUploadConfig,
        clock: Callable[[], datetime],
        namespace: str = _DEFAULT_NAMESPACE,
    ) -> None:
        """Initialize volatile Redis state dependencies."""
        self.redis = redis
        self.config = config
        self.clock = clock
        self.keys = _RedisWorkspaceUploadKeys(namespace)

    async def create(
        self,
        admission: WorkspaceUploadAdmission,
    ) -> WorkspaceUploadRecord | None:
        """Create one requester-bound upload if active capacity permits it."""
        now = self._now()
        async with self._locked() as token:
            records = await self._load_records()
            self._reclaim(records, now)
            existing = records.get(admission.upload_id)
            if existing is not None:
                await self._commit(token, records, now)
                return existing if existing.admission == admission else None
            if (
                admission.expected_size > self.config.maximum_file_size
                or not self._has_capacity(records, admission)
            ):
                await self._commit(token, records, now)
                return None
            record = WorkspaceUploadRecord(
                admission=admission,
                phase=WorkspaceUploadPhase.QUEUED,
                revision=1,
                received_size=0,
                ingress_handle=None,
                source_handle=None,
                actual_size=None,
                actual_sha256=None,
                delivery_attempts=(),
                current_delivery_number=None,
                cancellation_requested_at=None,
                reconciliation_claim_id=None,
                reconciliation_lease_expires_at=None,
                cleanup_claim_id=None,
                cleanup_lease_expires_at=None,
                cleanup_status=WorkspaceUploadCleanupStatus.NOT_REQUIRED,
                cleanup_failure=None,
                outcome=None,
                failure=None,
                created_at=now,
                updated_at=now,
                expires_at=now + self.config.upload_ttl,
                terminal_expires_at=None,
            )
            records[admission.upload_id] = record
            await self._commit(token, records, now)
            return record

    async def get(
        self,
        upload_id: str,
        *,
        requester_user_id: str,
        workspace_id: str,
        agent_id: str,
    ) -> WorkspaceUploadRecord | None:
        """Return one exact requester, Workspace, and Agent-bound upload."""
        now = self._now()
        async with self._locked() as token:
            records = await self._load_records()
            self._reclaim(records, now)
            await self._commit(token, records, now)
            record = records.get(upload_id)
            return (
                record
                if _bound(record, requester_user_id, workspace_id, agent_id)
                else None
            )

    async def compare_and_set(
        self,
        record: WorkspaceUploadRecord,
        *,
        expected_revision: int,
    ) -> WorkspaceUploadRecord | None:
        """Atomically replace one record while preserving immutable authority."""
        now = self._now()
        async with self._locked() as token:
            records = await self._load_records()
            self._reclaim(records, now)
            current = records.get(record.admission.upload_id)
            if (
                current is None
                or current.revision != expected_revision
                or not _same_authority(current, record)
            ):
                await self._commit(token, records, now)
                return None
            updated = dataclasses.replace(
                record,
                revision=current.revision + 1,
                updated_at=now,
            )
            records[updated.admission.upload_id] = updated
            await self._commit(token, records, now)
            return updated

    async def claim_ingress(
        self,
        upload_id: str,
        *,
        requester_user_id: str,
        workspace_id: str,
        agent_id: str,
        expected_revision: int,
        claim_id: str,
    ) -> WorkspaceUploadRecord | None:
        """Claim one direct-object ingress for authenticated finalization."""
        now = self._now()
        async with self._locked() as token:
            records = await self._load_records()
            self._reclaim(records, now)
            record = records.get(upload_id)
            if (
                not _bound(record, requester_user_id, workspace_id, agent_id)
                or record is None
                or record.revision != expected_revision
                or record.phase is not WorkspaceUploadPhase.UPLOADING
                or record.ingress_handle is None
                or record.source_handle is not None
                or record.pending_source_handle is not None
                or record.cancellation_requested_at is not None
                or (
                    record.ingress_claim_id is not None
                    and (
                        record.ingress_lease_expires_at is None
                        or record.ingress_lease_expires_at > now
                    )
                )
                or (
                    record.ingress_claim_id is None
                    and record.ingress_lease_expires_at is not None
                    and record.ingress_lease_expires_at > now
                )
            ):
                await self._commit(token, records, now)
                return None
            updated = dataclasses.replace(
                record,
                revision=record.revision + 1,
                updated_at=now,
                ingress_claim_id=claim_id,
                ingress_lease_expires_at=now + self.config.ingress_lease,
            )
            records[upload_id] = updated
            await self._commit(token, records, now)
            return updated

    async def renew_ingress_lease(
        self,
        upload_id: str,
        *,
        requester_user_id: str,
        workspace_id: str,
        agent_id: str,
        expected_revision: int,
        claim_id: str,
    ) -> WorkspaceUploadRecord | None:
        """Renew one exact active ingress lease."""
        now = self._now()
        async with self._locked() as token:
            records = await self._load_records()
            self._reclaim(records, now)
            record = records.get(upload_id)
            if (
                not _bound(record, requester_user_id, workspace_id, agent_id)
                or record is None
                or record.revision != expected_revision
                or record.phase is not WorkspaceUploadPhase.UPLOADING
                or record.ingress_claim_id != claim_id
                or record.ingress_lease_expires_at is None
                or record.ingress_lease_expires_at <= now
            ):
                await self._commit(token, records, now)
                return None
            updated = dataclasses.replace(
                record,
                revision=record.revision + 1,
                updated_at=now,
                ingress_lease_expires_at=now + self.config.ingress_lease,
            )
            records[upload_id] = updated
            await self._commit(token, records, now)
            return updated

    async def record_ingress_progress(
        self,
        upload_id: str,
        *,
        requester_user_id: str,
        workspace_id: str,
        agent_id: str,
        expected_revision: int,
        claim_id: str,
        received_size: int,
    ) -> WorkspaceUploadRecord | None:
        """Record monotonic ingress progress while renewing its lease."""
        now = self._now()
        async with self._locked() as token:
            records = await self._load_records()
            self._reclaim(records, now)
            record = records.get(upload_id)
            if (
                not _bound(record, requester_user_id, workspace_id, agent_id)
                or record is None
                or record.revision != expected_revision
                or record.phase is not WorkspaceUploadPhase.UPLOADING
                or record.ingress_claim_id != claim_id
                or record.ingress_lease_expires_at is None
                or record.ingress_lease_expires_at <= now
                or record.cancellation_requested_at is not None
                or received_size < record.received_size
                or received_size > record.admission.expected_size
            ):
                await self._commit(token, records, now)
                return None
            updated = dataclasses.replace(
                record,
                revision=record.revision + 1,
                updated_at=now,
                received_size=received_size,
                ingress_lease_expires_at=now + self.config.ingress_lease,
            )
            records[upload_id] = updated
            await self._commit(token, records, now)
            return updated

    async def append_delivery_attempt(
        self,
        upload_id: str,
        *,
        requester_user_id: str,
        workspace_id: str,
        agent_id: str,
        expected_revision: int,
        attempt: WorkspaceUploadDeliveryAttempt,
    ) -> WorkspaceUploadRecord | None:
        """Append exactly one new active immutable Runtime delivery attempt."""
        now = self._now()
        async with self._locked() as token:
            records = await self._load_records()
            self._reclaim(records, now)
            record = records.get(upload_id)
            if (
                not _bound(record, requester_user_id, workspace_id, agent_id)
                or record is None
                or record.revision != expected_revision
                or record.source_handle is None
                or record.ingress_claim_id is not None
                or record.phase
                not in {
                    WorkspaceUploadPhase.MOVING_TO_RUNTIME,
                    WorkspaceUploadPhase.CONFLICTED,
                    WorkspaceUploadPhase.RETRYABLE_FAILURE,
                }
                or (
                    record.delivery_attempts
                    and record.delivery_attempts[-1].completed_at is None
                )
                or attempt.number != len(record.delivery_attempts) + 1
                or attempt.completed_at is not None
            ):
                await self._commit(token, records, now)
                return None
            updated = dataclasses.replace(
                record,
                revision=record.revision + 1,
                updated_at=now,
                phase=WorkspaceUploadPhase.MOVING_TO_RUNTIME,
                delivery_attempts=record.delivery_attempts + (attempt,),
                current_delivery_number=attempt.number,
                cancellation_requested_at=None,
                outcome=None,
                failure=None,
                terminal_expires_at=None,
            )
            records[upload_id] = updated
            await self._commit(token, records, now)
            return updated

    async def settle_delivery_attempt(
        self,
        upload_id: str,
        *,
        requester_user_id: str,
        workspace_id: str,
        agent_id: str,
        expected_revision: int,
        delivery_number: int,
        outcome: WorkspaceUploadDeliveryOutcome,
        failure: WorkspaceUploadFailure | None,
        conflict_precondition: str | None,
        conflict_revision: str | None,
        destination_evidence: WorkspaceUploadDestinationEvidence | None,
    ) -> WorkspaceUploadRecord | None:
        """Settle exactly the current active delivery attempt once."""
        now = self._now()
        async with self._locked() as token:
            records = await self._load_records()
            self._reclaim(records, now)
            record = records.get(upload_id)
            if (
                not _bound(record, requester_user_id, workspace_id, agent_id)
                or record is None
                or record.revision != expected_revision
                or record.current_delivery_number != delivery_number
                or not record.delivery_attempts
                or record.delivery_attempts[-1].number != delivery_number
                or record.delivery_attempts[-1].completed_at is not None
            ):
                await self._commit(token, records, now)
                return None
            active = record.delivery_attempts[-1]
            completed = dataclasses.replace(
                active,
                conflict_precondition=(
                    conflict_precondition
                    if conflict_precondition is not None
                    else active.conflict_precondition
                ),
                completed_at=now,
                outcome=outcome,
                failure=failure,
                conflict_revision=conflict_revision,
                destination_evidence=destination_evidence,
            )
            attempts = record.delivery_attempts[:-1] + (completed,)
            terminal = outcome in {
                WorkspaceUploadDeliveryOutcome.SUCCEEDED,
                WorkspaceUploadDeliveryOutcome.CANCELLED,
                WorkspaceUploadDeliveryOutcome.FAILED,
                WorkspaceUploadDeliveryOutcome.EXPIRED,
            }
            phase = {
                WorkspaceUploadDeliveryOutcome.SUCCEEDED: (
                    WorkspaceUploadPhase.SUCCEEDED
                ),
                WorkspaceUploadDeliveryOutcome.CANCELLED: (
                    WorkspaceUploadPhase.CANCELLED
                ),
                WorkspaceUploadDeliveryOutcome.FAILED: WorkspaceUploadPhase.FAILED,
                WorkspaceUploadDeliveryOutcome.CONFLICTED: (
                    WorkspaceUploadPhase.CONFLICTED
                ),
                WorkspaceUploadDeliveryOutcome.RETRYABLE_FAILURE: (
                    WorkspaceUploadPhase.RETRYABLE_FAILURE
                ),
                WorkspaceUploadDeliveryOutcome.EXPIRED: WorkspaceUploadPhase.EXPIRED,
            }[outcome]
            updated = dataclasses.replace(
                record,
                revision=record.revision + 1,
                updated_at=now,
                phase=phase,
                delivery_attempts=attempts,
                reconciliation_claim_id=None,
                reconciliation_lease_expires_at=None,
                cancellation_requested_at=None,
                cleanup_status=(
                    WorkspaceUploadCleanupStatus.PENDING
                    if terminal
                    and (
                        record.source_handle is not None
                        or record.pending_source_handle is not None
                        or record.ingress_handle is not None
                    )
                    else WorkspaceUploadCleanupStatus.NOT_REQUIRED
                ),
                cleanup_claim_id=None,
                cleanup_lease_expires_at=None,
                cleanup_failure=None,
                outcome=WorkspaceUploadOutcome(outcome.value) if terminal else None,
                failure=failure,
                terminal_expires_at=(
                    workspace_upload_terminal_expiry(
                        now,
                        self.config.terminal_ttl,
                    )
                    if terminal
                    else None
                ),
            )
            records[upload_id] = updated
            await self._commit(token, records, now)
            return updated

    async def request_cancellation(
        self,
        upload_id: str,
        *,
        requester_user_id: str,
        workspace_id: str,
        agent_id: str,
        expected_revision: int,
        current_delivery_number: int | None = None,
    ) -> WorkspaceUploadRecord | None:
        """Request cancellation, terminalizing only states with no active worker."""
        now = self._now()
        async with self._locked() as token:
            records = await self._load_records()
            self._reclaim(records, now)
            record = records.get(upload_id)
            if (
                not _bound(record, requester_user_id, workspace_id, agent_id)
                or record is None
                or record.revision != expected_revision
                or (
                    current_delivery_number is not None
                    and record.current_delivery_number != current_delivery_number
                )
            ):
                await self._commit(token, records, now)
                return None
            if workspace_upload_phase_terminal(record.phase):
                await self._commit(token, records, now)
                return record
            active_worker = (
                record.phase is WorkspaceUploadPhase.UPLOADING
                and record.ingress_claim_id is not None
                and record.ingress_lease_expires_at is not None
                and record.ingress_lease_expires_at > now
            ) or (
                record.phase is WorkspaceUploadPhase.MOVING_TO_RUNTIME
                and bool(record.delivery_attempts)
                and record.delivery_attempts[-1].completed_at is None
            )
            if active_worker:
                updated = dataclasses.replace(
                    record,
                    revision=record.revision + 1,
                    updated_at=now,
                    cancellation_requested_at=now,
                )
            else:
                cleanup_required = (
                    record.source_handle is not None
                    or record.pending_source_handle is not None
                    or record.ingress_handle is not None
                )
                updated = dataclasses.replace(
                    record,
                    revision=record.revision + 1,
                    updated_at=now,
                    phase=WorkspaceUploadPhase.CANCELLED,
                    cleanup_status=(
                        WorkspaceUploadCleanupStatus.PENDING
                        if cleanup_required
                        else WorkspaceUploadCleanupStatus.NOT_REQUIRED
                    ),
                    cleanup_claim_id=None,
                    cleanup_lease_expires_at=None,
                    cleanup_failure=None,
                    outcome=WorkspaceUploadOutcome.CANCELLED,
                    failure=WorkspaceUploadFailure.CANCELLED,
                    terminal_expires_at=workspace_upload_terminal_expiry(
                        now,
                        self.config.terminal_ttl,
                    ),
                )
            records[upload_id] = updated
            await self._commit(token, records, now)
            return updated

    async def claim_reconciliation(
        self,
        upload_id: str,
        *,
        requester_user_id: str,
        workspace_id: str,
        agent_id: str,
        expected_revision: int,
        claim_id: str,
    ) -> WorkspaceUploadRecord | None:
        """Claim one active Runtime-delivery projection lease."""
        now = self._now()
        async with self._locked() as token:
            records = await self._load_records()
            self._reclaim(records, now)
            record = records.get(upload_id)
            if not _bound(record, requester_user_id, workspace_id, agent_id):
                await self._commit(token, records, now)
                return None
            assert record is not None
            if (
                record.revision != expected_revision
                or record.phase is not WorkspaceUploadPhase.MOVING_TO_RUNTIME
                or (
                    record.reconciliation_lease_expires_at is not None
                    and record.reconciliation_lease_expires_at > now
                )
            ):
                await self._commit(token, records, now)
                return None
            updated = dataclasses.replace(
                record,
                revision=record.revision + 1,
                updated_at=now,
                reconciliation_claim_id=claim_id,
                reconciliation_lease_expires_at=now + self.config.reconciliation_lease,
            )
            records[upload_id] = updated
            await self._commit(token, records, now)
            return updated

    async def claim_cleanup(
        self,
        upload_id: str,
        *,
        requester_user_id: str,
        workspace_id: str,
        agent_id: str,
        expected_revision: int,
        claim_id: str,
    ) -> WorkspaceUploadRecord | None:
        """Claim one bounded source-cleanup lease."""
        now = self._now()
        async with self._locked() as token:
            records = await self._load_records()
            self._reclaim(records, now)
            record = records.get(upload_id)
            if not _bound(record, requester_user_id, workspace_id, agent_id):
                await self._commit(token, records, now)
                return None
            assert record is not None
            if (
                record.revision != expected_revision
                or record.cleanup_status
                not in {
                    WorkspaceUploadCleanupStatus.PENDING,
                    WorkspaceUploadCleanupStatus.RETRYABLE_FAILURE,
                }
                or (
                    record.cleanup_lease_expires_at is not None
                    and record.cleanup_lease_expires_at > now
                )
            ):
                await self._commit(token, records, now)
                return None
            updated = dataclasses.replace(
                record,
                revision=record.revision + 1,
                updated_at=now,
                cleanup_claim_id=claim_id,
                cleanup_lease_expires_at=now + self.config.cleanup_lease,
                cleanup_status=WorkspaceUploadCleanupStatus.IN_PROGRESS,
                cleanup_failure=None,
            )
            records[upload_id] = updated
            await self._commit(token, records, now)
            return updated

    async def list_reconciliation(
        self,
        *,
        cursor: str | None,
        limit: int,
    ) -> WorkspaceUploadPage:
        """List active Runtime-delivery uploads in deterministic identifier order."""
        return await self._list(
            cursor=cursor,
            limit=limit,
            selected=lambda record: (
                record.phase is WorkspaceUploadPhase.MOVING_TO_RUNTIME
            ),
        )

    async def list_cleanup(
        self,
        *,
        cursor: str | None,
        limit: int,
    ) -> WorkspaceUploadPage:
        """List source cleanup candidates in deterministic identifier order."""
        return await self._list(
            cursor=cursor,
            limit=limit,
            selected=lambda record: (
                record.cleanup_status
                in {
                    WorkspaceUploadCleanupStatus.PENDING,
                    WorkspaceUploadCleanupStatus.RETRYABLE_FAILURE,
                }
            ),
        )

    async def list_object_handles(self) -> WorkspaceUploadObjectHandles:
        """Return all object handles retained by live upload metadata."""
        now = self._now()
        async with self._locked() as token:
            records = await self._load_records()
            self._reclaim(records, now)
            await self._commit(token, records, now)
            return WorkspaceUploadObjectHandles(
                ingress_handles=frozenset(
                    record.ingress_handle
                    for record in records.values()
                    if record.ingress_handle is not None
                ),
                source_handles=frozenset(
                    handle
                    for record in records.values()
                    for handle in (
                        record.pending_source_handle,
                        record.source_handle,
                    )
                    if handle is not None
                ),
            )

    async def purge_terminal(self, *, limit: int) -> int:
        """Delete retained terminal metadata only after terminal retention expires."""
        now = self._now()
        async with self._locked() as token:
            records = await self._load_records()
            self._reclaim(records, now)
            if limit <= 0 or limit > self.config.list_page_size:
                await self._commit(token, records, now)
                raise ValueError("invalid page limit")
            deleted = {
                upload_id
                for upload_id, record in sorted(records.items())
                if (
                    workspace_upload_phase_terminal(record.phase)
                    and record.terminal_expires_at is not None
                    and record.terminal_expires_at <= now
                    and record.cleanup_status
                    in {
                        WorkspaceUploadCleanupStatus.COMPLETE,
                        WorkspaceUploadCleanupStatus.NOT_REQUIRED,
                    }
                )
            }
            deleted = set(sorted(deleted)[:limit])
            for upload_id in deleted:
                del records[upload_id]
            await self._commit(token, records, now, deleted=deleted)
            return len(deleted)

    async def _list(
        self,
        *,
        cursor: str | None,
        limit: int,
        selected: Callable[[WorkspaceUploadRecord], bool],
    ) -> WorkspaceUploadPage:
        """Read one deterministic bounded page while applying due expiry."""
        now = self._now()
        async with self._locked() as token:
            records = await self._load_records()
            self._reclaim(records, now)
            if limit <= 0 or limit > self.config.list_page_size:
                await self._commit(token, records, now)
                raise ValueError("invalid page limit")
            matching = [
                record
                for upload_id, record in sorted(records.items())
                if (cursor is None or upload_id > cursor) and selected(record)
            ]
            page = tuple(matching[:limit])
            await self._commit(token, records, now)
            return WorkspaceUploadPage(
                records=page,
                cursor=(
                    page[-1].admission.upload_id if len(matching) > limit else None
                ),
            )

    async def _load_records(self) -> dict[str, WorkspaceUploadRecord]:
        """Load all bounded retained records from the namespace index."""
        keys = _texts(await self.redis.zrange(self.keys.active_index(), 0, -1))
        records: dict[str, WorkspaceUploadRecord] = {}
        for key in keys:
            value = await self.redis.get(key)
            if value is None:
                raise RuntimeError(
                    "Workspace upload retained index references a missing record"
                )
            record = _decode_record(_bytes(value))
            records[record.admission.upload_id] = record
        return records

    async def _commit(
        self,
        token: str,
        records: dict[str, WorkspaceUploadRecord],
        now: datetime,
        *,
        deleted: set[str] | None = None,
    ) -> None:
        """Persist all bounded records while the mutation token remains owned."""
        removed = deleted or set()
        async with self.redis.pipeline(transaction=True) as pipeline:
            if not isinstance(pipeline, _RedisPipeline):
                raise RuntimeError(
                    "Redis pipeline does not expose Workspace upload operations"
                )
            await pipeline.watch(self.keys.mutation_lock())
            owner = await pipeline.get(self.keys.mutation_lock())
            if owner is None or _text(owner) != token:
                raise RuntimeError("Workspace upload mutation lock ownership was lost")
            pipeline.multi()
            for record in records.values():
                key = self.keys.record(record.admission.upload_id)
                pipeline.set(key, _encode_record(record), keepttl=True)
                pipeline.zadd(
                    self.keys.active_index(),
                    {key: record.created_at.timestamp()},
                )
            for upload_id in removed:
                key = self.keys.record(upload_id)
                pipeline.delete(key)
                pipeline.zrem(self.keys.active_index(), key)
            try:
                await pipeline.execute()
            except WatchError as error:
                raise RuntimeError(
                    "Workspace upload mutation lock changed before commit"
                ) from error

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
                raise TimeoutError("timed out acquiring Workspace upload mutation lock")
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
                _integer(released, "mutation lock release") != 1
                and not operation_failed
            ):
                raise RuntimeError("Workspace upload mutation lock ownership was lost")

    def _reclaim(
        self,
        records: dict[str, WorkspaceUploadRecord],
        now: datetime,
    ) -> None:
        """Expire active metadata without reconstructing state from source residue."""
        for upload_id, record in tuple(records.items()):
            if (
                record.phase is WorkspaceUploadPhase.UPLOADING
                and record.ingress_lease_expires_at is not None
                and record.ingress_lease_expires_at <= now
            ):
                cleanup_required = (
                    record.source_handle is not None
                    or record.pending_source_handle is not None
                    or record.ingress_handle is not None
                )
                if record.cancellation_requested_at is not None:
                    records[upload_id] = dataclasses.replace(
                        record,
                        phase=WorkspaceUploadPhase.CANCELLED,
                        revision=record.revision + 1,
                        updated_at=now,
                        ingress_claim_id=None,
                        ingress_lease_expires_at=None,
                        cleanup_status=(
                            WorkspaceUploadCleanupStatus.PENDING
                            if cleanup_required
                            else WorkspaceUploadCleanupStatus.NOT_REQUIRED
                        ),
                        outcome=WorkspaceUploadOutcome.CANCELLED,
                        failure=WorkspaceUploadFailure.CANCELLED,
                        terminal_expires_at=workspace_upload_terminal_expiry(
                            now,
                            self.config.terminal_ttl,
                        ),
                    )
                else:
                    records[upload_id] = dataclasses.replace(
                        record,
                        phase=WorkspaceUploadPhase.RETRYABLE_FAILURE,
                        revision=record.revision + 1,
                        updated_at=now,
                        ingress_claim_id=None,
                        ingress_lease_expires_at=None,
                        cleanup_status=(
                            WorkspaceUploadCleanupStatus.PENDING
                            if cleanup_required
                            else WorkspaceUploadCleanupStatus.NOT_REQUIRED
                        ),
                        cleanup_claim_id=None,
                        cleanup_lease_expires_at=None,
                        cleanup_failure=None,
                        failure=WorkspaceUploadFailure.INGRESS,
                    )
                continue
            if (
                not workspace_upload_phase_terminal(record.phase)
                and record.expires_at <= now
            ):
                cleanup_status = (
                    WorkspaceUploadCleanupStatus.PENDING
                    if (
                        record.source_handle is not None
                        or record.pending_source_handle is not None
                        or record.ingress_handle is not None
                    )
                    else WorkspaceUploadCleanupStatus.NOT_REQUIRED
                )
                records[upload_id] = dataclasses.replace(
                    record,
                    phase=WorkspaceUploadPhase.EXPIRED,
                    revision=record.revision + 1,
                    updated_at=now,
                    reconciliation_claim_id=None,
                    reconciliation_lease_expires_at=None,
                    ingress_claim_id=None,
                    ingress_lease_expires_at=None,
                    cleanup_claim_id=None,
                    cleanup_lease_expires_at=None,
                    cleanup_status=cleanup_status,
                    cleanup_failure=None,
                    outcome=WorkspaceUploadOutcome.EXPIRED,
                    failure=None,
                    terminal_expires_at=workspace_upload_terminal_expiry(
                        now,
                        self.config.terminal_ttl,
                    ),
                )

    def _has_capacity(
        self,
        records: dict[str, WorkspaceUploadRecord],
        admission: WorkspaceUploadAdmission,
    ) -> bool:
        """Apply bounded deployment and requester-Agent active reservations."""
        active = [
            record
            for record in records.values()
            if not workspace_upload_phase_terminal(record.phase)
        ]
        scoped = [
            record
            for record in active
            if (
                record.admission.requester_user_id == admission.requester_user_id
                and record.admission.workspace_id == admission.workspace_id
                and record.admission.agent_id == admission.agent_id
            )
        ]
        return (
            len(active) < self.config.maximum_active_uploads
            and sum(record.admission.expected_size for record in active)
            + admission.expected_size
            <= self.config.maximum_active_bytes
            and len(scoped) < self.config.maximum_active_uploads_per_requester_agent
            and sum(record.admission.expected_size for record in scoped)
            + admission.expected_size
            <= self.config.maximum_active_bytes_per_requester_agent
        )

    def _now(self) -> datetime:
        """Capture one authoritative timezone-aware clock value."""
        now = self.clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("clock must return timezone-aware datetime")
        return now


def _record_to_value(record: WorkspaceUploadRecord) -> dict[str, object]:
    """Return one exact JSON-compatible record representation."""
    return {
        "admission": {
            "upload_id": record.admission.upload_id,
            "requester_user_id": record.admission.requester_user_id,
            "workspace_id": record.admission.workspace_id,
            "agent_id": record.admission.agent_id,
            "runtime_id": record.admission.runtime_id,
            "desired_generation": record.admission.desired_generation,
            "session_id": record.admission.session_id,
            "deadline_at": _datetime(record.admission.deadline_at),
            "destination_directory": record.admission.destination_directory,
            "filename": record.admission.filename,
            "destination_path": record.admission.destination_path,
            "expected_size": record.admission.expected_size,
            "media_type": record.admission.media_type,
            "expected_sha256": record.admission.expected_sha256,
        },
        "phase": record.phase.value,
        "revision": record.revision,
        "received_size": record.received_size,
        "ingress_handle": record.ingress_handle,
        "pending_source_handle": record.pending_source_handle,
        "source_handle": record.source_handle,
        "actual_size": record.actual_size,
        "actual_sha256": record.actual_sha256,
        "delivery_attempts": [
            {
                "number": attempt.number,
                "attempt_id": attempt.attempt_id,
                "transfer_id": attempt.transfer_id,
                "transfer_attempt_id": attempt.transfer_attempt_id,
                "overwrite": attempt.overwrite,
                "conflict_precondition": attempt.conflict_precondition,
                "created_at": _datetime(attempt.created_at),
                "completed_at": _optional_datetime_to_value(attempt.completed_at),
                "outcome": None if attempt.outcome is None else attempt.outcome.value,
                "failure": None if attempt.failure is None else attempt.failure.value,
                "conflict_revision": attempt.conflict_revision,
                "destination_evidence": (
                    None
                    if attempt.destination_evidence is None
                    else {
                        "kind": attempt.destination_evidence.kind,
                        "size": attempt.destination_evidence.size,
                        "modified_at": _datetime(
                            attempt.destination_evidence.modified_at
                        ),
                    }
                ),
            }
            for attempt in record.delivery_attempts
        ],
        "current_delivery_number": record.current_delivery_number,
        "cancellation_requested_at": _optional_datetime_to_value(
            record.cancellation_requested_at
        ),
        "reconciliation_claim_id": record.reconciliation_claim_id,
        "reconciliation_lease_expires_at": _optional_datetime_to_value(
            record.reconciliation_lease_expires_at
        ),
        "ingress_claim_id": record.ingress_claim_id,
        "ingress_lease_expires_at": _optional_datetime_to_value(
            record.ingress_lease_expires_at
        ),
        "cleanup_claim_id": record.cleanup_claim_id,
        "cleanup_lease_expires_at": _optional_datetime_to_value(
            record.cleanup_lease_expires_at
        ),
        "cleanup_status": record.cleanup_status.value,
        "cleanup_failure": None
        if record.cleanup_failure is None
        else {
            "artifact": record.cleanup_failure.artifact.value,
            "observed_at": _datetime(record.cleanup_failure.observed_at),
            "attempts": record.cleanup_failure.attempts,
        },
        "outcome": None if record.outcome is None else record.outcome.value,
        "failure": None if record.failure is None else record.failure.value,
        "created_at": _datetime(record.created_at),
        "updated_at": _datetime(record.updated_at),
        "expires_at": _datetime(record.expires_at),
        "terminal_expires_at": _optional_datetime_to_value(record.terminal_expires_at),
    }


_RECORD_FIELDS = frozenset(
    {
        "admission",
        "phase",
        "revision",
        "received_size",
        "ingress_handle",
        "pending_source_handle",
        "source_handle",
        "actual_size",
        "actual_sha256",
        "delivery_attempts",
        "current_delivery_number",
        "cancellation_requested_at",
        "reconciliation_claim_id",
        "reconciliation_lease_expires_at",
        "ingress_claim_id",
        "ingress_lease_expires_at",
        "cleanup_claim_id",
        "cleanup_lease_expires_at",
        "cleanup_status",
        "cleanup_failure",
        "outcome",
        "failure",
        "created_at",
        "updated_at",
        "expires_at",
        "terminal_expires_at",
    }
)
_ADMISSION_FIELDS = frozenset(
    {
        "upload_id",
        "requester_user_id",
        "workspace_id",
        "agent_id",
        "runtime_id",
        "desired_generation",
        "session_id",
        "deadline_at",
        "destination_directory",
        "filename",
        "destination_path",
        "expected_size",
        "media_type",
        "expected_sha256",
    }
)
_ATTEMPT_FIELDS = frozenset(
    {
        "number",
        "attempt_id",
        "transfer_id",
        "transfer_attempt_id",
        "overwrite",
        "conflict_precondition",
        "created_at",
        "completed_at",
        "outcome",
        "failure",
        "conflict_revision",
        "destination_evidence",
    }
)
_DESTINATION_EVIDENCE_FIELDS = frozenset({"kind", "size", "modified_at"})
_CLEANUP_FAILURE_FIELDS = frozenset({"artifact", "observed_at", "attempts"})


def _record_from_value(value: object) -> WorkspaceUploadRecord:
    """Restore one record through exact schema and domain validation."""
    record = _object(value, "record", _RECORD_FIELDS)
    admission = _object(record["admission"], "admission", _ADMISSION_FIELDS)
    attempts_value = record["delivery_attempts"]
    if not isinstance(attempts_value, list):
        raise ValueError("delivery_attempts must be an array")
    cleanup_failure_value = record["cleanup_failure"]
    return WorkspaceUploadRecord(
        admission=WorkspaceUploadAdmission(
            upload_id=_string(admission["upload_id"], "upload_id"),
            requester_user_id=_string(
                admission["requester_user_id"],
                "requester_user_id",
            ),
            workspace_id=_string(admission["workspace_id"], "workspace_id"),
            agent_id=_string(admission["agent_id"], "agent_id"),
            runtime_id=_string(admission["runtime_id"], "runtime_id"),
            desired_generation=_integer(
                admission["desired_generation"],
                "desired_generation",
            ),
            session_id=_optional_string(admission["session_id"], "session_id"),
            deadline_at=_datetime_from_value(
                admission["deadline_at"],
                "deadline_at",
            ),
            destination_directory=_string(
                admission["destination_directory"],
                "destination_directory",
            ),
            filename=_string(admission["filename"], "filename"),
            destination_path=_string(
                admission["destination_path"],
                "destination_path",
            ),
            expected_size=_integer(admission["expected_size"], "expected_size"),
            media_type=_optional_string(admission["media_type"], "media_type"),
            expected_sha256=_string(admission["expected_sha256"], "expected_sha256"),
        ),
        phase=WorkspaceUploadPhase(_string(record["phase"], "phase")),
        revision=_integer(record["revision"], "revision"),
        received_size=_integer(record["received_size"], "received_size"),
        ingress_handle=_optional_string(
            record["ingress_handle"],
            "ingress_handle",
        ),
        pending_source_handle=_optional_string(
            record["pending_source_handle"],
            "pending_source_handle",
        ),
        source_handle=_optional_string(record["source_handle"], "source_handle"),
        actual_size=_optional_integer(record["actual_size"], "actual_size"),
        actual_sha256=_optional_string(record["actual_sha256"], "actual_sha256"),
        delivery_attempts=tuple(_attempt_from_value(item) for item in attempts_value),
        current_delivery_number=_optional_integer(
            record["current_delivery_number"],
            "current_delivery_number",
        ),
        cancellation_requested_at=_optional_datetime_from_value(
            record["cancellation_requested_at"],
            "cancellation_requested_at",
        ),
        reconciliation_claim_id=_optional_string(
            record["reconciliation_claim_id"],
            "reconciliation_claim_id",
        ),
        reconciliation_lease_expires_at=_optional_datetime_from_value(
            record["reconciliation_lease_expires_at"],
            "reconciliation_lease_expires_at",
        ),
        ingress_claim_id=_optional_string(
            record["ingress_claim_id"],
            "ingress_claim_id",
        ),
        ingress_lease_expires_at=_optional_datetime_from_value(
            record["ingress_lease_expires_at"],
            "ingress_lease_expires_at",
        ),
        cleanup_claim_id=_optional_string(
            record["cleanup_claim_id"], "cleanup_claim_id"
        ),
        cleanup_lease_expires_at=_optional_datetime_from_value(
            record["cleanup_lease_expires_at"],
            "cleanup_lease_expires_at",
        ),
        cleanup_status=WorkspaceUploadCleanupStatus(
            _string(record["cleanup_status"], "cleanup_status")
        ),
        cleanup_failure=None
        if cleanup_failure_value is None
        else _cleanup_failure_from_value(cleanup_failure_value),
        outcome=None
        if record["outcome"] is None
        else WorkspaceUploadOutcome(_string(record["outcome"], "outcome")),
        failure=None
        if record["failure"] is None
        else WorkspaceUploadFailure(_string(record["failure"], "failure")),
        created_at=_datetime_from_value(record["created_at"], "created_at"),
        updated_at=_datetime_from_value(record["updated_at"], "updated_at"),
        expires_at=_datetime_from_value(record["expires_at"], "expires_at"),
        terminal_expires_at=_optional_datetime_from_value(
            record["terminal_expires_at"],
            "terminal_expires_at",
        ),
    )


def _attempt_from_value(value: object) -> WorkspaceUploadDeliveryAttempt:
    """Restore one ordered delivery attempt through exact schema validation."""
    attempt = _object(value, "delivery_attempt", _ATTEMPT_FIELDS)
    destination_evidence_value = attempt["destination_evidence"]
    return WorkspaceUploadDeliveryAttempt(
        number=_integer(attempt["number"], "delivery_attempt.number"),
        attempt_id=_string(attempt["attempt_id"], "delivery_attempt.attempt_id"),
        transfer_id=_string(attempt["transfer_id"], "delivery_attempt.transfer_id"),
        transfer_attempt_id=_string(
            attempt["transfer_attempt_id"],
            "delivery_attempt.transfer_attempt_id",
        ),
        overwrite=_boolean(attempt["overwrite"], "delivery_attempt.overwrite"),
        conflict_precondition=_optional_string(
            attempt["conflict_precondition"],
            "delivery_attempt.conflict_precondition",
        ),
        created_at=_datetime_from_value(
            attempt["created_at"],
            "delivery_attempt.created_at",
        ),
        completed_at=_optional_datetime_from_value(
            attempt["completed_at"],
            "delivery_attempt.completed_at",
        ),
        outcome=None
        if attempt["outcome"] is None
        else WorkspaceUploadDeliveryOutcome(
            _string(attempt["outcome"], "delivery_attempt.outcome")
        ),
        failure=None
        if attempt["failure"] is None
        else WorkspaceUploadFailure(
            _string(attempt["failure"], "delivery_attempt.failure")
        ),
        conflict_revision=_optional_string(
            attempt["conflict_revision"],
            "delivery_attempt.conflict_revision",
        ),
        destination_evidence=(
            None
            if destination_evidence_value is None
            else _destination_evidence_from_value(destination_evidence_value)
        ),
    )


def _destination_evidence_from_value(
    value: object,
) -> WorkspaceUploadDestinationEvidence:
    """Restore public-safe destination conflict evidence."""
    evidence = _object(
        value,
        "destination_evidence",
        _DESTINATION_EVIDENCE_FIELDS,
    )
    return WorkspaceUploadDestinationEvidence(
        kind=_string(evidence["kind"], "destination_evidence.kind"),
        size=_optional_integer(evidence["size"], "destination_evidence.size"),
        modified_at=_datetime_from_value(
            evidence["modified_at"],
            "destination_evidence.modified_at",
        ),
    )


def _cleanup_failure_from_value(
    value: object,
) -> WorkspaceUploadCleanupFailureEvidence:
    """Restore bounded source cleanup failure evidence."""
    failure = _object(value, "cleanup_failure", _CLEANUP_FAILURE_FIELDS)
    return WorkspaceUploadCleanupFailureEvidence(
        artifact=WorkspaceUploadCleanupArtifact(
            _string(failure["artifact"], "cleanup_failure.artifact")
        ),
        observed_at=_datetime_from_value(
            failure["observed_at"],
            "cleanup_failure.observed_at",
        ),
        attempts=_integer(failure["attempts"], "cleanup_failure.attempts"),
    )


def _object(
    value: object,
    name: str,
    fields: frozenset[str],
) -> dict[str, object]:
    """Require one object with exactly the expected fields."""
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be an object")
    result = {key: item for key, item in value.items() if isinstance(key, str)}
    if len(result) != len(value) or frozenset(result) != fields:
        raise ValueError(f"{name} fields do not match the schema")
    return result


def _string(value: object, name: str) -> str:
    """Require one string."""
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a string")
    return value


def _optional_string(value: object, name: str) -> str | None:
    """Require one optional string."""
    return None if value is None else _string(value, name)


def _integer(value: object, name: str) -> int:
    """Require one integer while rejecting booleans."""
    if type(value) is not int:
        raise ValueError(f"{name} must be an integer")
    return value


def _optional_integer(value: object, name: str) -> int | None:
    """Require one optional integer while rejecting booleans."""
    return None if value is None else _integer(value, name)


def _boolean(value: object, name: str) -> bool:
    """Require one boolean."""
    if type(value) is not bool:
        raise ValueError(f"{name} must be a boolean")
    return value


def _datetime(value: datetime) -> str:
    """Serialize one timezone-aware datetime."""
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Workspace upload datetime must be timezone-aware")
    return value.isoformat()


def _optional_datetime_to_value(value: datetime | None) -> str | None:
    """Serialize one optional timezone-aware datetime."""
    return None if value is None else _datetime(value)


def _datetime_from_value(value: object, name: str) -> datetime:
    """Restore one timezone-aware ISO-8601 datetime."""
    text = _string(value, name)
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as error:
        raise ValueError(f"{name} must be an ISO-8601 datetime") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return parsed


def _optional_datetime_from_value(value: object, name: str) -> datetime | None:
    """Restore one optional timezone-aware ISO-8601 datetime."""
    return None if value is None else _datetime_from_value(value, name)


def _text(value: object) -> str:
    """Decode one Redis text response."""
    if isinstance(value, bytes):
        return value.decode("utf-8")
    if isinstance(value, str):
        return value
    raise ValueError("Redis response must be text")


def _bytes(value: object) -> bytes:
    """Decode one Redis binary response."""
    if isinstance(value, bytes):
        return value
    if isinstance(value, str):
        return value.encode("utf-8")
    raise ValueError("Redis response must be bytes")


def _texts(values: object) -> list[str]:
    """Decode one Redis text list response."""
    if not isinstance(values, list):
        raise ValueError("Redis response must be a list")
    return [_text(value) for value in values]


def _bound(
    record: WorkspaceUploadRecord | None,
    requester_user_id: str,
    workspace_id: str,
    agent_id: str,
) -> bool:
    """Return whether a record matches every requester-visible authority boundary."""
    return record is not None and (
        record.admission.requester_user_id,
        record.admission.workspace_id,
        record.admission.agent_id,
    ) == (requester_user_id, workspace_id, agent_id)


def _same_authority(
    current: WorkspaceUploadRecord,
    replacement: WorkspaceUploadRecord,
) -> bool:
    """Prevent CAS callers from changing immutable admission or lifetime authority."""
    return (
        current.admission == replacement.admission
        and current.created_at == replacement.created_at
        and current.expires_at == replacement.expires_at
        and current.delivery_attempts == replacement.delivery_attempts
        and current.current_delivery_number == replacement.current_delivery_number
    )
