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
    RuntimeTransferFailure,
    RuntimeTransferOutcome,
    RuntimeTransferRecord,
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


class RuntimeRunnerTransferResultCoordinator:
    """Derive fenced settlement authority from durable state, never Runner input."""

    def __init__(
        self,
        *,
        state_store: RuntimeTransferStateStore,
        coordination_store: RuntimeCoordinationStore,
        control_protocol: RuntimeControlProtocolService,
        clock: Callable[[], datetime],
    ) -> None:
        """Initialize trusted settlement collaborators.

        :param state_store: authoritative transfer state
        :param coordination_store: durable Runner operation metadata
        :param control_protocol: authoritative final reply append service
        :param clock: timezone-aware result timestamp clock
        """
        self._state_store = state_store
        self._coordination_store = coordination_store
        self._control_protocol = control_protocol
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
            await self._handle_success(record, operation, result, request_id=request_id)
            return
        await self._handle_failure(record, operation, result, request_id=request_id)

    async def _handle_success(
        self,
        record: RuntimeTransferRecord,
        operation: RuntimeOperationMetadata,
        result: RunnerTransferResult,
        *,
        request_id: str,
    ) -> None:
        if result.direction is RunnerTransferDirection.DOWNLOAD:
            if (
                record.stream_claim_id is None
                or record.object is None
                or record.phase.value != "streaming"
                or result.actual_size is None
                or result.sha256 is None
                or record.object.size != result.actual_size
                or record.object.sha256 != result.sha256
            ):
                return
            verifying = await self._state_store.begin_verification(
                record.admission.transfer_id,
                attempt_id=record.admission.attempt_id,
                runtime_id=record.admission.runtime_id,
                desired_generation=record.admission.desired_generation,
                accepted_runner_generation=(record.accepted_runner_generation or 0),
                claim_id=record.stream_claim_id,
                expected_revision=record.revision,
            )
            if verifying is None:
                return
            committed = await self._state_store.mark_committed(
                verifying.admission.transfer_id,
                attempt_id=verifying.admission.attempt_id,
                runtime_id=verifying.admission.runtime_id,
                desired_generation=verifying.admission.desired_generation,
                accepted_runner_generation=(verifying.accepted_runner_generation or 0),
                claim_id=verifying.stream_claim_id or "",
                expected_revision=verifying.revision,
                actual_size=result.actual_size,
                actual_sha256=result.sha256,
            )
            if committed is None:
                return
            settled = await self._state_store.settle(
                committed.admission.transfer_id,
                attempt_id=committed.admission.attempt_id,
                expected_revision=committed.revision,
                outcome=RuntimeTransferOutcome.SUCCEEDED,
                failure=None,
            )
            if settled is None:
                return
            await self._state_store.release_admission(
                settled.admission.transfer_id,
                attempt_id=settled.admission.attempt_id,
                lease_id=settled.lease_id,
            )
        else:
            if (
                record.actual_size != result.actual_size
                or record.actual_sha256 != result.sha256
                or record.phase.value != "available"
            ):
                return
        await self._append_final(operation, result, request_id=request_id, success=True)

    async def _handle_failure(
        self,
        record: RuntimeTransferRecord,
        operation: RuntimeOperationMetadata,
        result: RunnerTransferResult,
        *,
        request_id: str,
    ) -> None:
        failure = _runtime_failure(result.failure)
        outcome = (
            RuntimeTransferOutcome.CANCELLED
            if result.outcome is RunnerTransferOutcome.CANCELLED
            else RuntimeTransferOutcome.FAILED
        )
        settled = await self._state_store.settle(
            record.admission.transfer_id,
            attempt_id=record.admission.attempt_id,
            expected_revision=record.revision,
            outcome=outcome,
            failure=failure,
        )
        if settled is not None:
            await self._state_store.release_admission(
                settled.admission.transfer_id,
                attempt_id=settled.admission.attempt_id,
                lease_id=settled.lease_id,
            )
            await self._append_final(
                operation,
                result,
                request_id=request_id,
                success=False,
            )

    async def _append_final(
        self,
        operation: RuntimeOperationMetadata,
        result: RunnerTransferResult,
        *,
        request_id: str,
        success: bool,
    ) -> None:
        await self._control_protocol.append_reply_event(
            RuntimeReplyEvent(
                request_id=request_id,
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
    if failure is RunnerTransferFailure.PROTOCOL_VIOLATION:
        return RuntimeTransferFailure.FENCED
    return RuntimeTransferFailure.STREAM
