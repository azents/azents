"""Trusted Runtime transfer coordination, dispatch, and bounded repair."""

import hashlib
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from azents.runtime.coordination.data import (
    RuntimeConnectionKind,
    RuntimeConnectionRecord,
    RuntimeCoordinationTarget,
    RuntimeOperationMetadata,
    RuntimeOperationStatus,
    RuntimeOperationTransferDirection,
    RuntimeReplyEvent,
    RuntimeReplyEventType,
    RuntimeRequestEnvelope,
)
from azents.runtime.coordination.store import RuntimeCoordinationStore
from azents.runtime.transfer.data import (
    RuntimeTransferAdmission,
    RuntimeTransferCancellationReason,
    RuntimeTransferCleanupStatus,
    RuntimeTransferFailure,
    RuntimeTransferObject,
    RuntimeTransferOutcome,
    RuntimeTransferRecord,
    cancellation_settlement,
)
from azents.runtime.transfer.store import RuntimeTransferStateStore

_TRANSFER_OPERATION_TYPE = "file.transfer.v1"
_TRANSFER_CANCEL_OPERATION_TYPE = "file.transfer.cancel.v1"
_DEFAULT_REPAIR_PAGE_SIZE = 100
_LOGGER = logging.getLogger(__name__)


class RuntimeTransferDispatchError(RuntimeError):
    """Raised when stable transfer intent delivery cannot be completed."""


class RuntimeTransferCleanup(Protocol):
    """Clean one bounded trusted transfer artifact."""

    async def cleanup(self, record: RuntimeTransferRecord) -> None:
        """Clean exact incomplete or completed transfer work."""
        ...


@dataclass(frozen=True)
class RuntimeTransferDispatch:
    """Stable metadata-only Runner transfer intent delivery result."""

    record: RuntimeTransferRecord
    request_id: str
    request_stream_id: str
    reply_stream_id: str


class RuntimeTransferCoordinator:
    """Coordinate Transfer State with metadata-only Runner delivery."""

    def __init__(
        self,
        *,
        state_store: RuntimeTransferStateStore,
        coordination_store: RuntimeCoordinationStore,
        cleanup: RuntimeTransferCleanup | None,
        clock: Callable[[], datetime],
    ) -> None:
        """Initialize trusted state and coordination dependencies.

        :param state_store: Runtime Control-owned transfer state
        :param coordination_store: shared Runner request/reply coordination store
        :param cleanup: trusted physical-artifact cleanup collaborator
        :param clock: timezone-aware clock for operation metadata and replies
        """
        self._state_store = state_store
        self._coordination_store = coordination_store
        self._cleanup = cleanup
        self._clock = clock

    @property
    def state_store(self) -> RuntimeTransferStateStore:
        """Return the Runtime Control-owned transfer state dependency."""
        return self._state_store

    async def admit(
        self,
        admission: RuntimeTransferAdmission,
        *,
        lease_id: str,
    ) -> RuntimeTransferRecord | None:
        """Admit one trusted transfer attempt.

        :param admission: complete transfer admission metadata
        :param lease_id: bounded admission lease identity
        :returns: admitted record, or None when admission is unavailable
        """
        return await self._state_store.admit(admission, lease_id=lease_id)

    async def mark_ready(
        self,
        record: RuntimeTransferRecord,
        *,
        expected_revision: int,
        object_handle: str,
        size: int,
        sha256: str,
    ) -> RuntimeTransferRecord | None:
        """Mark an admitted attempt ready with its deterministic opaque handle.

        :param record: transfer attempt selected by trusted identity
        :param expected_revision: optimistic state revision
        :param object_handle: deterministic opaque attempt handle
        :param size: verified object size
        :param sha256: verified object SHA-256
        :returns: updated record, or None when transition is invalid
        """
        if object_handle != object_handle_for(record):
            return None
        return await self._state_store.mark_ready(
            record.admission.transfer_id,
            attempt_id=record.admission.attempt_id,
            runtime_id=record.admission.runtime_id,
            desired_generation=record.admission.desired_generation,
            expected_revision=expected_revision,
            object=RuntimeTransferObject(
                key=object_handle,
                size=size,
                sha256=sha256,
            ),
        )

    async def dispatch(
        self,
        record: RuntimeTransferRecord,
        *,
        expected_revision: int,
        dispatch_id: str,
    ) -> RuntimeTransferDispatch:
        """Bind and append one stable metadata-only Runner transfer intent.

        :param record: trusted transfer attempt selected by its identity
        :param expected_revision: client-supplied optimistic state revision
        :param dispatch_id: stable idempotency identity for Runner delivery
        :returns: completed stable delivery information
        :raises RuntimeTransferDispatchError: if delivery cannot be completed
        """
        if _record_expired(record, self._now()):
            await self.expire(record)
            raise RuntimeTransferDispatchError("Transfer deadline expired")
        connection = await self._runner_connection(record)
        if connection is None:
            await self._settle_connection_failure(
                record,
                outcome=RuntimeTransferOutcome.FAILED,
                failure=RuntimeTransferFailure.STREAM,
            )
            raise RuntimeTransferDispatchError("Runner connection is unavailable")
        request_id = dispatch_request_id(record, dispatch_id)
        bound = await self._state_store.bind_dispatch(
            record.admission.transfer_id,
            attempt_id=record.admission.attempt_id,
            runtime_id=record.admission.runtime_id,
            desired_generation=record.admission.desired_generation,
            accepted_runner_generation=connection.generation,
            expected_revision=expected_revision,
            dispatch_id=dispatch_id,
            dispatch_request_id=request_id,
        )
        if bound is None:
            raise RuntimeTransferDispatchError(
                "Transfer dispatch binding is unavailable"
            )
        return await self._deliver(bound)

    async def resume_dispatch(
        self,
        record: RuntimeTransferRecord,
    ) -> RuntimeTransferDispatch | None:
        """Resume one persisted BOUND or DELIVERABLE dispatch outbox record.

        :param record: pending transfer dispatch record
        :returns: completed delivery, or None when fenced during repair
        """
        if record.dispatch_id is None or record.dispatch_request_id is None:
            return None
        try:
            return await self._deliver(record)
        except RuntimeTransferDispatchError:
            return None

    async def cancel(
        self,
        record: RuntimeTransferRecord,
        *,
        expected_revision: int,
        reason: RuntimeTransferCancellationReason,
    ) -> RuntimeTransferRecord | None:
        """Persist and deliver one idempotent typed transfer cancellation.

        :param record: exact transfer attempt selected by trusted identity
        :param expected_revision: optimistic state revision
        :param reason: bounded cancellation cause
        :returns: cancellation or terminal state, when accepted
        """
        cancelled = await self._state_store.request_cancellation(
            record.admission.transfer_id,
            attempt_id=record.admission.attempt_id,
            expected_revision=expected_revision,
            reason=reason,
        )
        if cancelled is None:
            return cancelled
        if cancelled.phase.value == "terminal":
            cancelled = await self._cleanup_before_terminal(cancelled)
            await self._state_store.release_admission(
                cancelled.admission.transfer_id,
                attempt_id=cancelled.admission.attempt_id,
                lease_id=cancelled.lease_id,
            )
            await self._append_terminal_reply(cancelled)
            return cancelled
        await self._deliver_cancellation(cancelled, reason)
        if cancelled.phase.value != "streaming":
            settlement = cancellation_settlement(reason)
            return await self.settle_terminal(
                cancelled,
                outcome=settlement.outcome,
                failure=settlement.failure,
                cleanup_completed=False,
            )
        return cancelled

    async def expire(
        self,
        record: RuntimeTransferRecord,
    ) -> RuntimeTransferRecord | None:
        """Persist deadline cancellation and settle one expired attempt."""
        expired = await self._state_store.request_cancellation(
            record.admission.transfer_id,
            attempt_id=record.admission.attempt_id,
            expected_revision=record.revision,
            reason=RuntimeTransferCancellationReason.DEADLINE,
        )
        if expired is None:
            current = await self._state_store.get(record.admission.transfer_id)
            if (
                current is not None
                and current.admission.attempt_id == record.admission.attempt_id
                and current.phase.value == "terminal"
                and current.terminal_outcome is RuntimeTransferOutcome.EXPIRED
            ):
                current = await self._cleanup_before_terminal(current)
                await self._append_terminal_reply(current)
                return current
            return None
        if expired.phase.value == "terminal":
            expired = await self._cleanup_before_terminal(expired)
            await self._append_terminal_reply(expired)
            return expired
        await self._deliver_cancellation(
            expired,
            RuntimeTransferCancellationReason.DEADLINE,
        )
        if expired.phase.value != "streaming":
            settlement = cancellation_settlement(
                RuntimeTransferCancellationReason.DEADLINE
            )
            return await self.settle_terminal(
                expired,
                outcome=settlement.outcome,
                failure=settlement.failure,
                cleanup_completed=False,
            )
        return expired

    async def settle_terminal(
        self,
        record: RuntimeTransferRecord,
        *,
        outcome: RuntimeTransferOutcome,
        failure: RuntimeTransferFailure | None,
        cleanup_completed: bool,
    ) -> RuntimeTransferRecord | None:
        """Clean, settle, and promptly correlate one authoritative terminal.

        :param record: transfer attempt whose terminal condition is known
        :param outcome: bounded terminal outcome
        :param failure: bounded failure classification, or None for success
        :returns: terminal record when settlement succeeds
        """
        current = await self._state_store.get(record.admission.transfer_id)
        if (
            current is None
            or current.admission.attempt_id != record.admission.attempt_id
        ):
            return None
        if current.cancellation_reason is not None:
            settlement = cancellation_settlement(current.cancellation_reason)
            outcome = settlement.outcome
            failure = settlement.failure
        elif _record_expired(current, self._now()):
            outcome = RuntimeTransferOutcome.EXPIRED
            failure = RuntimeTransferFailure.EXPIRED
        cleanup_completed = bool(
            cleanup_completed
            and current.cleanup_status is RuntimeTransferCleanupStatus.COMPLETE
            and current.multipart_cleanup_handle is None
            and not current.completed_object_cleanup_required
        )
        if not cleanup_completed:
            current = await self._cleanup_before_terminal(current)
        settled = await self._state_store.settle(
            current.admission.transfer_id,
            attempt_id=current.admission.attempt_id,
            expected_revision=current.revision,
            outcome=outcome,
            failure=failure,
        )
        if settled is None:
            return None
        await self._state_store.release_admission(
            settled.admission.transfer_id,
            attempt_id=settled.admission.attempt_id,
            lease_id=settled.lease_id,
        )
        await self._append_terminal_reply(settled)
        return settled

    async def _cleanup_before_terminal(
        self,
        record: RuntimeTransferRecord,
    ) -> RuntimeTransferRecord:
        """Persist, attempt, and retain exact terminal artifact cleanup."""
        if (
            record.phase.value == "terminal"
            and record.cleanup_status is RuntimeTransferCleanupStatus.COMPLETE
            and record.multipart_cleanup_handle is None
            and not record.completed_object_cleanup_required
        ):
            return record
        multipart_required = record.multipart_cleanup_handle is not None
        completed_required = record.completed_object_cleanup_required or (
            record.object is not None
            and (
                record.admission.direction.value == "download"
                or record.actual_size is not None
                or record.phase.value
                in {"verifying", "available", "consuming", "consumed"}
            )
        )
        if not multipart_required and not completed_required:
            return record
        if completed_required:
            marked = await self._state_store.record_completed_object_cleanup(
                record.admission.transfer_id,
                attempt_id=record.admission.attempt_id,
                expected_revision=record.revision,
                status=RuntimeTransferCleanupStatus.RETRYABLE_FAILURE,
                multipart_cleanup_required=multipart_required,
                completed_object_cleanup_required=True,
            )
        else:
            marked = await self._state_store.record_cleanup(
                record.admission.transfer_id,
                attempt_id=record.admission.attempt_id,
                expected_revision=record.revision,
                status=RuntimeTransferCleanupStatus.RETRYABLE_FAILURE,
            )
        if marked is None:
            current = await self._state_store.get(record.admission.transfer_id)
            return current or record
        if self._cleanup is None:
            return marked
        try:
            await self._cleanup.cleanup(marked)
        except Exception:
            _LOGGER.warning(
                "Runtime transfer terminal cleanup requires retry",
                exc_info=True,
                extra={
                    "transfer_id": marked.admission.transfer_id,
                    "attempt_id": marked.admission.attempt_id,
                },
            )
            return marked
        if completed_required:
            cleaned = await self._state_store.record_completed_object_cleanup(
                marked.admission.transfer_id,
                attempt_id=marked.admission.attempt_id,
                expected_revision=marked.revision,
                status=RuntimeTransferCleanupStatus.COMPLETE,
                multipart_cleanup_required=False,
                completed_object_cleanup_required=False,
            )
        else:
            cleaned = await self._state_store.record_cleanup(
                marked.admission.transfer_id,
                attempt_id=marked.admission.attempt_id,
                expected_revision=marked.revision,
                status=RuntimeTransferCleanupStatus.COMPLETE,
            )
        return cleaned or marked

    async def fence_generation(
        self,
        record: RuntimeTransferRecord,
        *,
        missing_connection: bool,
    ) -> RuntimeTransferRecord | None:
        """Fence a transfer whose accepted Runner connection is no longer current.

        :param record: generation-bound transfer record
        :param missing_connection: whether the Runner connection is absent
        :returns: terminal record when settlement succeeds
        """
        if record.phase.value == "terminal":
            return record
        if record.upload_response_committed_at is not None:
            return record
        if record.stream_claim_id is not None:
            cancelled = await self._state_store.request_cancellation(
                record.admission.transfer_id,
                attempt_id=record.admission.attempt_id,
                expected_revision=record.revision,
                reason=RuntimeTransferCancellationReason.SUPERSEDED,
            )
            if cancelled is not None:
                record = cancelled
        outcome = (
            RuntimeTransferOutcome.FAILED
            if missing_connection
            else RuntimeTransferOutcome.SUPERSEDED
        )
        failure = (
            RuntimeTransferFailure.STREAM
            if missing_connection
            else RuntimeTransferFailure.FENCED
        )
        return await self.settle_terminal(
            record,
            outcome=outcome,
            failure=failure,
            cleanup_completed=False,
        )

    async def repair_pending(
        self,
        *,
        page_size: int = _DEFAULT_REPAIR_PAGE_SIZE,
    ) -> int:
        """Repair one bounded page sequence of pending dispatches.

        :param page_size: maximum records per Transfer State page
        :returns: number of records observed for repair
        """
        cursor: str | None = None
        observed = 0
        while True:
            page = await self._state_store.list_pending_dispatches(
                cursor=cursor,
                limit=page_size,
            )
            for record in page.records:
                observed += 1
                if _record_expired(record, self._now()):
                    await self.expire(record)
                else:
                    await self.resume_dispatch(record)
            if page.cursor is None:
                return observed
            cursor = page.cursor

    async def reconcile_generations(
        self,
        *,
        page_size: int = _DEFAULT_REPAIR_PAGE_SIZE,
    ) -> int:
        """Fence every bounded dispatch whose current Runner authority changed.

        :param page_size: maximum records per Transfer State page
        :returns: number of records observed for reconciliation
        """
        cursor: str | None = None
        observed = 0
        while True:
            page = await self._state_store.list_generation_dispatches(
                cursor=cursor,
                limit=page_size,
            )
            for record in page.records:
                observed += 1
                if record.runner_result_confirmed_at is not None:
                    await self._append_upload_success_reply(record)
                    continue
                if _record_expired(record, self._now()):
                    await self.expire(record)
                    continue
                connection = await self._runner_connection(record)
                if connection is None:
                    await self.fence_generation(record, missing_connection=True)
                elif connection.generation != record.accepted_runner_generation:
                    await self.fence_generation(record, missing_connection=False)
            if page.cursor is None:
                return observed
            cursor = page.cursor

    async def repair_terminal_correlations(
        self,
        *,
        page_size: int = _DEFAULT_REPAIR_PAGE_SIZE,
    ) -> int:
        """Retry operation correlation for all retained terminal records."""
        cursor: str | None = None
        observed = 0
        while True:
            page = await self._state_store.list_stale(
                cursor=cursor,
                limit=page_size,
            )
            for record in page.records:
                if record.phase.value != "terminal":
                    continue
                observed += 1
                current = await self._cleanup_before_terminal(record)
                await self._state_store.release_admission(
                    current.admission.transfer_id,
                    attempt_id=current.admission.attempt_id,
                    lease_id=current.lease_id,
                )
                await self._append_terminal_reply(current)
            if page.cursor is None:
                return observed
            cursor = page.cursor

    async def repair_stale_stream_claims(
        self,
        *,
        cleanup: RuntimeTransferCleanup | None,
        page_size: int = _DEFAULT_REPAIR_PAGE_SIZE,
    ) -> int:
        """Fence expired stream owners and preserve cleanup evidence.

        :param cleanup: optional trusted multipart cleanup collaborator
        :param page_size: maximum records per Transfer State page
        :returns: number of expired stream records observed
        """
        cursor: str | None = None
        observed = 0
        while True:
            page = await self._state_store.list_stale_stream_claims(
                cursor=cursor,
                limit=page_size,
            )
            for stale_record in page.records:
                observed += 1
                current = stale_record
                if cleanup is not None and (
                    current.multipart_cleanup_handle is not None
                    or current.completed_object_cleanup_required
                ):
                    try:
                        await cleanup.cleanup(current)
                    except Exception:
                        if current.completed_object_cleanup_required:
                            record_cleanup = (
                                self._state_store.record_completed_object_cleanup
                            )
                            updated = await record_cleanup(
                                current.admission.transfer_id,
                                attempt_id=current.admission.attempt_id,
                                expected_revision=current.revision,
                                status=RuntimeTransferCleanupStatus.RETRYABLE_FAILURE,
                                multipart_cleanup_required=(
                                    current.multipart_cleanup_handle is not None
                                ),
                                completed_object_cleanup_required=True,
                            )
                        else:
                            updated = await self._state_store.record_cleanup(
                                current.admission.transfer_id,
                                attempt_id=current.admission.attempt_id,
                                expected_revision=current.revision,
                                status=RuntimeTransferCleanupStatus.RETRYABLE_FAILURE,
                            )
                    else:
                        if current.completed_object_cleanup_required:
                            updated = (
                                await self._state_store.record_completed_object_cleanup(
                                    current.admission.transfer_id,
                                    attempt_id=current.admission.attempt_id,
                                    expected_revision=current.revision,
                                    status=RuntimeTransferCleanupStatus.COMPLETE,
                                    multipart_cleanup_required=False,
                                    completed_object_cleanup_required=False,
                                )
                            )
                        else:
                            updated = await self._state_store.record_cleanup(
                                current.admission.transfer_id,
                                attempt_id=current.admission.attempt_id,
                                expected_revision=current.revision,
                                status=RuntimeTransferCleanupStatus.COMPLETE,
                            )
                    if updated is not None:
                        current = updated
                if current.phase.value != "terminal":
                    outcome = RuntimeTransferOutcome.FAILED
                    failure = RuntimeTransferFailure.STREAM
                    if current.cancellation_reason is not None:
                        settlement = cancellation_settlement(
                            current.cancellation_reason
                        )
                        outcome = settlement.outcome
                        failure = settlement.failure
                    await self.settle_terminal(
                        current,
                        outcome=outcome,
                        failure=failure,
                        cleanup_completed=False,
                    )
            if page.cursor is None:
                return observed
            cursor = page.cursor

    async def on_runner_replaced(
        self,
        *,
        runtime_id: str,
        previous_generation: int,
        generation: int,
    ) -> None:
        """Fence dispatches bound to a replaced Runner generation.

        :param runtime_id: Runtime whose Runner generation changed
        :param previous_generation: replaced generation
        :param generation: newly accepted generation
        """
        if previous_generation == generation:
            return
        await self._fence_exact_generation(runtime_id, previous_generation)

    async def on_runner_revoked(
        self,
        *,
        runtime_id: str,
        generation: int,
    ) -> None:
        """Fence dispatches bound to a successfully closed Runner generation.

        :param runtime_id: Runtime whose Runner generation closed
        :param generation: closed generation
        """
        await self._fence_exact_generation(runtime_id, generation)

    async def _deliver(self, record: RuntimeTransferRecord) -> RuntimeTransferDispatch:
        if record.dispatch_id is None or record.dispatch_request_id is None:
            raise RuntimeTransferDispatchError("Transfer dispatch identity is missing")
        if _record_expired(record, self._now()):
            await self.expire(record)
            raise RuntimeTransferDispatchError("Transfer deadline expired")
        connection = await self._runner_connection(record)
        if (
            connection is None
            or connection.generation != record.accepted_runner_generation
        ):
            await self.fence_generation(
                record,
                missing_connection=connection is None,
            )
            raise RuntimeTransferDispatchError("Runner generation changed after bind")
        request_stream_id = runner_request_stream_id(
            record.admission.runtime_id,
            connection.generation,
        )
        reply_stream_id = runner_reply_stream_id(
            record.admission.runtime_id,
            connection.generation,
        )
        metadata = RuntimeOperationMetadata(
            operation_id=record.admission.operation_id,
            runtime_id=record.admission.runtime_id,
            target=RuntimeCoordinationTarget.RUNNER,
            generation=connection.generation,
            operation_type=_TRANSFER_OPERATION_TYPE,
            transfer_id=record.admission.transfer_id,
            transfer_attempt_id=record.admission.attempt_id,
            transfer_dispatch_id=record.dispatch_id,
            transfer_direction=RuntimeOperationTransferDirection(
                record.admission.direction.value
            ),
            request_stream_id=request_stream_id,
            reply_stream_id=reply_stream_id,
            status=RuntimeOperationStatus.ACTIVE,
            created_at=self._now(),
            updated_at=self._now(),
            deadline_at=record.admission.deadline_at,
            body_stream_id=None,
            last_heartbeat_at=None,
            last_event_at=None,
            cancel_requested_at=None,
            final_event_cursor=None,
        )
        ensured = await self._coordination_store.ensure_operation_metadata(
            metadata,
            ttl_seconds=_operation_ttl_seconds(metadata),
        )
        if ensured is None:
            raise RuntimeTransferDispatchError("Transfer operation metadata conflicts")
        deliverable = await self._state_store.mark_dispatch_deliverable(
            record.admission.transfer_id,
            attempt_id=record.admission.attempt_id,
            expected_revision=record.revision,
            dispatch_id=record.dispatch_id,
            dispatch_request_id=record.dispatch_request_id,
        )
        if deliverable is None:
            current = await self._state_store.get(record.admission.transfer_id)
            if current is None or current.dispatch_id != record.dispatch_id:
                raise RuntimeTransferDispatchError("Transfer dispatch is unavailable")
            deliverable = current
        if deliverable.dispatch_status.value == "bound":
            raise RuntimeTransferDispatchError("Transfer dispatch is not deliverable")
        if deliverable.dispatch_status.value == "deliverable":
            await self._coordination_store.append_request(
                request_stream_id,
                _intent_envelope(deliverable, reply_stream_id),
            )
        dispatch_id = deliverable.dispatch_id
        if dispatch_id is None:
            raise RuntimeTransferDispatchError("Transfer dispatch identity is missing")
        enqueued = await self._state_store.mark_dispatch_enqueued(
            deliverable.admission.transfer_id,
            attempt_id=deliverable.admission.attempt_id,
            operation_id=deliverable.admission.operation_id,
            expected_revision=deliverable.revision,
            dispatch_id=dispatch_id,
        )
        if enqueued is None:
            current = await self._state_store.get(deliverable.admission.transfer_id)
            if current is None or current.dispatch_id != dispatch_id:
                raise RuntimeTransferDispatchError("Transfer dispatch enqueue failed")
            enqueued = current
        if enqueued.dispatch_status.value != "enqueued":
            raise RuntimeTransferDispatchError("Transfer dispatch is not enqueued")
        return RuntimeTransferDispatch(
            record=enqueued,
            request_id=enqueued.dispatch_request_id or record.dispatch_request_id,
            request_stream_id=request_stream_id,
            reply_stream_id=reply_stream_id,
        )

    async def _runner_connection(
        self,
        record: RuntimeTransferRecord,
    ) -> RuntimeConnectionRecord | None:
        return await self._coordination_store.get_connection(
            kind=RuntimeConnectionKind.RUNNER,
            subject_id=record.admission.runtime_id,
        )

    async def _settle_connection_failure(
        self,
        record: RuntimeTransferRecord,
        *,
        outcome: RuntimeTransferOutcome,
        failure: RuntimeTransferFailure,
    ) -> None:
        await self.settle_terminal(
            record,
            outcome=outcome,
            failure=failure,
            cleanup_completed=False,
        )

    async def _deliver_cancellation(
        self,
        record: RuntimeTransferRecord,
        reason: RuntimeTransferCancellationReason,
    ) -> None:
        operation = await self._coordination_store.get_operation(
            record.admission.operation_id
        )
        if (
            operation is None
            or operation.status is RuntimeOperationStatus.FINAL
            or record.dispatch_id is None
            or record.dispatch_request_id is None
            or record.accepted_runner_generation is None
        ):
            return
        await self._coordination_store.update_operation_status(
            operation.operation_id,
            status=RuntimeOperationStatus.CANCEL_REQUESTED,
            updated_at=self._now(),
            final_event_cursor=None,
        )
        await self._coordination_store.append_request(
            operation.request_stream_id,
            _cancel_envelope(record, operation, reason),
        )

    async def _append_upload_success_reply(
        self,
        record: RuntimeTransferRecord,
    ) -> None:
        if (
            record.runner_result_confirmed_at is None
            or record.actual_size is None
            or record.actual_sha256 is None
        ):
            return
        operation = await self._correlated_operation(record)
        if operation is None:
            return
        await self._coordination_store.append_reply_for_operation(
            operation.reply_stream_id,
            RuntimeReplyEvent(
                request_id=record.dispatch_request_id or record.admission.operation_id,
                runtime_id=record.admission.runtime_id,
                generation=operation.generation,
                event_type=RuntimeReplyEventType.FINAL_SUCCESS,
                payload={
                    "transfer_id": record.admission.transfer_id,
                    "attempt_id": record.admission.attempt_id,
                    "dispatch_id": record.dispatch_id,
                    "outcome": RuntimeTransferOutcome.SUCCEEDED.value,
                    "actual_size": record.actual_size,
                    "sha256": record.actual_sha256,
                    "success": True,
                },
                created_at=self._now(),
                final=True,
            ),
            operation_id=record.admission.operation_id,
        )

    async def _append_terminal_reply(self, record: RuntimeTransferRecord) -> None:
        if record.terminal_outcome is None:
            return
        operation = await self._correlated_operation(record)
        if operation is None:
            return
        success = record.terminal_outcome is RuntimeTransferOutcome.SUCCEEDED
        await self._coordination_store.append_reply_for_operation(
            operation.reply_stream_id,
            RuntimeReplyEvent(
                request_id=record.dispatch_request_id or record.admission.operation_id,
                runtime_id=record.admission.runtime_id,
                generation=operation.generation,
                event_type=(
                    RuntimeReplyEventType.FINAL_SUCCESS
                    if success
                    else RuntimeReplyEventType.FINAL_ERROR
                ),
                payload={
                    "transfer_id": record.admission.transfer_id,
                    "attempt_id": record.admission.attempt_id,
                    "outcome": record.terminal_outcome.value,
                    "failure": record.failure.value if record.failure else None,
                    "success": success,
                },
                created_at=self._now(),
                final=True,
            ),
            operation_id=record.admission.operation_id,
        )

    async def _correlated_operation(
        self,
        record: RuntimeTransferRecord,
    ) -> RuntimeOperationMetadata | None:
        """Return only the durable operation owned by this transfer attempt."""
        operation = await self._coordination_store.get_operation(
            record.admission.operation_id
        )
        if (
            operation is None
            or operation.runtime_id != record.admission.runtime_id
            or operation.transfer_id != record.admission.transfer_id
            or operation.transfer_attempt_id != record.admission.attempt_id
            or operation.transfer_dispatch_id != record.dispatch_id
            or operation.generation != record.accepted_runner_generation
        ):
            return None
        return operation

    async def _fence_exact_generation(
        self,
        runtime_id: str,
        generation: int,
    ) -> None:
        cursor: str | None = None
        while True:
            page = await self._state_store.list_generation_dispatches(
                cursor=cursor,
                limit=_DEFAULT_REPAIR_PAGE_SIZE,
            )
            for record in page.records:
                if (
                    record.admission.runtime_id == runtime_id
                    and record.accepted_runner_generation == generation
                ):
                    if record.runner_result_confirmed_at is not None:
                        await self._append_upload_success_reply(record)
                    elif record.upload_response_committed_at is not None:
                        continue
                    elif _record_expired(record, self._now()):
                        await self.expire(record)
                    else:
                        await self.fence_generation(
                            record,
                            missing_connection=False,
                        )
            if page.cursor is None:
                return
            cursor = page.cursor

    def _now(self) -> datetime:
        now = self._clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError(
                "Runtime transfer coordinator clock must be timezone-aware"
            )
        return now


def object_handle_for(record: RuntimeTransferRecord) -> str:
    """Return the deterministic opaque object handle for one attempt."""
    digest = hashlib.sha256(
        f"{record.admission.transfer_id}\0{record.admission.attempt_id}".encode()
    ).hexdigest()
    return f"transfer-object:{digest}"


def dispatch_request_id(record: RuntimeTransferRecord, dispatch_id: str) -> str:
    """Return a deterministic request identity for stable at-least-once delivery."""
    digest = hashlib.sha256(
        "\0".join(
            (
                record.admission.transfer_id,
                record.admission.attempt_id,
                record.admission.operation_id,
                dispatch_id,
            )
        ).encode()
    ).hexdigest()
    return f"transfer-dispatch:{digest}"


def cancel_request_id(record: RuntimeTransferRecord) -> str:
    """Return the stable cancellation request identity for one dispatch."""
    digest = hashlib.sha256(
        "\0".join(
            (
                record.admission.transfer_id,
                record.admission.attempt_id,
                record.admission.operation_id,
                record.dispatch_id or "",
                "cancel",
            )
        ).encode()
    ).hexdigest()
    return f"transfer-cancel:{digest}"


def runner_request_stream_id(runtime_id: str, generation: int) -> str:
    """Return the current generation-specific Runner request stream identifier."""
    return f"runner:{runtime_id}:generation:{generation}:requests"


def runner_reply_stream_id(runtime_id: str, generation: int) -> str:
    """Return the current generation-specific Runner reply stream identifier."""
    return f"runner:{runtime_id}:generation:{generation}:replies"


def _intent_envelope(
    record: RuntimeTransferRecord,
    reply_stream_id: str,
) -> RuntimeRequestEnvelope:
    return RuntimeRequestEnvelope(
        request_id=record.dispatch_request_id or "",
        runtime_id=record.admission.runtime_id,
        target=RuntimeCoordinationTarget.RUNNER,
        generation=record.accepted_runner_generation or 0,
        operation_type=_TRANSFER_OPERATION_TYPE,
        payload={
            "transfer_id": record.admission.transfer_id,
            "attempt_id": record.admission.attempt_id,
            "runtime_id": record.admission.runtime_id,
            "desired_generation": record.admission.desired_generation,
            "direction": record.admission.direction.value,
            "operation_id": record.admission.operation_id,
            "owner_session_id": record.admission.session_id,
            "runtime_path": record.admission.runtime_path,
            "overwrite": record.admission.overwrite,
            "expected_size": record.admission.expected_size,
            "expected_sha256": record.admission.expected_sha256,
            "deadline_at": record.admission.deadline_at.isoformat(),
            "dispatch_id": record.dispatch_id or "",
        },
        reply_stream_id=reply_stream_id,
        deadline_at=record.admission.deadline_at,
        body_stream_id=None,
    )


def _cancel_envelope(
    record: RuntimeTransferRecord,
    operation: RuntimeOperationMetadata,
    reason: RuntimeTransferCancellationReason,
) -> RuntimeRequestEnvelope:
    return RuntimeRequestEnvelope(
        request_id=cancel_request_id(record),
        runtime_id=record.admission.runtime_id,
        target=RuntimeCoordinationTarget.RUNNER,
        generation=record.accepted_runner_generation or 0,
        operation_type=_TRANSFER_CANCEL_OPERATION_TYPE,
        payload={
            "transfer_id": record.admission.transfer_id,
            "attempt_id": record.admission.attempt_id,
            "runtime_id": record.admission.runtime_id,
            "runner_generation": record.accepted_runner_generation or 0,
            "operation_id": record.admission.operation_id,
            "dispatch_id": record.dispatch_id or "",
            "reason": reason.value,
        },
        reply_stream_id=operation.reply_stream_id,
        deadline_at=record.admission.deadline_at,
        body_stream_id=None,
    )


def _operation_ttl_seconds(metadata: RuntimeOperationMetadata) -> int:
    remaining = (
        int((metadata.deadline_at - metadata.created_at).total_seconds())
        if metadata.deadline_at
        else 0
    )
    return max(900, remaining + 300, 1)


def _record_expired(record: RuntimeTransferRecord, now: datetime) -> bool:
    """Return whether one attempt reached its effective absolute deadline."""
    return (
        record.admission.deadline_at <= now
        or record.logical_expires_at <= now
        or (
            record.phase.value == "terminal"
            and record.terminal_outcome is RuntimeTransferOutcome.EXPIRED
        )
    )
