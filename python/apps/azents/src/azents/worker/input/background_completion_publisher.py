"""Publish completed Background Runtime operation as worker input."""

import base64
import dataclasses
from datetime import UTC, datetime
from typing import Literal

from azents.runtime.coordination.data import (
    JsonValue,
    RuntimeBackgroundCompletionClaimStatus,
    RuntimeOperationMetadata,
    RuntimeReplyEventType,
    RuntimeReplyRecord,
)
from azents.runtime.coordination.store import RuntimeCoordinationStore
from azents.worker.input.queue import BackgroundCompletionInput, WorkerInputQueue

_DEFAULT_LIMIT = 100
_DEFAULT_CLAIM_TTL_SECONDS = 60
_CompletionStatus = Literal[
    "completed",
    "failed",
    "expired",
    "interrupted",
    "lost",
    "canceled",
]


@dataclasses.dataclass(frozen=True)
class BackgroundCompletionPublisherConfig:
    """Background completion publisher settings."""

    claimant_id: str
    claim_ttl_seconds: int = _DEFAULT_CLAIM_TTL_SECONDS


class RuntimeBackgroundCompletionPublisher:
    """Publish completed background Runtime operation to Worker input queue."""

    def __init__(
        self,
        *,
        coordination_store: RuntimeCoordinationStore,
        worker_input_queue: WorkerInputQueue,
        config: BackgroundCompletionPublisherConfig,
    ) -> None:
        """Initialize Publisher."""
        self._coordination_store = coordination_store
        self._worker_input_queue = worker_input_queue
        self._config = config

    async def publish_once(self, *, limit: int = _DEFAULT_LIMIT) -> int:
        """Publish one batch of completed background operations."""
        candidates = (
            await self._coordination_store.list_background_completion_candidates(
                limit=limit
            )
        )
        published = 0
        for metadata in candidates:
            if await self._publish_operation(metadata):
                published += 1
        return published

    async def _publish_operation(self, metadata: RuntimeOperationMetadata) -> bool:
        context = metadata.background_context
        if context is None:
            return False
        now = datetime.now(UTC)
        claim = await self._coordination_store.claim_background_completion(
            operation_id=metadata.operation_id,
            claimant_id=self._config.claimant_id,
            claimed_at=now,
            ttl_seconds=self._config.claim_ttl_seconds,
        )
        if claim is None:
            return False
        if claim.status == RuntimeBackgroundCompletionClaimStatus.PUBLISHED:
            return False

        request_id = _request_id(metadata.operation_id)
        replies = await _read_operation_replies(
            self._coordination_store,
            metadata=metadata,
            request_id=request_id,
        )
        completion = _fold_completion(metadata, replies, tool_name=context.tool_name)
        item = BackgroundCompletionInput(
            agent_id=context.agent_id,
            parent_session_id=context.parent_session_id,
            workspace_id=context.workspace_id,
            task_id=context.task_id,
            operation_id=metadata.operation_id,
            request_id=request_id,
            tool_name=context.tool_name,
            status=completion.status,
            text=completion.text,
            created_at=now.isoformat(),
            idempotency_key=context.idempotency_key,
        )
        await self._worker_input_queue.enqueue_background_completion(item)
        await self._coordination_store.mark_background_completion_published(
            operation_id=metadata.operation_id,
            claimant_id=self._config.claimant_id,
            published_at=now,
        )
        return True


@dataclasses.dataclass(frozen=True)
class _Completion:
    status: _CompletionStatus
    text: str


def _fold_completion(
    metadata: RuntimeOperationMetadata,
    replies: list[RuntimeReplyRecord],
    *,
    tool_name: str,
) -> _Completion:
    stdout: list[str] = []
    stderr: list[str] = []
    file_chunks: list[str] = []
    final_payload: dict[str, JsonValue] = {}
    final_event_type = RuntimeReplyEventType.FINAL_ERROR
    for record in replies:
        event = record.event
        if event.request_id != _request_id(metadata.operation_id):
            continue
        if event.event_type == RuntimeReplyEventType.STDOUT:
            stdout.append(_str_payload(event.payload, "text"))
        elif event.event_type == RuntimeReplyEventType.STDERR:
            stderr.append(_str_payload(event.payload, "text"))
        elif event.event_type == RuntimeReplyEventType.FILE_CHUNK:
            file_chunks.append(_file_chunk_preview(event.payload))
        if event.final:
            final_payload = event.payload
            final_event_type = event.event_type

    status: _CompletionStatus
    if final_event_type == RuntimeReplyEventType.FINAL_SUCCESS:
        status = "completed"
    else:
        status = _failure_status(final_payload)

    text = _completion_text(
        operation_id=metadata.operation_id,
        operation_type=tool_name,
        status=status,
        stdout="".join(stdout),
        stderr="".join(stderr),
        file_preview="".join(file_chunks),
        error_message=_error_message(final_payload) if status != "completed" else "",
    )
    return _Completion(status=status, text=text)


async def _read_operation_replies(
    coordination_store: RuntimeCoordinationStore,
    *,
    metadata: RuntimeOperationMetadata,
    request_id: str,
) -> list[RuntimeReplyRecord]:
    """Read only specific operation events from shared reply stream."""
    replies: list[RuntimeReplyRecord] = []
    after_cursor: str | None = None
    while True:
        batch = await coordination_store.read_replies(
            metadata.reply_stream_id,
            after_cursor=after_cursor,
            limit=1000,
        )
        if not batch:
            return replies
        for record in batch:
            if record.event.request_id == request_id:
                replies.append(record)
            if (
                metadata.final_event_cursor is not None
                and record.cursor == metadata.final_event_cursor
            ):
                return replies
        after_cursor = batch[-1].cursor


def _completion_text(
    *,
    operation_id: str,
    operation_type: str,
    status: str,
    stdout: str,
    stderr: str,
    file_preview: str,
    error_message: str,
) -> str:
    title = (
        f"[Background runtime operation '{operation_type}' {status}]\n"
        f"Operation ID: {operation_id}"
    )
    sections: list[str] = [title]
    if stdout:
        sections.append(f"stdout:\n{stdout}")
    if stderr:
        sections.append(f"stderr:\n{stderr}")
    if file_preview:
        sections.append(f"file output:\n{file_preview}")
    if error_message:
        sections.append(f"error:\n{error_message}")
    return "\n\n".join(sections)


def _failure_status(
    payload: dict[str, JsonValue],
) -> Literal["failed", "expired", "interrupted", "lost", "canceled"]:
    code = _str_payload(payload, "error_code").lower()
    if code == "expired":
        return "expired"
    if code == "interrupted":
        return "interrupted"
    if code == "lost":
        return "lost"
    if code == "canceled":
        return "canceled"
    return "failed"


def _error_message(payload: dict[str, JsonValue]) -> str:
    code = _str_payload(payload, "error_code")
    message = _str_payload(payload, "error_message")
    if code and message:
        return f"{code}: {message}"
    return message or code or "Runtime operation failed"


def _str_payload(payload: dict[str, JsonValue], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str):
        return ""
    return value


def _file_chunk_preview(payload: dict[str, JsonValue]) -> str:
    raw = _str_payload(payload, "data_base64")
    if not raw:
        return ""
    try:
        return base64.b64decode(raw).decode("utf-8", errors="replace")
    except ValueError:
        return ""


def _request_id(operation_id: str) -> str:
    return operation_id.removeprefix("operation:")
