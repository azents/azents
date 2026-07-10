"""In-memory Agent Runtime coordination store."""

import asyncio
import dataclasses
from datetime import datetime, timedelta, timezone

from azents.runtime.coordination.data import (
    JsonValue,
    RuntimeBackgroundCompletionClaim,
    RuntimeBackgroundCompletionClaimStatus,
    RuntimeBodyChunk,
    RuntimeBodyChunkRecord,
    RuntimeConnectionKind,
    RuntimeConnectionRecord,
    RuntimeOperationMetadata,
    RuntimeOperationStatus,
    RuntimeReplyEvent,
    RuntimeReplyRecord,
    RuntimeRequestEnvelope,
    RuntimeRequestRecord,
)


@dataclasses.dataclass(frozen=True)
class InMemoryRequestPending:
    """In-memory pending request claim metadata."""

    consumer_id: str
    claimed_at: datetime


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
        self._completion_claims: dict[str, RuntimeBackgroundCompletionClaim] = {}

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
    ) -> tuple[str, RuntimeOperationMetadata] | None:
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
            return cursor, updated

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

    async def list_background_completion_candidates(
        self,
        *,
        limit: int,
    ) -> list[RuntimeOperationMetadata]:
        """List final background operations awaiting completion publication."""
        async with self._lock:
            candidates = [
                metadata
                for metadata in self._operation_metadata.values()
                if metadata.background
                and metadata.background_context is not None
                and metadata.status == RuntimeOperationStatus.FINAL
            ]
            candidates.sort(key=lambda metadata: metadata.updated_at)
            return candidates[:limit]

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

    async def claim_background_completion(
        self,
        *,
        operation_id: str,
        claimant_id: str,
        claimed_at: datetime,
        ttl_seconds: int,
    ) -> RuntimeBackgroundCompletionClaim | None:
        """Claim publishing a background operation completion."""
        async with self._lock:
            existing = self._completion_claims.get(operation_id)
            if existing is not None and existing.expires_at > claimed_at:
                if existing.claimant_id == claimant_id:
                    return existing
                return None
            claim = RuntimeBackgroundCompletionClaim(
                operation_id=operation_id,
                claimant_id=claimant_id,
                status=RuntimeBackgroundCompletionClaimStatus.CLAIMED,
                claimed_at=claimed_at,
                expires_at=claimed_at + timedelta(seconds=ttl_seconds),
                published_at=None,
            )
            self._completion_claims[operation_id] = claim
            return claim

    async def get_background_completion_claim(
        self,
        operation_id: str,
    ) -> RuntimeBackgroundCompletionClaim | None:
        """Get a background completion claim."""
        async with self._lock:
            return self._completion_claims.get(operation_id)

    async def mark_background_completion_published(
        self,
        *,
        operation_id: str,
        claimant_id: str,
        published_at: datetime,
    ) -> RuntimeBackgroundCompletionClaim | None:
        """Mark a claimed background completion as published."""
        async with self._lock:
            existing = self._completion_claims.get(operation_id)
            if existing is None or existing.claimant_id != claimant_id:
                return None
            claim = dataclasses.replace(
                existing,
                status=RuntimeBackgroundCompletionClaimStatus.PUBLISHED,
                published_at=published_at,
            )
            self._completion_claims[operation_id] = claim
            return claim

    async def delete_background_completion_claim(
        self,
        operation_id: str,
    ) -> None:
        """Delete a background completion claim."""
        async with self._lock:
            self._completion_claims.pop(operation_id, None)


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
