"""Redis-backed Agent Runtime coordination store."""

import base64
import dataclasses
import json
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta, timezone
from typing import Any, cast

from redis.asyncio import Redis
from redis.exceptions import ResponseError

from azents.runtime.coordination.data import (
    JsonValue,
    RuntimeBackgroundCompletionClaim,
    RuntimeBackgroundCompletionClaimStatus,
    RuntimeBackgroundOperationContext,
    RuntimeBodyChunk,
    RuntimeBodyChunkRecord,
    RuntimeConnectionKind,
    RuntimeConnectionRecord,
    RuntimeCoordinationTarget,
    RuntimeOperationMetadata,
    RuntimeOperationStatus,
    RuntimeReplyEvent,
    RuntimeReplyEventType,
    RuntimeReplyRecord,
    RuntimeRequestEnvelope,
    RuntimeRequestRecord,
)

_BUSYGROUP_PREFIX = "BUSYGROUP"
_PAYLOAD_FIELD = "payload"
_DEFAULT_STREAM_TTL_SECONDS = 60 * 60
_DEFAULT_CONNECTION_GENERATION_TTL_SECONDS = 7 * 24 * 60 * 60
_GENERATION_FENCED_SET_CONNECTION_SCRIPT = """
local raw = redis.call('GET', KEYS[1])
if not raw then
  return 0
end
local ok, payload = pcall(cjson.decode, raw)
if not ok or tonumber(payload['generation']) ~= tonumber(ARGV[1]) then
  return 0
end
redis.call('SET', KEYS[1], ARGV[2], 'EX', tonumber(ARGV[3]))
return 1
"""
_GENERATION_FENCED_DELETE_CONNECTION_SCRIPT = """
local raw = redis.call('GET', KEYS[1])
if not raw then
  return 0
end
local ok, payload = pcall(cjson.decode, raw)
if not ok or tonumber(payload['generation']) ~= tonumber(ARGV[1]) then
  return 0
end
redis.call('DEL', KEYS[1])
return 1
"""


class RedisRuntimeCoordinationStore:
    """Redis Streams and keys implementation of RuntimeCoordinationStore."""

    def __init__(
        self,
        redis: Redis,
        *,
        key_prefix: str = "azents:agent-runtime:coordination",
        stream_ttl_seconds: int = _DEFAULT_STREAM_TTL_SECONDS,
        connection_generation_ttl_seconds: int = (
            _DEFAULT_CONNECTION_GENERATION_TTL_SECONDS
        ),
    ) -> None:
        """Initialize the Redis coordination store."""
        self._redis = redis
        self._key_prefix = key_prefix
        self._stream_ttl_seconds = stream_ttl_seconds
        self._connection_generation_ttl_seconds = connection_generation_ttl_seconds

    async def append_request(
        self,
        stream_id: str,
        envelope: RuntimeRequestEnvelope,
    ) -> str:
        """Append a request envelope and return its cursor."""
        stream_key = self._stream_key("request", stream_id)
        cursor = await self._redis.xadd(
            stream_key,
            {_PAYLOAD_FIELD: _envelope_to_json(envelope)},
        )
        await self._refresh_stream_ttl(stream_key)
        return _decode_text(cursor)

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
        stream_key = self._stream_key("request", stream_id)
        await self._refresh_stream_ttl(stream_key)
        await self._ensure_group(stream_key, consumer_group)
        await self._refresh_stream_ttl(stream_key)
        if reclaim_idle_seconds is not None:
            xautoclaim = cast(Any, self._redis).xautoclaim
            reclaimed = await xautoclaim(
                stream_key,
                consumer_group,
                consumer_id,
                int(reclaim_idle_seconds * 1000),
                start_id="0-0",
                count=1,
            )
            record = _request_record_from_xautoclaim(reclaimed)
            if record is not None:
                await self._refresh_stream_ttl(stream_key)
                return record
        block = block_ms if block_ms > 0 else None
        result = await self._redis.xreadgroup(
            consumer_group,
            consumer_id,
            {stream_key: ">"},
            count=1,
            block=block,
        )
        streams = cast(
            list[tuple[object, list[tuple[object, Mapping[object, object]]]]], result
        )
        if not streams:
            return None
        _stream_name, entries = streams[0]
        cursor, fields = entries[0]
        payload = _payload_field(fields)
        return RuntimeRequestRecord(
            cursor=_decode_text(cursor),
            envelope=_envelope_from_json(payload),
        )

    async def ack_request(
        self,
        stream_id: str,
        *,
        consumer_group: str,
        cursor: str,
    ) -> None:
        """Acknowledge a claimed request."""
        stream_key = self._stream_key("request", stream_id)
        await self._redis.xack(stream_key, consumer_group, cursor)
        await self._refresh_stream_ttl(stream_key)

    async def append_reply(
        self,
        stream_id: str,
        event: RuntimeReplyEvent,
    ) -> str:
        """Append a reply event and return its cursor."""
        stream_key = self._stream_key("reply", stream_id)
        cursor = await self._redis.xadd(
            stream_key,
            {_PAYLOAD_FIELD: _reply_event_to_json(event)},
        )
        await self._refresh_stream_ttl(stream_key)
        return _decode_text(cursor)

    async def read_replies(
        self,
        stream_id: str,
        *,
        after_cursor: str | None,
        limit: int,
    ) -> list[RuntimeReplyRecord]:
        """Read reply events after the supplied cursor."""
        stream_key = self._stream_key("reply", stream_id)
        await self._refresh_stream_ttl(stream_key)
        rows = await self._read_stream(
            stream_key,
            after_cursor=after_cursor,
            limit=limit,
        )
        return [
            RuntimeReplyRecord(
                cursor=cursor,
                event=_reply_event_from_json(payload),
            )
            for cursor, payload in rows
        ]

    async def append_body_chunk(
        self,
        stream_id: str,
        chunk: RuntimeBodyChunk,
    ) -> str:
        """Append a request body chunk and return its cursor."""
        stream_key = self._stream_key("body", stream_id)
        cursor = await self._redis.xadd(
            stream_key,
            {_PAYLOAD_FIELD: _body_chunk_to_json(chunk)},
        )
        await self._refresh_stream_ttl(stream_key)
        return _decode_text(cursor)

    async def read_body_chunks(
        self,
        stream_id: str,
        *,
        after_cursor: str | None,
        limit: int,
    ) -> list[RuntimeBodyChunkRecord]:
        """Read request body chunks after the supplied cursor."""
        stream_key = self._stream_key("body", stream_id)
        await self._refresh_stream_ttl(stream_key)
        rows = await self._read_stream(
            stream_key,
            after_cursor=after_cursor,
            limit=limit,
        )
        return [
            RuntimeBodyChunkRecord(
                cursor=cursor,
                chunk=_body_chunk_from_json(payload),
            )
            for cursor, payload in rows
        ]

    async def put_operation(
        self,
        metadata: RuntimeOperationMetadata,
        *,
        ttl_seconds: int | None,
    ) -> None:
        """Create or replace operation metadata."""
        await self._redis.set(
            self._operation_key(metadata.operation_id),
            _operation_to_json(metadata),
            ex=ttl_seconds,
        )

    async def get_operation(
        self,
        operation_id: str,
    ) -> RuntimeOperationMetadata | None:
        """Get operation metadata."""
        raw = await self._redis.get(self._operation_key(operation_id))
        if raw is None:
            return None
        return _operation_from_json(_decode_text(raw))

    async def update_operation_status(
        self,
        operation_id: str,
        *,
        status: RuntimeOperationStatus,
        updated_at: datetime,
        final_event_cursor: str | None,
    ) -> RuntimeOperationMetadata | None:
        """Update operation status if the operation exists."""
        metadata = await self.get_operation(operation_id)
        if metadata is None:
            return None
        updated = dataclasses.replace(
            metadata,
            status=status,
            updated_at=updated_at,
            final_event_cursor=final_event_cursor,
        )
        ttl = await self._positive_ttl(self._operation_key(operation_id))
        await self.put_operation(updated, ttl_seconds=ttl)
        return updated

    async def heartbeat_operation(
        self,
        operation_id: str,
        *,
        heartbeat_at: datetime,
    ) -> RuntimeOperationMetadata | None:
        """Record an operation heartbeat."""
        metadata = await self.get_operation(operation_id)
        if metadata is None:
            return None
        updated = dataclasses.replace(
            metadata,
            updated_at=heartbeat_at,
            last_heartbeat_at=heartbeat_at,
        )
        ttl = await self._positive_ttl(self._operation_key(operation_id))
        await self.put_operation(updated, ttl_seconds=ttl)
        return updated

    async def delete_operation(self, operation_id: str) -> None:
        """Delete operation metadata."""
        await self._redis.delete(self._operation_key(operation_id))

    async def list_background_completion_candidates(
        self,
        *,
        limit: int,
    ) -> list[RuntimeOperationMetadata]:
        """List final background operations awaiting completion publication."""
        candidates: list[RuntimeOperationMetadata] = []
        async for key in self._redis.scan_iter(  # pyright: ignore[reportAttributeAccessIssue]  # redis-py stub omits SCAN iterator.
            match=self._operation_key("*")
        ):
            raw = await self._redis.get(key)
            if raw is None:
                continue
            metadata = _operation_from_json(_decode_text(raw))
            if (
                metadata.background
                and metadata.background_context is not None
                and metadata.status == RuntimeOperationStatus.FINAL
            ):
                candidates.append(metadata)
                if len(candidates) >= limit:
                    break
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
        generation_key = self._connection_generation_key(kind, subject_id)
        generation = int(
            await self._redis.incr(  # pyright: ignore[reportAttributeAccessIssue]  # redis-py stub omits INCR
                generation_key
            )
        )
        await self._redis.expire(
            generation_key, self._connection_generation_ttl_seconds
        )
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
        await self._redis.set(
            self._connection_key(kind, subject_id),
            _connection_to_json(record),
            ex=ttl_seconds,
        )
        return record

    async def get_connection(
        self,
        *,
        kind: RuntimeConnectionKind,
        subject_id: str,
    ) -> RuntimeConnectionRecord | None:
        """Get the current non-expired connection."""
        key = self._connection_key(kind, subject_id)
        raw = await self._redis.get(key)
        if raw is None:
            return None
        record = _connection_from_json(_decode_text(raw))
        if record.expires_at <= datetime.now(timezone.utc):
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
        record = await self.get_connection(kind=kind, subject_id=subject_id)
        if record is None or record.generation != generation:
            return False
        updated = dataclasses.replace(
            record,
            heartbeat_at=heartbeat_at,
            expires_at=heartbeat_at + timedelta(seconds=ttl_seconds),
        )
        updated = await self._set_connection_if_generation(
            kind=kind,
            subject_id=subject_id,
            generation=generation,
            record=updated,
            ttl_seconds=ttl_seconds,
        )
        return updated

    async def revoke_connection(
        self,
        *,
        kind: RuntimeConnectionKind,
        subject_id: str,
        generation: int,
    ) -> bool:
        """Revoke a connection if generation fencing matches."""
        return await self._delete_connection_if_generation(
            kind=kind,
            subject_id=subject_id,
            generation=generation,
        )

    async def claim_background_completion(
        self,
        *,
        operation_id: str,
        claimant_id: str,
        claimed_at: datetime,
        ttl_seconds: int,
    ) -> RuntimeBackgroundCompletionClaim | None:
        """Claim publishing a background operation completion."""
        claim = RuntimeBackgroundCompletionClaim(
            operation_id=operation_id,
            claimant_id=claimant_id,
            status=RuntimeBackgroundCompletionClaimStatus.CLAIMED,
            claimed_at=claimed_at,
            expires_at=claimed_at + timedelta(seconds=ttl_seconds),
            published_at=None,
        )
        key = self._completion_claim_key(operation_id)
        acquired = await self._redis.set(
            key,
            _completion_claim_to_json(claim),
            nx=True,
            ex=ttl_seconds,
        )
        if bool(acquired):
            return claim
        existing = await self.get_background_completion_claim(operation_id)
        if existing is not None and existing.claimant_id == claimant_id:
            return existing
        return None

    async def get_background_completion_claim(
        self,
        operation_id: str,
    ) -> RuntimeBackgroundCompletionClaim | None:
        """Get a background completion claim."""
        raw = await self._redis.get(self._completion_claim_key(operation_id))
        if raw is None:
            return None
        return _completion_claim_from_json(_decode_text(raw))

    async def mark_background_completion_published(
        self,
        *,
        operation_id: str,
        claimant_id: str,
        published_at: datetime,
    ) -> RuntimeBackgroundCompletionClaim | None:
        """Mark a claimed background completion as published."""
        claim = await self.get_background_completion_claim(operation_id)
        if claim is None or claim.claimant_id != claimant_id:
            return None
        updated = dataclasses.replace(
            claim,
            status=RuntimeBackgroundCompletionClaimStatus.PUBLISHED,
            published_at=published_at,
        )
        key = self._completion_claim_key(operation_id)
        await self._redis.set(
            key,
            _completion_claim_to_json(updated),
            ex=await self._positive_ttl(key),
        )
        return updated

    async def delete_background_completion_claim(
        self,
        operation_id: str,
    ) -> None:
        """Delete a background completion claim."""
        await self._redis.delete(self._completion_claim_key(operation_id))

    async def _set_connection_if_generation(
        self,
        *,
        kind: RuntimeConnectionKind,
        subject_id: str,
        generation: int,
        record: RuntimeConnectionRecord,
        ttl_seconds: int,
    ) -> bool:
        eval_script = cast(Any, self._redis).eval
        result = await eval_script(
            _GENERATION_FENCED_SET_CONNECTION_SCRIPT,
            1,
            self._connection_key(kind, subject_id),
            generation,
            _connection_to_json(record),
            ttl_seconds,
        )
        return bool(result)

    async def _delete_connection_if_generation(
        self,
        *,
        kind: RuntimeConnectionKind,
        subject_id: str,
        generation: int,
    ) -> bool:
        eval_script = cast(Any, self._redis).eval
        result = await eval_script(
            _GENERATION_FENCED_DELETE_CONNECTION_SCRIPT,
            1,
            self._connection_key(kind, subject_id),
            generation,
        )
        return bool(result)

    async def _ensure_group(self, stream_key: str, group_name: str) -> None:
        try:
            await self._redis.xgroup_create(
                stream_key,
                group_name,
                id="0",
                mkstream=True,
            )
        except ResponseError as exc:
            if not str(exc).startswith(_BUSYGROUP_PREFIX):
                raise

    async def _read_stream(
        self,
        key: str,
        *,
        after_cursor: str | None,
        limit: int,
    ) -> list[tuple[str, str]]:
        if limit <= 0:
            return []
        min_cursor = "-" if after_cursor is None else f"({after_cursor}"
        rows = await self._redis.xrange(  # pyright: ignore[reportAttributeAccessIssue]  # redis-py stub omits XRANGE
            key, min=min_cursor, max="+", count=limit
        )
        entries = cast(list[tuple[object, Mapping[object, object]]], rows)
        return [
            (_decode_text(cursor), _payload_field(fields)) for cursor, fields in entries
        ]

    async def _positive_ttl(self, key: str) -> int | None:
        ttl = int(await self._redis.ttl(key))
        if ttl > 0:
            return ttl
        return None

    async def _refresh_stream_ttl(self, key: str) -> None:
        await self._redis.expire(key, self._stream_ttl_seconds)

    def _stream_key(self, stream_kind: str, stream_id: str) -> str:
        return f"{self._key_prefix}:stream:{stream_kind}:{stream_id}"

    def _operation_key(self, operation_id: str) -> str:
        return f"{self._key_prefix}:operation:{operation_id}"

    def _connection_key(self, kind: RuntimeConnectionKind, subject_id: str) -> str:
        return f"{self._key_prefix}:connection:{kind.value}:{subject_id}"

    def _connection_generation_key(
        self,
        kind: RuntimeConnectionKind,
        subject_id: str,
    ) -> str:
        return f"{self._key_prefix}:connection-generation:{kind.value}:{subject_id}"

    def _completion_claim_key(self, operation_id: str) -> str:
        return f"{self._key_prefix}:completion-claim:{operation_id}"


def _request_record_from_xautoclaim(result: object) -> RuntimeRequestRecord | None:
    if not isinstance(result, Sequence) or isinstance(result, (bytes, str)):
        return None
    if len(result) < 2:
        return None
    entries = result[1]
    if not isinstance(entries, Sequence) or isinstance(entries, (bytes, str)):
        return None
    if not entries:
        return None
    entry = entries[0]
    if not isinstance(entry, Sequence) or isinstance(entry, (bytes, str)):
        return None
    if len(entry) != 2:
        return None
    cursor, fields = entry
    if not isinstance(fields, Mapping):
        return None
    payload = _payload_field(fields)
    return RuntimeRequestRecord(
        cursor=_decode_text(cursor),
        envelope=_envelope_from_json(payload),
    )


def _payload_field(fields: Mapping[object, object]) -> str:
    raw = fields.get(_PAYLOAD_FIELD)
    if raw is None:
        raw = fields.get(_PAYLOAD_FIELD.encode())
    if raw is None:
        raise RuntimeError("Runtime coordination stream entry is missing payload")
    return _decode_text(raw)


def _decode_text(value: object) -> str:
    if isinstance(value, bytes):
        return value.decode()
    if isinstance(value, str):
        return value
    return str(value)


def _datetime_to_json(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat()


def _datetime_from_json(value: object) -> datetime | None:
    if value is None:
        return None
    return datetime.fromisoformat(str(value))


def _required_datetime(value: object) -> datetime:
    result = _datetime_from_json(value)
    if result is None:
        raise RuntimeError("Runtime coordination datetime is required")
    return result


def _json_loads(raw: str) -> dict[str, Any]:
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise RuntimeError("Runtime coordination payload must be an object")
    return payload


def _json_dumps(payload: dict[str, object]) -> str:
    return json.dumps(payload, separators=(",", ":"), sort_keys=True)


def _envelope_to_json(envelope: RuntimeRequestEnvelope) -> str:
    return _json_dumps(
        {
            "request_id": envelope.request_id,
            "runtime_id": envelope.runtime_id,
            "target": envelope.target.value,
            "generation": envelope.generation,
            "operation_type": envelope.operation_type,
            "payload": envelope.payload,
            "reply_stream_id": envelope.reply_stream_id,
            "deadline_at": _datetime_to_json(envelope.deadline_at),
            "body_stream_id": envelope.body_stream_id,
        }
    )


def _envelope_from_json(raw: str) -> RuntimeRequestEnvelope:
    payload = _json_loads(raw)
    return RuntimeRequestEnvelope(
        request_id=str(payload["request_id"]),
        runtime_id=str(payload["runtime_id"]),
        target=RuntimeCoordinationTarget(str(payload["target"])),
        generation=int(payload["generation"]),
        operation_type=str(payload["operation_type"]),
        payload=cast(dict[str, JsonValue], payload["payload"]),
        reply_stream_id=str(payload["reply_stream_id"]),
        deadline_at=_datetime_from_json(payload.get("deadline_at")),
        body_stream_id=_optional_str(payload.get("body_stream_id")),
    )


def _reply_event_to_json(event: RuntimeReplyEvent) -> str:
    return _json_dumps(
        {
            "request_id": event.request_id,
            "runtime_id": event.runtime_id,
            "generation": event.generation,
            "event_type": event.event_type.value,
            "payload": event.payload,
            "created_at": _datetime_to_json(event.created_at),
            "final": event.final,
        }
    )


def _reply_event_from_json(raw: str) -> RuntimeReplyEvent:
    payload = _json_loads(raw)
    return RuntimeReplyEvent(
        request_id=str(payload["request_id"]),
        runtime_id=str(payload["runtime_id"]),
        generation=int(payload["generation"]),
        event_type=RuntimeReplyEventType(str(payload["event_type"])),
        payload=cast(dict[str, JsonValue], payload["payload"]),
        created_at=_required_datetime(payload["created_at"]),
        final=bool(payload["final"]),
    )


def _body_chunk_to_json(chunk: RuntimeBodyChunk) -> str:
    return _json_dumps(
        {
            "request_id": chunk.request_id,
            "chunk_id": chunk.chunk_id,
            "data_base64": base64.b64encode(chunk.data).decode(),
            "created_at": _datetime_to_json(chunk.created_at),
            "final": chunk.final,
        }
    )


def _body_chunk_from_json(raw: str) -> RuntimeBodyChunk:
    payload = _json_loads(raw)
    return RuntimeBodyChunk(
        request_id=str(payload["request_id"]),
        chunk_id=int(payload["chunk_id"]),
        data=base64.b64decode(str(payload["data_base64"])),
        created_at=_required_datetime(payload["created_at"]),
        final=bool(payload["final"]),
    )


def _operation_to_json(metadata: RuntimeOperationMetadata) -> str:
    return _json_dumps(
        {
            "operation_id": metadata.operation_id,
            "runtime_id": metadata.runtime_id,
            "target": metadata.target.value,
            "request_stream_id": metadata.request_stream_id,
            "reply_stream_id": metadata.reply_stream_id,
            "status": metadata.status.value,
            "created_at": _datetime_to_json(metadata.created_at),
            "updated_at": _datetime_to_json(metadata.updated_at),
            "deadline_at": _datetime_to_json(metadata.deadline_at),
            "body_stream_id": metadata.body_stream_id,
            "last_heartbeat_at": _datetime_to_json(metadata.last_heartbeat_at),
            "last_event_at": _datetime_to_json(metadata.last_event_at),
            "cancel_requested_at": _datetime_to_json(metadata.cancel_requested_at),
            "final_event_cursor": metadata.final_event_cursor,
            "background": metadata.background,
            "background_context": (
                _background_context_to_payload(metadata.background_context)
                if metadata.background_context is not None
                else None
            ),
        }
    )


def _operation_from_json(raw: str) -> RuntimeOperationMetadata:
    payload = _json_loads(raw)
    return RuntimeOperationMetadata(
        operation_id=str(payload["operation_id"]),
        runtime_id=str(payload["runtime_id"]),
        target=RuntimeCoordinationTarget(str(payload["target"])),
        request_stream_id=str(payload["request_stream_id"]),
        reply_stream_id=str(payload["reply_stream_id"]),
        status=RuntimeOperationStatus(str(payload["status"])),
        created_at=_required_datetime(payload["created_at"]),
        updated_at=_required_datetime(payload["updated_at"]),
        deadline_at=_datetime_from_json(payload.get("deadline_at")),
        body_stream_id=_optional_str(payload.get("body_stream_id")),
        last_heartbeat_at=_datetime_from_json(payload.get("last_heartbeat_at")),
        last_event_at=_datetime_from_json(payload.get("last_event_at")),
        cancel_requested_at=_datetime_from_json(payload.get("cancel_requested_at")),
        final_event_cursor=_optional_str(payload.get("final_event_cursor")),
        background=bool(payload.get("background", False)),
        background_context=_background_context_from_payload(
            payload.get("background_context")
        ),
    )


def _background_context_to_payload(
    context: RuntimeBackgroundOperationContext,
) -> dict[str, str]:
    return {
        "task_id": context.task_id,
        "agent_id": context.agent_id,
        "parent_session_id": context.parent_session_id,
        "workspace_id": context.workspace_id,
        "tool_name": context.tool_name,
        "idempotency_key": context.idempotency_key,
    }


def _background_context_from_payload(
    payload: object,
) -> RuntimeBackgroundOperationContext | None:
    if not isinstance(payload, Mapping):
        return None
    return RuntimeBackgroundOperationContext(
        task_id=str(payload["task_id"]),
        agent_id=str(payload["agent_id"]),
        parent_session_id=str(payload["parent_session_id"]),
        workspace_id=str(payload["workspace_id"]),
        tool_name=str(payload["tool_name"]),
        idempotency_key=str(payload["idempotency_key"]),
    )


def _connection_to_json(record: RuntimeConnectionRecord) -> str:
    return _json_dumps(
        {
            "kind": record.kind.value,
            "subject_id": record.subject_id,
            "connection_id": record.connection_id,
            "owner_replica_id": record.owner_replica_id,
            "generation": record.generation,
            "connected_at": _datetime_to_json(record.connected_at),
            "heartbeat_at": _datetime_to_json(record.heartbeat_at),
            "expires_at": _datetime_to_json(record.expires_at),
            "metadata": record.metadata,
        }
    )


def _connection_from_json(raw: str) -> RuntimeConnectionRecord:
    payload = _json_loads(raw)
    return RuntimeConnectionRecord(
        kind=RuntimeConnectionKind(str(payload["kind"])),
        subject_id=str(payload["subject_id"]),
        connection_id=str(payload["connection_id"]),
        owner_replica_id=str(payload["owner_replica_id"]),
        generation=int(payload["generation"]),
        connected_at=_required_datetime(payload["connected_at"]),
        heartbeat_at=_required_datetime(payload["heartbeat_at"]),
        expires_at=_required_datetime(payload["expires_at"]),
        metadata=cast(dict[str, JsonValue], payload["metadata"]),
    )


def _completion_claim_to_json(claim: RuntimeBackgroundCompletionClaim) -> str:
    return _json_dumps(
        {
            "operation_id": claim.operation_id,
            "claimant_id": claim.claimant_id,
            "status": claim.status.value,
            "claimed_at": _datetime_to_json(claim.claimed_at),
            "expires_at": _datetime_to_json(claim.expires_at),
            "published_at": _datetime_to_json(claim.published_at),
        }
    )


def _completion_claim_from_json(raw: str) -> RuntimeBackgroundCompletionClaim:
    payload = _json_loads(raw)
    return RuntimeBackgroundCompletionClaim(
        operation_id=str(payload["operation_id"]),
        claimant_id=str(payload["claimant_id"]),
        status=RuntimeBackgroundCompletionClaimStatus(str(payload["status"])),
        claimed_at=_required_datetime(payload["claimed_at"]),
        expires_at=_required_datetime(payload["expires_at"]),
        published_at=_datetime_from_json(payload.get("published_at")),
    )


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    return str(value)
