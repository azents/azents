"""Agent Runtime coordination store interface."""

from datetime import datetime
from typing import Protocol

from azents.runtime.coordination.data import (
    JsonValue,
    RuntimeBodyChunk,
    RuntimeBodyChunkRecord,
    RuntimeConnectionKind,
    RuntimeConnectionRecord,
    RuntimeCoordinationTarget,
    RuntimeFencedMutationResult,
    RuntimeOperationMetadata,
    RuntimeOperationReplyAppend,
    RuntimeOperationStatus,
    RuntimeReplyEvent,
    RuntimeReplyRecord,
    RuntimeRequestEnvelope,
    RuntimeRequestRecord,
    RuntimeSystemMetricsSample,
)


class RuntimeCoordinationStore(Protocol):
    """Short-lived coordination state shared by Control replicas."""

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
        ...

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
        ...

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
        ...

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
        ...

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
        ...

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

    async def ensure_operation_metadata(
        self,
        metadata: RuntimeOperationMetadata,
        *,
        ttl_seconds: int | None,
    ) -> RuntimeOperationMetadata | None:
        """Create metadata once or return an exactly compatible existing record."""
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
    ) -> RuntimeOperationReplyAppend | None:
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

    async def append_runner_system_metrics(
        self,
        *,
        runtime_id: str,
        generation: int,
        sample: RuntimeSystemMetricsSample,
    ) -> bool:
        """Atomically append a higher-sequence sample to the bounded series."""
        ...

    async def read_runner_system_metrics(
        self,
        *,
        runtime_id: str,
        generation: int,
        current_time: datetime,
    ) -> list[RuntimeSystemMetricsSample]:
        """Read at most one hour and 60 samples for one Runner generation."""
        ...
