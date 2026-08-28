"""In-memory Agent Runtime coordination store."""

import asyncio
import dataclasses
from datetime import datetime, timedelta, timezone

from azents.runtime.coordination.data import (
    JsonValue,
    RuntimeBodyChunk,
    RuntimeBodyChunkRecord,
    RuntimeConnectionKind,
    RuntimeConnectionRecord,
    RuntimeCoordinationTarget,
    RuntimeFencedMutationResult,
    RuntimeFencedMutationStatus,
    RuntimeOperationMetadata,
    RuntimeOperationReplyAppend,
    RuntimeOperationStatus,
    RuntimeOperationTransferDirection,
    RuntimeReplyEvent,
    RuntimeReplyRecord,
    RuntimeRequestEnvelope,
    RuntimeRequestRecord,
    RuntimeSystemMetricsSample,
)

_SYSTEM_METRICS_RETENTION = timedelta(hours=1)
_SYSTEM_METRICS_MAX_SAMPLES = 60


@dataclasses.dataclass(frozen=True)
class InMemoryRequestPending:
    """In-memory pending request claim metadata."""

    consumer_id: str
    claimed_at: datetime


@dataclasses.dataclass(frozen=True)
class _InMemorySystemMetricsSeries:
    """One generation-scoped bounded metrics series."""

    samples: tuple[RuntimeSystemMetricsSample, ...]
    expires_at: datetime


@dataclasses.dataclass(frozen=True)
class _RuntimeOperationIdentity:
    """Immutable fields used by atomic operation creation."""

    request_id: str
    runtime_id: str
    target: RuntimeCoordinationTarget
    target_subject_id: str
    generation: int
    operation_type: str
    transfer_id: str | None
    transfer_attempt_id: str | None
    transfer_dispatch_id: str | None
    transfer_direction: RuntimeOperationTransferDirection | None
    request_stream_id: str
    reply_stream_id: str
    deadline_at: datetime | None
    body_stream_id: str | None


class InMemoryRuntimeCoordinationStore:
    """Process-local coordination store for standalone deployments and tests."""

    def __init__(self, *, request_reclaim_idle_seconds: float = 30.0) -> None:
        """Initialize the in-memory store."""
        self._lock = asyncio.Lock()
        self._request_reclaim_idle_seconds = request_reclaim_idle_seconds
        self._request_streams: dict[str, list[RuntimeRequestRecord]] = {}
        self._request_group_offsets: dict[tuple[str, str], int] = {}
        self._request_pending: dict[
            tuple[str, str], dict[str, InMemoryRequestPending]
        ] = {}
        self._request_acked: set[tuple[str, str, str]] = set()
        self._reply_streams: dict[str, list[RuntimeReplyRecord]] = {}
        self._body_streams: dict[str, list[RuntimeBodyChunkRecord]] = {}
        self._operation_metadata: dict[str, RuntimeOperationMetadata] = {}
        self._connections: dict[
            tuple[RuntimeConnectionKind, str], RuntimeConnectionRecord
        ] = {}
        self._connection_generations: dict[tuple[RuntimeConnectionKind, str], int] = {}
        self._system_metrics: dict[tuple[str, int], _InMemorySystemMetricsSeries] = {}

    async def append_operation_request_if_connection_current(
        self,
        *,
        connection_kind: RuntimeConnectionKind,
        connection_subject_id: str,
        connection_generation: int,
        metadata: RuntimeOperationMetadata,
        envelope: RuntimeRequestEnvelope,
        ttl_seconds: int | None,
    ) -> RuntimeFencedMutationResult[RuntimeOperationMetadata]:
        """Atomically fence, create operation metadata, and append its request."""
        del ttl_seconds
        async with self._lock:
            status = self._connection_fence_status(
                kind=connection_kind,
                subject_id=connection_subject_id,
                generation=connection_generation,
            )
            if status is not RuntimeFencedMutationStatus.APPLIED:
                return RuntimeFencedMutationResult(status=status, value=None)
            if not _operation_request_matches(
                metadata,
                envelope,
                connection_kind=connection_kind,
                connection_subject_id=connection_subject_id,
                connection_generation=connection_generation,
            ):
                return RuntimeFencedMutationResult(
                    status=RuntimeFencedMutationStatus.OPERATION_REJECTED,
                    value=None,
                )
            existing = self._operation_metadata.get(metadata.operation_id)
            if existing is not None:
                if (
                    existing.status is RuntimeOperationStatus.FINAL
                    or _operation_identity(existing) != _operation_identity(metadata)
                ):
                    return RuntimeFencedMutationResult(
                        status=RuntimeFencedMutationStatus.OPERATION_REJECTED,
                        value=None,
                    )
                if existing.request_cursor is not None:
                    return RuntimeFencedMutationResult(
                        status=RuntimeFencedMutationStatus.APPLIED,
                        value=existing,
                    )
            stream = self._request_streams.setdefault(metadata.request_stream_id, [])
            cursor = str(len(stream) + 1)
            stream.append(RuntimeRequestRecord(cursor=cursor, envelope=envelope))
            updated = dataclasses.replace(
                existing or metadata,
                request_cursor=cursor,
            )
            self._operation_metadata[metadata.operation_id] = updated
            return RuntimeFencedMutationResult(
                status=RuntimeFencedMutationStatus.APPLIED,
                value=updated,
            )

    async def request_operation_cancel_if_connection_current(
        self,
        *,
        connection_kind: RuntimeConnectionKind,
        connection_subject_id: str,
        connection_generation: int,
        operation_id: str,
        expected_runtime_id: str,
        expected_target: RuntimeCoordinationTarget,
        envelope: RuntimeRequestEnvelope,
        updated_at: datetime,
    ) -> RuntimeFencedMutationResult[RuntimeOperationMetadata]:
        """Atomically fence, mark one operation cancelled, and append the request."""
        async with self._lock:
            status = self._connection_fence_status(
                kind=connection_kind,
                subject_id=connection_subject_id,
                generation=connection_generation,
            )
            if status is not RuntimeFencedMutationStatus.APPLIED:
                return RuntimeFencedMutationResult(status=status, value=None)
            metadata = self._operation_metadata.get(operation_id)
            if (
                metadata is None
                or metadata.status
                in {
                    RuntimeOperationStatus.CANCEL_REQUESTED,
                    RuntimeOperationStatus.FINAL,
                }
                or not _operation_matches_connection(
                    metadata,
                    connection_kind=connection_kind,
                    connection_subject_id=connection_subject_id,
                    connection_generation=connection_generation,
                    expected_runtime_id=expected_runtime_id,
                    expected_target=expected_target,
                )
                or not _cancel_request_matches(metadata, envelope, operation_id)
            ):
                return RuntimeFencedMutationResult(
                    status=RuntimeFencedMutationStatus.OPERATION_REJECTED,
                    value=None,
                )
            stream = self._request_streams.setdefault(metadata.request_stream_id, [])
            cursor = str(len(stream) + 1)
            stream.append(RuntimeRequestRecord(cursor=cursor, envelope=envelope))
            updated = dataclasses.replace(
                metadata,
                status=RuntimeOperationStatus.CANCEL_REQUESTED,
                updated_at=updated_at,
                cancel_requested_at=updated_at,
            )
            self._operation_metadata[operation_id] = updated
            return RuntimeFencedMutationResult(
                status=RuntimeFencedMutationStatus.APPLIED,
                value=updated,
            )

    async def try_start_operation_if_connection_current(
        self,
        *,
        connection_kind: RuntimeConnectionKind,
        connection_subject_id: str,
        connection_generation: int,
        operation_id: str,
        expected_runtime_id: str,
        expected_target: RuntimeCoordinationTarget,
        updated_at: datetime,
    ) -> RuntimeFencedMutationResult[RuntimeOperationMetadata]:
        """Atomically fence and transition one exact operation to running."""
        async with self._lock:
            status = self._connection_fence_status(
                kind=connection_kind,
                subject_id=connection_subject_id,
                generation=connection_generation,
            )
            if status is not RuntimeFencedMutationStatus.APPLIED:
                return RuntimeFencedMutationResult(status=status, value=None)
            metadata = self._operation_metadata.get(operation_id)
            if (
                metadata is None
                or metadata.status is not RuntimeOperationStatus.ACTIVE
                or not _operation_matches_connection(
                    metadata,
                    connection_kind=connection_kind,
                    connection_subject_id=connection_subject_id,
                    connection_generation=connection_generation,
                    expected_runtime_id=expected_runtime_id,
                    expected_target=expected_target,
                )
            ):
                return RuntimeFencedMutationResult(
                    status=RuntimeFencedMutationStatus.OPERATION_REJECTED,
                    value=None,
                )
            updated = dataclasses.replace(
                metadata,
                status=RuntimeOperationStatus.RUNNING,
                updated_at=updated_at,
            )
            self._operation_metadata[operation_id] = updated
            return RuntimeFencedMutationResult(
                status=RuntimeFencedMutationStatus.APPLIED,
                value=updated,
            )

    async def append_reply_if_connection_current(
        self,
        *,
        connection_kind: RuntimeConnectionKind,
        connection_subject_id: str,
        connection_generation: int,
        stream_id: str,
        event: RuntimeReplyEvent,
    ) -> RuntimeFencedMutationResult[str]:
        """Atomically fence and append a reply without operation metadata."""
        async with self._lock:
            status = self._connection_fence_status(
                kind=connection_kind,
                subject_id=connection_subject_id,
                generation=connection_generation,
            )
            if status is not RuntimeFencedMutationStatus.APPLIED:
                return RuntimeFencedMutationResult(status=status, value=None)
            if event.generation != connection_generation:
                return RuntimeFencedMutationResult(
                    status=RuntimeFencedMutationStatus.STALE_GENERATION,
                    value=None,
                )
            stream = self._reply_streams.setdefault(stream_id, [])
            cursor = str(len(stream) + 1)
            stream.append(RuntimeReplyRecord(cursor=cursor, event=event))
            return RuntimeFencedMutationResult(
                status=RuntimeFencedMutationStatus.APPLIED,
                value=cursor,
            )

    async def append_operation_reply_if_connection_current(
        self,
        *,
        connection_kind: RuntimeConnectionKind,
        connection_subject_id: str,
        connection_generation: int,
        operation_id: str,
        expected_runtime_id: str,
        expected_target: RuntimeCoordinationTarget,
        stream_id: str,
        event: RuntimeReplyEvent,
    ) -> RuntimeFencedMutationResult[RuntimeOperationReplyAppend]:
        """Atomically fence, append a reply, and mutate one exact operation."""
        async with self._lock:
            status = self._connection_fence_status(
                kind=connection_kind,
                subject_id=connection_subject_id,
                generation=connection_generation,
            )
            if status is not RuntimeFencedMutationStatus.APPLIED:
                return RuntimeFencedMutationResult(status=status, value=None)
            metadata = self._operation_metadata.get(operation_id)
            if (
                metadata is None
                or metadata.status is RuntimeOperationStatus.FINAL
                or metadata.reply_stream_id != stream_id
                or metadata.request_id != event.request_id
                or metadata.runtime_id != event.runtime_id
                or metadata.generation != event.generation
                or not _operation_matches_connection(
                    metadata,
                    connection_kind=connection_kind,
                    connection_subject_id=connection_subject_id,
                    connection_generation=connection_generation,
                    expected_runtime_id=expected_runtime_id,
                    expected_target=expected_target,
                )
            ):
                return RuntimeFencedMutationResult(
                    status=RuntimeFencedMutationStatus.OPERATION_REJECTED,
                    value=None,
                )
            stream = self._reply_streams.setdefault(stream_id, [])
            cursor = str(len(stream) + 1)
            stream.append(RuntimeReplyRecord(cursor=cursor, event=event))
            if event.final:
                updated = dataclasses.replace(
                    metadata,
                    status=RuntimeOperationStatus.FINAL,
                    updated_at=event.created_at,
                    final_event_cursor=cursor,
                    last_event_at=event.created_at,
                )
            else:
                updated = dataclasses.replace(
                    metadata,
                    updated_at=event.created_at,
                    last_heartbeat_at=event.created_at,
                    last_event_at=event.created_at,
                )
            self._operation_metadata[operation_id] = updated
            return RuntimeFencedMutationResult(
                status=RuntimeFencedMutationStatus.APPLIED,
                value=RuntimeOperationReplyAppend(cursor=cursor, metadata=updated),
            )

    async def append_request(
        self,
        stream_id: str,
        envelope: RuntimeRequestEnvelope,
    ) -> str:
        """Append a request envelope and return its cursor."""
        async with self._lock:
            stream = self._request_streams.setdefault(stream_id, [])
            cursor = str(len(stream) + 1)
            stream.append(RuntimeRequestRecord(cursor=cursor, envelope=envelope))
            return cursor

    async def claim_next_request(
        self,
        stream_id: str,
        *,
        consumer_group: str,
        consumer_id: str,
        block_ms: int,
        reclaim_idle_seconds: float | None = None,
    ) -> RuntimeRequestRecord | None:
        """Claim the next request for an active owner consumer."""
        del block_ms
        async with self._lock:
            stream = self._request_streams.get(stream_id, [])
            pending_key = (stream_id, consumer_group)
            pending = self._request_pending.setdefault(pending_key, {})
            now = datetime.now(timezone.utc)
            reclaim_after = (
                self._request_reclaim_idle_seconds
                if reclaim_idle_seconds is None
                else reclaim_idle_seconds
            )
            for record in stream:
                claim = pending.get(record.cursor)
                if claim is None:
                    continue
                if now - claim.claimed_at < timedelta(seconds=reclaim_after):
                    continue
                pending[record.cursor] = InMemoryRequestPending(
                    consumer_id=consumer_id,
                    claimed_at=now,
                )
                return record
            offset_key = (stream_id, consumer_group)
            offset = self._request_group_offsets.get(offset_key, 0)
            while offset < len(stream):
                record = stream[offset]
                offset += 1
                ack_key = (stream_id, consumer_group, record.cursor)
                if ack_key in self._request_acked:
                    continue
                pending[record.cursor] = InMemoryRequestPending(
                    consumer_id=consumer_id,
                    claimed_at=now,
                )
                self._request_group_offsets[offset_key] = offset
                return record
            self._request_group_offsets[offset_key] = offset
            return None

    async def ack_request(
        self,
        stream_id: str,
        *,
        consumer_group: str,
        cursor: str,
    ) -> None:
        """Acknowledge a claimed request."""
        async with self._lock:
            self._request_pending.setdefault((stream_id, consumer_group), {}).pop(
                cursor,
                None,
            )
            self._request_acked.add((stream_id, consumer_group, cursor))

    async def append_reply(
        self,
        stream_id: str,
        event: RuntimeReplyEvent,
    ) -> str:
        """Append a reply event and return its cursor."""
        async with self._lock:
            stream = self._reply_streams.setdefault(stream_id, [])
            cursor = str(len(stream) + 1)
            stream.append(RuntimeReplyRecord(cursor=cursor, event=event))
            return cursor

    async def read_replies(
        self,
        stream_id: str,
        *,
        after_cursor: str | None,
        limit: int,
    ) -> list[RuntimeReplyRecord]:
        """Read reply events after the supplied cursor."""
        async with self._lock:
            stream = self._reply_streams.get(stream_id, [])
            return _read_after_cursor(stream, after_cursor=after_cursor, limit=limit)

    async def append_body_chunk(
        self,
        stream_id: str,
        chunk: RuntimeBodyChunk,
    ) -> str:
        """Append a request body chunk and return its cursor."""
        async with self._lock:
            stream = self._body_streams.setdefault(stream_id, [])
            cursor = str(len(stream) + 1)
            stream.append(RuntimeBodyChunkRecord(cursor=cursor, chunk=chunk))
            return cursor

    async def read_body_chunks(
        self,
        stream_id: str,
        *,
        after_cursor: str | None,
        limit: int,
    ) -> list[RuntimeBodyChunkRecord]:
        """Read request body chunks after the supplied cursor."""
        async with self._lock:
            stream = self._body_streams.get(stream_id, [])
            return _read_after_cursor(stream, after_cursor=after_cursor, limit=limit)

    async def put_operation(
        self,
        metadata: RuntimeOperationMetadata,
        *,
        ttl_seconds: int | None,
    ) -> None:
        """Create or replace operation metadata."""
        del ttl_seconds
        async with self._lock:
            self._operation_metadata[metadata.operation_id] = metadata

    async def ensure_operation_metadata(
        self,
        metadata: RuntimeOperationMetadata,
        *,
        ttl_seconds: int | None,
    ) -> RuntimeOperationMetadata | None:
        """Create metadata once or return an exactly compatible existing record."""
        del ttl_seconds
        async with self._lock:
            existing = self._operation_metadata.get(metadata.operation_id)
            if existing is None:
                self._operation_metadata[metadata.operation_id] = metadata
                return metadata
            if existing.status is RuntimeOperationStatus.FINAL:
                return None
            return (
                existing
                if _operation_identity(existing) == _operation_identity(metadata)
                else None
            )

    async def get_operation(
        self,
        operation_id: str,
    ) -> RuntimeOperationMetadata | None:
        """Get operation metadata."""
        async with self._lock:
            return self._operation_metadata.get(operation_id)

    async def update_operation_status(
        self,
        operation_id: str,
        *,
        status: RuntimeOperationStatus,
        updated_at: datetime,
        final_event_cursor: str | None,
    ) -> RuntimeOperationMetadata | None:
        """Update operation status if the operation exists and is not final."""
        async with self._lock:
            metadata = self._operation_metadata.get(operation_id)
            if metadata is None:
                return None
            if metadata.status is RuntimeOperationStatus.FINAL:
                return metadata
            updated = dataclasses.replace(
                metadata,
                status=status,
                updated_at=updated_at,
                cancel_requested_at=(
                    updated_at
                    if status is RuntimeOperationStatus.CANCEL_REQUESTED
                    else metadata.cancel_requested_at
                ),
                final_event_cursor=final_event_cursor,
            )
            self._operation_metadata[operation_id] = updated
            return updated

    async def try_start_operation(
        self,
        operation_id: str,
        *,
        updated_at: datetime,
    ) -> RuntimeOperationMetadata | None:
        """Atomically transition an operation from ACTIVE to RUNNING."""
        async with self._lock:
            metadata = self._operation_metadata.get(operation_id)
            if metadata is None or metadata.status is not RuntimeOperationStatus.ACTIVE:
                return None
            updated = dataclasses.replace(
                metadata,
                status=RuntimeOperationStatus.RUNNING,
                updated_at=updated_at,
            )
            self._operation_metadata[operation_id] = updated
            return updated

    async def append_reply_for_operation(
        self,
        stream_id: str,
        event: RuntimeReplyEvent,
        *,
        operation_id: str,
    ) -> RuntimeOperationReplyAppend | None:
        """Append a reply and update operation metadata if not already final."""
        async with self._lock:
            metadata = self._operation_metadata.get(operation_id)
            if metadata is None or metadata.status is RuntimeOperationStatus.FINAL:
                return None
            stream = self._reply_streams.setdefault(stream_id, [])
            cursor = str(len(stream) + 1)
            stream.append(RuntimeReplyRecord(cursor=cursor, event=event))
            if event.final:
                updated = dataclasses.replace(
                    metadata,
                    status=RuntimeOperationStatus.FINAL,
                    updated_at=event.created_at,
                    final_event_cursor=cursor,
                    last_event_at=event.created_at,
                )
            else:
                updated = dataclasses.replace(
                    metadata,
                    updated_at=event.created_at,
                    last_heartbeat_at=event.created_at,
                    last_event_at=event.created_at,
                )
            self._operation_metadata[operation_id] = updated
            return RuntimeOperationReplyAppend(cursor=cursor, metadata=updated)

    async def heartbeat_operation(
        self,
        operation_id: str,
        *,
        heartbeat_at: datetime,
    ) -> RuntimeOperationMetadata | None:
        """Record an operation heartbeat."""
        async with self._lock:
            metadata = self._operation_metadata.get(operation_id)
            if metadata is None:
                return None
            if metadata.status is RuntimeOperationStatus.FINAL:
                return metadata
            updated = dataclasses.replace(
                metadata,
                updated_at=heartbeat_at,
                last_heartbeat_at=heartbeat_at,
            )
            self._operation_metadata[operation_id] = updated
            return updated

    async def delete_operation(self, operation_id: str) -> None:
        """Delete operation metadata."""
        async with self._lock:
            self._operation_metadata.pop(operation_id, None)

    async def register_connection(
        self,
        *,
        kind: RuntimeConnectionKind,
        subject_id: str,
        connection_id: str,
        owner_replica_id: str,
        connected_at: datetime,
        heartbeat_at: datetime,
        ttl_seconds: int,
        metadata: dict[str, JsonValue],
    ) -> RuntimeConnectionRecord:
        """Register a current connection and issue a new generation."""
        async with self._lock:
            key = (kind, subject_id)
            generation = self._connection_generations.get(key, 0) + 1
            self._connection_generations[key] = generation
            record = RuntimeConnectionRecord(
                kind=kind,
                subject_id=subject_id,
                connection_id=connection_id,
                owner_replica_id=owner_replica_id,
                generation=generation,
                connected_at=connected_at,
                heartbeat_at=heartbeat_at,
                expires_at=heartbeat_at + timedelta(seconds=ttl_seconds),
                metadata=metadata,
            )
            self._connections[key] = record
            return record

    async def get_connection(
        self,
        *,
        kind: RuntimeConnectionKind,
        subject_id: str,
    ) -> RuntimeConnectionRecord | None:
        """Get the current non-expired connection."""
        async with self._lock:
            record = self._connections.get((kind, subject_id))
            if record is None:
                return None
            if record.expires_at <= datetime.now(timezone.utc):
                self._connections.pop((kind, subject_id), None)
                return None
            return record

    async def heartbeat_connection(
        self,
        *,
        kind: RuntimeConnectionKind,
        subject_id: str,
        generation: int,
        heartbeat_at: datetime,
        ttl_seconds: int,
    ) -> bool:
        """Refresh a connection heartbeat if generation fencing matches."""
        async with self._lock:
            key = (kind, subject_id)
            record = self._connections.get(key)
            if record is None or record.generation != generation:
                return False
            self._connections[key] = dataclasses.replace(
                record,
                heartbeat_at=heartbeat_at,
                expires_at=heartbeat_at + timedelta(seconds=ttl_seconds),
            )
            return True

    async def revoke_connection(
        self,
        *,
        kind: RuntimeConnectionKind,
        subject_id: str,
        generation: int,
    ) -> bool:
        """Revoke a connection if generation fencing matches."""
        async with self._lock:
            key = (kind, subject_id)
            record = self._connections.get(key)
            if record is None or record.generation != generation:
                return False
            self._connections.pop(key, None)
            return True

    async def append_runner_system_metrics(
        self,
        *,
        runtime_id: str,
        generation: int,
        sample: RuntimeSystemMetricsSample,
    ) -> bool:
        """Atomically append a higher-sequence sample to the bounded series."""
        async with self._lock:
            key = (runtime_id, generation)
            series = self._system_metrics.get(key)
            if series is not None and series.expires_at <= sample.measured_at:
                self._system_metrics.pop(key, None)
                series = None
            if series is not None and series.samples[-1].sequence >= sample.sequence:
                return False
            cutoff = sample.measured_at - _SYSTEM_METRICS_RETENTION
            retained = (
                [current for current in series.samples if current.measured_at >= cutoff]
                if series is not None
                else []
            )
            retained.append(sample)
            self._system_metrics[key] = _InMemorySystemMetricsSeries(
                samples=tuple(retained[-_SYSTEM_METRICS_MAX_SAMPLES:]),
                expires_at=sample.measured_at + _SYSTEM_METRICS_RETENTION,
            )
            return True

    async def read_runner_system_metrics(
        self,
        *,
        runtime_id: str,
        generation: int,
        current_time: datetime,
    ) -> list[RuntimeSystemMetricsSample]:
        """Read at most one hour and 60 samples for one Runner generation."""
        async with self._lock:
            key = (runtime_id, generation)
            series = self._system_metrics.get(key)
            if series is None:
                return []
            if series.expires_at <= current_time:
                self._system_metrics.pop(key, None)
                return []
            cutoff = current_time - _SYSTEM_METRICS_RETENTION
            retained = tuple(
                sample for sample in series.samples if sample.measured_at >= cutoff
            )
            if retained != series.samples:
                self._system_metrics[key] = dataclasses.replace(
                    series,
                    samples=retained,
                )
            return list(retained[-_SYSTEM_METRICS_MAX_SAMPLES:])

    def _connection_fence_status(
        self,
        *,
        kind: RuntimeConnectionKind,
        subject_id: str,
        generation: int,
    ) -> RuntimeFencedMutationStatus:
        record = self._connections.get((kind, subject_id))
        if record is None:
            return RuntimeFencedMutationStatus.CONNECTION_MISSING
        if record.expires_at <= datetime.now(timezone.utc):
            self._connections.pop((kind, subject_id), None)
            return RuntimeFencedMutationStatus.CONNECTION_MISSING
        if record.generation != generation:
            return RuntimeFencedMutationStatus.STALE_GENERATION
        return RuntimeFencedMutationStatus.APPLIED


def _read_after_cursor[RecordT](
    records: list[RecordT],
    *,
    after_cursor: str | None,
    limit: int,
) -> list[RecordT]:
    """Read records whose dataclass cursor is after the supplied cursor."""
    if limit <= 0:
        return []
    if after_cursor is None:
        return records[:limit]
    offset = int(after_cursor)
    return records[offset : offset + limit]


def _operation_identity(
    metadata: RuntimeOperationMetadata,
) -> _RuntimeOperationIdentity:
    """Return the immutable identity used by atomic operation creation."""
    return _RuntimeOperationIdentity(
        request_id=metadata.request_id,
        runtime_id=metadata.runtime_id,
        target=metadata.target,
        target_subject_id=metadata.target_subject_id,
        generation=metadata.generation,
        operation_type=metadata.operation_type,
        transfer_id=metadata.transfer_id,
        transfer_attempt_id=metadata.transfer_attempt_id,
        transfer_dispatch_id=metadata.transfer_dispatch_id,
        transfer_direction=metadata.transfer_direction,
        request_stream_id=metadata.request_stream_id,
        reply_stream_id=metadata.reply_stream_id,
        deadline_at=metadata.deadline_at,
        body_stream_id=metadata.body_stream_id,
    )


def _operation_matches_connection(
    metadata: RuntimeOperationMetadata,
    *,
    connection_kind: RuntimeConnectionKind,
    connection_subject_id: str,
    connection_generation: int,
    expected_runtime_id: str,
    expected_target: RuntimeCoordinationTarget,
) -> bool:
    """Return whether operation ownership matches one current connection."""
    return (
        metadata.target is expected_target
        and metadata.target.value == connection_kind.value
        and metadata.target_subject_id == connection_subject_id
        and metadata.generation == connection_generation
        and metadata.runtime_id == expected_runtime_id
    )


def _operation_request_matches(
    metadata: RuntimeOperationMetadata,
    envelope: RuntimeRequestEnvelope,
    *,
    connection_kind: RuntimeConnectionKind,
    connection_subject_id: str,
    connection_generation: int,
) -> bool:
    """Return whether proposed metadata and request share one exact identity."""
    return (
        metadata.status is RuntimeOperationStatus.ACTIVE
        and metadata.request_cursor is None
        and metadata.target.value == connection_kind.value
        and metadata.target_subject_id == connection_subject_id
        and metadata.generation == connection_generation
        and metadata.request_id == envelope.request_id
        and metadata.runtime_id == envelope.runtime_id
        and metadata.target is envelope.target
        and metadata.generation == envelope.generation
        and metadata.operation_type == envelope.operation_type
        and metadata.reply_stream_id == envelope.reply_stream_id
        and metadata.deadline_at == envelope.deadline_at
        and metadata.body_stream_id == envelope.body_stream_id
    )


def _cancel_request_matches(
    metadata: RuntimeOperationMetadata,
    envelope: RuntimeRequestEnvelope,
    operation_id: str,
) -> bool:
    """Return whether one cancellation request targets exact operation metadata."""
    return (
        envelope.runtime_id == metadata.runtime_id
        and envelope.target is metadata.target
        and envelope.generation == metadata.generation
        and envelope.operation_type
        in {
            "operation.cancel",
            "file.transfer.cancel.v1",
        }
        and envelope.payload.get("operation_id") == operation_id
        and envelope.reply_stream_id == metadata.reply_stream_id
        and envelope.deadline_at == metadata.deadline_at
        and envelope.body_stream_id is None
    )
