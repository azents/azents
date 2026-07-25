"""Trusted settlement of Runner transfer result metadata."""

from collections.abc import Callable
from datetime import datetime
from typing import Protocol

from azents_runtime_control.runner_transfer import (
    RunnerTransferDirection,
    RunnerTransferFailure,
    RunnerTransferOutcome,
    RunnerTransferResult,
)

from azents.runtime.control_protocol.service import RuntimeControlProtocolService
from azents.runtime.coordination.data import (
    RuntimeCoordinationTarget,
    RuntimeOperationMetadata,
    RuntimeOperationStatus,
    RuntimeReplyEvent,
    RuntimeReplyEventType,
)
from azents.runtime.coordination.store import RuntimeCoordinationStore
from azents.runtime.transfer.data import (
    RuntimeTransferCleanupStatus,
    RuntimeTransferDirection,
    RuntimeTransferFailure,
    RuntimeTransferOutcome,
    RuntimeTransferRecord,
    cancellation_settlement,
)
from azents.runtime.transfer.store import RuntimeTransferStateStore


class RuntimeRunnerTransferResultSink(Protocol):
    """Settle one structurally validated Runner transfer result."""

    async def handle(
        self,
        result: RunnerTransferResult,
        *,
        request_id: str,
    ) -> None:
        """Correlate trusted state and append one authoritative reply.

        :param result: structurally validated untrusted Runner result
        :param request_id: Runner control message request identity
        """
        ...

    async def handle_failure(
        self,
        operation: RuntimeOperationMetadata,
        *,
        request_id: str,
        error_code: str,
        failure: RuntimeTransferFailure,
    ) -> None:
        """Settle one identity-correlated unusable Runner result."""
        ...


class RuntimeTransferTerminalCoordinator(Protocol):
    """Clean, settle, release, and correlate one terminal transfer."""

    async def settle_terminal(
        self,
        record: RuntimeTransferRecord,
        *,
        outcome: RuntimeTransferOutcome,
        failure: RuntimeTransferFailure | None,
        cleanup_completed: bool,
    ) -> RuntimeTransferRecord | None: ...


class RuntimeRunnerTransferResultCoordinator:
    """Derive fenced settlement authority from durable state, never Runner input."""

    def __init__(
        self,
        *,
        state_store: RuntimeTransferStateStore,
        coordination_store: RuntimeCoordinationStore,
        control_protocol: RuntimeControlProtocolService,
        terminal_coordinator: RuntimeTransferTerminalCoordinator,
        clock: Callable[[], datetime],
    ) -> None:
        """Initialize trusted settlement collaborators.

        :param state_store: authoritative transfer state
        :param coordination_store: durable Runner operation metadata
        :param control_protocol: authoritative final reply append service
        :param terminal_coordinator: terminal cleanup and correlation authority
        :param clock: timezone-aware result timestamp clock
        """
        self._state_store = state_store
        self._coordination_store = coordination_store
        self._control_protocol = control_protocol
        self._terminal_coordinator = terminal_coordinator
        self._clock = clock

    async def handle(self, result: RunnerTransferResult, *, request_id: str) -> None:
        """Settle one result only after exact metadata and state correlation.

        :param result: structurally validated Runner result
        :param request_id: Runner control message request identity
        """
        operation = await self._coordination_store.get_operation(result.operation_id)
        if operation is None or not _matches_operation(operation, result):
            return
        record = await self._state_store.get(result.identity.transfer_id)
        if record is None or not _matches_record(record, result):
            return
        if result.outcome is RunnerTransferOutcome.SUCCEEDED:
            await self._handle_success(record, operation, result)
            return
        await self._handle_failure(record, operation, result)

    async def _handle_success(
        self,
        record: RuntimeTransferRecord,
        operation: RuntimeOperationMetadata,
        result: RunnerTransferResult,
    ) -> None:
        if operation.status is not RuntimeOperationStatus.ACTIVE:
            return
        if result.direction is RunnerTransferDirection.DOWNLOAD:
            if (
                record.stream_claim_id is None
                or record.object is None
                or record.phase.value != "verifying"
                or result.actual_size is None
                or result.sha256 is None
                or record.object.size != result.actual_size
                or record.object.sha256 != result.sha256
            ):
                return
            committed = await self._state_store.mark_committed(
                record.admission.transfer_id,
                attempt_id=record.admission.attempt_id,
                runtime_id=record.admission.runtime_id,
                desired_generation=record.admission.desired_generation,
                accepted_runner_generation=(record.accepted_runner_generation or 0),
                claim_id=record.stream_claim_id,
                expected_revision=record.revision,
                actual_size=result.actual_size,
                actual_sha256=result.sha256,
            )
            if committed is None:
                return
            settled = await self._terminal_coordinator.settle_terminal(
                committed,
                outcome=RuntimeTransferOutcome.SUCCEEDED,
                failure=None,
                cleanup_completed=False,
            )
            if settled is None:
                return
            return
        else:
            if (
                result.actual_size is None
                or result.sha256 is None
                or record.actual_size != result.actual_size
                or record.actual_sha256 != result.sha256
                or record.phase.value != "available"
            ):
                return
            confirmed = await self._state_store.confirm_upload_result(
                record.admission.transfer_id,
                attempt_id=record.admission.attempt_id,
                expected_revision=record.revision,
                actual_size=result.actual_size,
                actual_sha256=result.sha256,
            )
            if confirmed is None:
                return
        await self._append_final(operation, confirmed, result, success=True)

    async def _handle_failure(
        self,
        record: RuntimeTransferRecord,
        operation: RuntimeOperationMetadata,
        result: RunnerTransferResult,
    ) -> None:
        if record.runner_result_confirmed_at is not None:
            return
        if (
            record.admission.direction is RuntimeTransferDirection.UPLOAD
            and record.upload_response_committed_at is not None
        ):
            return
        current = record
        if (
            current.admission.direction is RuntimeTransferDirection.UPLOAD
            and current.phase.value in {"verifying", "available"}
            and current.object is not None
        ):
            cleanup = await self._state_store.record_completed_object_cleanup(
                current.admission.transfer_id,
                attempt_id=current.admission.attempt_id,
                expected_revision=current.revision,
                status=RuntimeTransferCleanupStatus.RETRYABLE_FAILURE,
                multipart_cleanup_required=False,
                completed_object_cleanup_required=True,
            )
            if cleanup is None:
                return
            current = cleanup
        if current.cancellation_reason is not None:
            settlement = cancellation_settlement(current.cancellation_reason)
            outcome = settlement.outcome
            failure = settlement.failure
        else:
            failure = _runtime_failure(result.failure)
            if result.failure is RunnerTransferFailure.DEADLINE_EXCEEDED:
                outcome = RuntimeTransferOutcome.EXPIRED
            elif result.outcome is RunnerTransferOutcome.CANCELLED:
                outcome = RuntimeTransferOutcome.CANCELLED
            else:
                outcome = RuntimeTransferOutcome.FAILED
        settled = await self._terminal_coordinator.settle_terminal(
            current,
            outcome=outcome,
            failure=failure,
            cleanup_completed=False,
        )
        if settled is not None:
            return

    async def handle_failure(
        self,
        operation: RuntimeOperationMetadata,
        *,
        request_id: str,
        error_code: str,
        failure: RuntimeTransferFailure,
    ) -> None:
        """Settle one malformed identity-correlated Runner result."""
        if operation.transfer_id is None or operation.transfer_attempt_id is None:
            return
        record = await self._state_store.get(operation.transfer_id)
        if (
            record is None
            or record.admission.attempt_id != operation.transfer_attempt_id
            or record.admission.operation_id != operation.operation_id
            or record.dispatch_id != operation.transfer_dispatch_id
            or record.accepted_runner_generation != operation.generation
            or record.phase.value == "terminal"
            or record.runner_result_confirmed_at is not None
            or (
                record.admission.direction is RuntimeTransferDirection.UPLOAD
                and record.upload_response_committed_at is not None
            )
        ):
            return
        current = record
        if (
            current.admission.direction is RuntimeTransferDirection.UPLOAD
            and current.phase.value in {"verifying", "available"}
            and current.object is not None
        ):
            cleanup = await self._state_store.record_completed_object_cleanup(
                current.admission.transfer_id,
                attempt_id=current.admission.attempt_id,
                expected_revision=current.revision,
                status=RuntimeTransferCleanupStatus.RETRYABLE_FAILURE,
                multipart_cleanup_required=False,
                completed_object_cleanup_required=True,
            )
            if cleanup is not None:
                current = cleanup
        settled = await self._terminal_coordinator.settle_terminal(
            current,
            outcome=RuntimeTransferOutcome.FAILED,
            failure=failure,
            cleanup_completed=False,
        )
        if settled is None:
            return
        return

    async def _append_final(
        self,
        operation: RuntimeOperationMetadata,
        record: RuntimeTransferRecord,
        result: RunnerTransferResult,
        *,
        success: bool,
    ) -> None:
        await self._control_protocol.append_reply_event(
            RuntimeReplyEvent(
                request_id=(
                    record.dispatch_request_id or record.admission.operation_id
                ),
                runtime_id=result.identity.runtime_id,
                generation=result.identity.runner_generation,
                event_type=(
                    RuntimeReplyEventType.FINAL_SUCCESS
                    if success
                    else RuntimeReplyEventType.FINAL_ERROR
                ),
                payload={
                    "transfer_id": result.identity.transfer_id,
                    "attempt_id": result.identity.attempt_id,
                    "dispatch_id": result.dispatch_id,
                    "outcome": result.outcome.value,
                    "success": success,
                },
                created_at=self._clock(),
                final=True,
            ),
            reply_stream_id=operation.reply_stream_id,
            operation_id=operation.operation_id,
            expected_target=RuntimeCoordinationTarget.RUNNER,
            expected_subject_id=result.identity.runtime_id,
        )


def _matches_operation(
    operation: RuntimeOperationMetadata | None,
    result: RunnerTransferResult,
) -> bool:
    """Check exact durable operation correlation."""
    return bool(
        operation is not None
        and operation.status is not RuntimeOperationStatus.FINAL
        and operation.transfer_id == result.identity.transfer_id
        and operation.transfer_attempt_id == result.identity.attempt_id
        and operation.transfer_dispatch_id == result.dispatch_id
        and operation.transfer_direction is not None
        and operation.transfer_direction.value == result.direction.value
        and operation.runtime_id == result.identity.runtime_id
        and operation.generation == result.identity.runner_generation
    )


def _matches_record(
    record: RuntimeTransferRecord,
    result: RunnerTransferResult,
) -> bool:
    """Check durable transfer attempt and accepted Runner authority."""
    return bool(
        record.admission.attempt_id == result.identity.attempt_id
        and record.admission.runtime_id == result.identity.runtime_id
        and record.admission.direction.value == result.direction.value
        and record.dispatch_id == result.dispatch_id
        and record.accepted_runner_generation == result.identity.runner_generation
        and record.phase.value != "terminal"
    )


def _runtime_failure(
    failure: RunnerTransferFailure | None,
) -> RuntimeTransferFailure:
    """Map bounded Runner failure evidence to a trusted terminal class."""
    if failure is RunnerTransferFailure.CANCELLED:
        return RuntimeTransferFailure.CANCELLED
    if failure is RunnerTransferFailure.INTEGRITY_FAILED:
        return RuntimeTransferFailure.INTEGRITY
    if failure is RunnerTransferFailure.DEADLINE_EXCEEDED:
        return RuntimeTransferFailure.EXPIRED
    if failure is RunnerTransferFailure.PROTOCOL_VIOLATION:
        return RuntimeTransferFailure.FENCED
    return RuntimeTransferFailure.STREAM
