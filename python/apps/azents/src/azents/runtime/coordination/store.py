"""Agent Runtime coordination store interface."""

from datetime import datetime
from typing import Protocol

from azents.runtime.coordination.data import (
    JsonValue,
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


class RuntimeCoordinationStore(Protocol):
    """Short-lived coordination state shared by Control replicas."""

    async def append_request(
        self,
        stream_id: str,
        envelope: RuntimeRequestEnvelope,
    ) -> str:
        """Append a request envelope and return its cursor."""
        ...

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
        ...

    async def ack_request(
        self,
        stream_id: str,
        *,
        consumer_group: str,
        cursor: str,
    ) -> None:
        """Acknowledge a claimed request."""
        ...

    async def append_reply(
        self,
        stream_id: str,
        event: RuntimeReplyEvent,
    ) -> str:
        """Append a reply event and return its cursor."""
        ...

    async def read_replies(
        self,
        stream_id: str,
        *,
        after_cursor: str | None,
        limit: int,
    ) -> list[RuntimeReplyRecord]:
        """Read reply events after the supplied cursor."""
        ...

    async def append_body_chunk(
        self,
        stream_id: str,
        chunk: RuntimeBodyChunk,
    ) -> str:
        """Append a request body chunk and return its cursor."""
        ...

    async def read_body_chunks(
        self,
        stream_id: str,
        *,
        after_cursor: str | None,
        limit: int,
    ) -> list[RuntimeBodyChunkRecord]:
        """Read request body chunks after the supplied cursor."""
        ...

    async def put_operation(
        self,
        metadata: RuntimeOperationMetadata,
        *,
        ttl_seconds: int | None,
    ) -> None:
        """Create or replace operation metadata."""
        ...

    async def get_operation(
        self,
        operation_id: str,
    ) -> RuntimeOperationMetadata | None:
        """Get operation metadata."""
        ...

    async def update_operation_status(
        self,
        operation_id: str,
        *,
        status: RuntimeOperationStatus,
        updated_at: datetime,
        final_event_cursor: str | None,
    ) -> RuntimeOperationMetadata | None:
        """Update operation status if the operation exists and is not already final."""
        ...

    async def try_start_operation(
        self,
        operation_id: str,
        *,
        updated_at: datetime,
    ) -> RuntimeOperationMetadata | None:
        """Atomically transition an operation from ACTIVE to RUNNING.

        :returns: Updated metadata when the start claim succeeds, otherwise
            ``None`` when the operation is missing or not startable.
        """
        ...

    async def append_reply_for_operation(
        self,
        stream_id: str,
        event: RuntimeReplyEvent,
        *,
        operation_id: str,
    ) -> tuple[str, RuntimeOperationMetadata] | None:
        """Append a reply and update operation metadata if not already final.

        Final events mark the operation final with the new cursor. Non-final
        events refresh the operation heartbeat. Returns ``None`` when the
        operation is missing or already final so late Runner events cannot
        replace an authoritative final cursor.
        """
        ...

    async def heartbeat_operation(
        self,
        operation_id: str,
        *,
        heartbeat_at: datetime,
    ) -> RuntimeOperationMetadata | None:
        """Record an operation heartbeat."""
        ...

    async def delete_operation(self, operation_id: str) -> None:
        """Delete operation metadata."""
        ...

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
        ...

    async def get_connection(
        self,
        *,
        kind: RuntimeConnectionKind,
        subject_id: str,
    ) -> RuntimeConnectionRecord | None:
        """Get the current non-expired connection."""
        ...

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
        ...

    async def revoke_connection(
        self,
        *,
        kind: RuntimeConnectionKind,
        subject_id: str,
        generation: int,
    ) -> bool:
        """Revoke a connection if generation fencing matches."""
        ...
