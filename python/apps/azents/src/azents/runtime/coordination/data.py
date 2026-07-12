"""Agent Runtime coordination data types."""

import dataclasses
import enum
from datetime import datetime

type JsonScalar = str | int | float | bool | None
type JsonValue = JsonScalar | list[JsonValue] | dict[str, JsonValue]


class RuntimeCoordinationTarget(enum.StrEnum):
    """Runtime coordination request target."""

    PROVIDER = "provider"
    RUNNER = "runner"


class RuntimeOperationStatus(enum.StrEnum):
    """Short-lived coordination status for an active Runtime operation."""

    ACTIVE = "active"
    RUNNING = "running"
    CANCEL_REQUESTED = "cancel_requested"
    FINAL = "final"


class RuntimeReplyEventType(enum.StrEnum):
    """Reply stream event type."""

    ACCEPTED = "accepted"
    PROGRESS = "progress"
    STDOUT = "stdout"
    STDERR = "stderr"
    FILE_CHUNK = "file_chunk"
    PROCESS_OUTPUT = "process_output"
    HEARTBEAT = "heartbeat"
    FINAL_SUCCESS = "final_success"
    FINAL_ERROR = "final_error"
    OPERATION_NOT_FOUND = "operation_not_found"


class RuntimeConnectionKind(enum.StrEnum):
    """Runtime connection registry kind."""

    PROVIDER = "provider"
    RUNNER = "runner"


@dataclasses.dataclass(frozen=True)
class RuntimeRequestEnvelope:
    """Request envelope shared between Control replicas."""

    request_id: str
    runtime_id: str
    target: RuntimeCoordinationTarget
    generation: int
    operation_type: str
    payload: dict[str, JsonValue]
    reply_stream_id: str
    deadline_at: datetime | None
    body_stream_id: str | None
    cursor: str | None = None
    stream_id: str | None = None
    consumer_group: str | None = None


@dataclasses.dataclass(frozen=True)
class RuntimeRequestRecord:
    """Request stream entry with its stream cursor."""

    cursor: str
    envelope: RuntimeRequestEnvelope


@dataclasses.dataclass(frozen=True)
class RuntimeReplyEvent:
    """Runtime operation reply event."""

    request_id: str
    runtime_id: str
    generation: int
    event_type: RuntimeReplyEventType
    payload: dict[str, JsonValue]
    created_at: datetime
    final: bool


@dataclasses.dataclass(frozen=True)
class RuntimeReplyRecord:
    """Reply stream entry with its stream cursor."""

    cursor: str
    event: RuntimeReplyEvent


@dataclasses.dataclass(frozen=True)
class RuntimeBodyChunk:
    """Request body stream chunk."""

    request_id: str
    chunk_id: int
    data: bytes
    created_at: datetime
    final: bool


@dataclasses.dataclass(frozen=True)
class RuntimeBodyChunkRecord:
    """Request body stream chunk with its stream cursor."""

    cursor: str
    chunk: RuntimeBodyChunk


@dataclasses.dataclass(frozen=True)
class RuntimeOperationMetadata:
    """Short-lived metadata for an active Runtime operation."""

    operation_id: str
    runtime_id: str
    target: RuntimeCoordinationTarget
    request_stream_id: str
    reply_stream_id: str
    status: RuntimeOperationStatus
    created_at: datetime
    updated_at: datetime
    deadline_at: datetime | None
    body_stream_id: str | None
    last_heartbeat_at: datetime | None
    last_event_at: datetime | None
    cancel_requested_at: datetime | None
    final_event_cursor: str | None


@dataclasses.dataclass(frozen=True)
class RuntimeConnectionRecord:
    """Current Provider or Runner connection registry entry."""

    kind: RuntimeConnectionKind
    subject_id: str
    connection_id: str
    owner_replica_id: str
    generation: int
    connected_at: datetime
    heartbeat_at: datetime
    expires_at: datetime
    metadata: dict[str, JsonValue]
