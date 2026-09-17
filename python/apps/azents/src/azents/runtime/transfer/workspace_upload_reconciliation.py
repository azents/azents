"""Runtime delivery and reconciliation for Workspace uploads."""

from __future__ import annotations

import asyncio
import base64
from collections.abc import Callable
from datetime import datetime, timedelta

from azcommon.uuid import uuid7

from azents.runtime.transfer.coordinator import (
    RuntimeTransferCoordinator,
    RuntimeTransferDispatchError,
)
from azents.runtime.transfer.data import (
    RuntimeTransferAdmission,
    RuntimeTransferCancellationReason,
    RuntimeTransferDirection,
    RuntimeTransferFailure,
    RuntimeTransferOutcome,
    RuntimeTransferPhase,
    RuntimeTransferRecord,
    RuntimeTransferSourceTransport,
)
from azents.runtime.transfer.workspace_upload import (
    WorkspaceUploadDeliveryAttempt,
    WorkspaceUploadDeliveryOutcome,
    WorkspaceUploadDestinationEvidence,
    WorkspaceUploadFailure,
    WorkspaceUploadPhase,
    WorkspaceUploadRecord,
)
from azents.runtime.transfer.workspace_upload_coordinator import (
    WorkspaceUploadReconciliationHandler,
)
from azents.runtime.transfer.workspace_upload_object import WorkspaceUploadObjectStore
from azents.runtime.transfer.workspace_upload_store import WorkspaceUploadStore


class WorkspaceUploadRuntimeReconciliationHandler(WorkspaceUploadReconciliationHandler):
    """Drive one claimed Workspace upload through Runtime Transfer."""

    def __init__(
        self,
        *,
        store: WorkspaceUploadStore,
        object_store: WorkspaceUploadObjectStore,
        transfer_coordinator: RuntimeTransferCoordinator,
        product_maximum_size: int,
        provider_maximum_size: int,
        status_poll_interval: timedelta,
        clock: Callable[[], datetime],
        delivery_attempt_id_factory: Callable[[], str] | None = None,
        transfer_id_factory: Callable[[], str] | None = None,
        transfer_attempt_id_factory: Callable[[], str] | None = None,
        transfer_lease_id_factory: Callable[[], str] | None = None,
        dispatch_id_factory: Callable[[], str] | None = None,
    ) -> None:
        """Initialize the trusted Workspace-to-Runtime delivery bridge."""
        if min(product_maximum_size, provider_maximum_size) <= 0:
            raise ValueError("Workspace upload transfer bounds must be positive")
        if status_poll_interval <= timedelta():
            raise ValueError("Workspace upload status poll interval must be positive")
        self.store = store
        self.object_store = object_store
        self.transfer_coordinator = transfer_coordinator
        self.product_maximum_size = product_maximum_size
        self.provider_maximum_size = provider_maximum_size
        self.status_poll_interval = status_poll_interval
        self.clock = clock
        self.delivery_attempt_id_factory = delivery_attempt_id_factory or (
            lambda: uuid7().hex
        )
        self.transfer_id_factory = transfer_id_factory or (lambda: uuid7().hex)
        self.transfer_attempt_id_factory = transfer_attempt_id_factory or (
            lambda: uuid7().hex
        )
        self.transfer_lease_id_factory = transfer_lease_id_factory or (
            lambda: uuid7().hex
        )
        self.dispatch_id_factory = dispatch_id_factory or (lambda: uuid7().hex)

    async def reconcile(self, record: WorkspaceUploadRecord) -> None:
        """Advance one claimed upload until its current delivery settles."""
        current = await self._current(record)
        if (
            current is None
            or current.phase is not WorkspaceUploadPhase.MOVING_TO_RUNTIME
            or current.source_handle is None
        ):
            return
        current, attempt = await self._ensure_attempt(current)
        if current is None or attempt is None:
            return

        runtime_record = await self.transfer_coordinator.state_store.get(
            attempt.transfer_id
        )
        if runtime_record is None:
            current = await self._current(current)
            if (
                current is None
                or current.phase is not WorkspaceUploadPhase.MOVING_TO_RUNTIME
            ):
                return
            if current.cancellation_requested_at is not None:
                await self._settle(
                    current,
                    attempt,
                    outcome=WorkspaceUploadDeliveryOutcome.CANCELLED,
                    failure=WorkspaceUploadFailure.CANCELLED,
                )
                return
            runtime_record = await self.transfer_coordinator.admit(
                self._runtime_admission(current, attempt),
                lease_id=self.transfer_lease_id_factory(),
            )
            if runtime_record is None:
                await self._settle(
                    current,
                    attempt,
                    outcome=WorkspaceUploadDeliveryOutcome.RETRYABLE_FAILURE,
                    failure=WorkspaceUploadFailure.ADMISSION,
                )
                return

        while True:
            current = await self._current(current)
            if (
                current is None
                or current.phase is not WorkspaceUploadPhase.MOVING_TO_RUNTIME
            ):
                return
            runtime_record = await self.transfer_coordinator.state_store.get(
                attempt.transfer_id
            )
            if runtime_record is None:
                runtime_record = await self.transfer_coordinator.admit(
                    self._runtime_admission(current, attempt),
                    lease_id=self.transfer_lease_id_factory(),
                )
                if runtime_record is None:
                    await self._settle(
                        current,
                        attempt,
                        outcome=WorkspaceUploadDeliveryOutcome.RETRYABLE_FAILURE,
                        failure=WorkspaceUploadFailure.ADMISSION,
                    )
                    return

            if current.cancellation_requested_at is not None:
                if runtime_record.phase is not RuntimeTransferPhase.TERMINAL:
                    cancelled = await self.transfer_coordinator.cancel(
                        runtime_record,
                        expected_revision=runtime_record.revision,
                        reason=RuntimeTransferCancellationReason.CALLER,
                    )
                    runtime_record = cancelled or runtime_record

            if runtime_record.phase is RuntimeTransferPhase.TERMINAL:
                await self._settle_from_runtime(current, attempt, runtime_record)
                return

            if self.clock() >= min(
                current.expires_at,
                runtime_record.admission.deadline_at,
                runtime_record.logical_expires_at,
            ):
                expired = await self.transfer_coordinator.expire(runtime_record)
                runtime_record = expired or runtime_record
                if runtime_record.phase is RuntimeTransferPhase.TERMINAL:
                    await self._settle_from_runtime(current, attempt, runtime_record)
                    return

            if runtime_record.phase is RuntimeTransferPhase.PREPARING:
                try:
                    ready = await self._prepare(current, runtime_record)
                except asyncio.CancelledError:
                    raise
                except FileNotFoundError:
                    failed = await self._settle_runtime_failure(
                        runtime_record,
                        RuntimeTransferFailure.INTEGRITY,
                    )
                    await self._settle_from_runtime(current, attempt, failed)
                    return
                except ValueError:
                    failed = await self._settle_runtime_failure(
                        runtime_record,
                        RuntimeTransferFailure.INTEGRITY,
                    )
                    await self._settle_from_runtime(current, attempt, failed)
                    return
                except Exception:
                    failed = await self._settle_runtime_failure(
                        runtime_record,
                        RuntimeTransferFailure.STREAM,
                    )
                    await self._settle_from_runtime(current, attempt, failed)
                    return
                runtime_record = ready or runtime_record
                continue

            if (
                runtime_record.phase is RuntimeTransferPhase.READY
                and runtime_record.dispatch_status.value != "enqueued"
            ):
                try:
                    dispatched = await self.transfer_coordinator.dispatch(
                        runtime_record,
                        expected_revision=runtime_record.revision,
                        dispatch_id=self.dispatch_id_factory(),
                    )
                except asyncio.CancelledError:
                    raise
                except RuntimeTransferDispatchError:
                    dispatched = None
                if dispatched is not None:
                    runtime_record = dispatched.record
                else:
                    runtime_record = (
                        await self.transfer_coordinator.state_store.get(
                            attempt.transfer_id
                        )
                        or runtime_record
                    )
                continue

            await asyncio.sleep(
                min(
                    self.status_poll_interval.total_seconds(),
                    max(
                        0.0,
                        (
                            min(
                                current.expires_at,
                                runtime_record.admission.deadline_at,
                                runtime_record.logical_expires_at,
                            )
                            - self.clock()
                        ).total_seconds(),
                    ),
                )
            )

    async def _ensure_attempt(
        self,
        record: WorkspaceUploadRecord,
    ) -> tuple[WorkspaceUploadRecord | None, WorkspaceUploadDeliveryAttempt | None]:
        """Append the first immutable delivery child after source verification."""
        if record.delivery_attempts:
            latest = record.delivery_attempts[-1]
            if latest.completed_at is None:
                return record, latest
        attempt = WorkspaceUploadDeliveryAttempt(
            number=len(record.delivery_attempts) + 1,
            attempt_id=self.delivery_attempt_id_factory(),
            transfer_id=self.transfer_id_factory(),
            transfer_attempt_id=self.transfer_attempt_id_factory(),
            overwrite=False,
            conflict_precondition=None,
            created_at=self.clock(),
            completed_at=None,
            outcome=None,
            failure=None,
            conflict_revision=None,
            destination_evidence=None,
        )
        appended = await self.store.append_delivery_attempt(
            record.admission.upload_id,
            requester_user_id=record.admission.requester_user_id,
            workspace_id=record.admission.workspace_id,
            agent_id=record.admission.agent_id,
            expected_revision=record.revision,
            attempt=attempt,
        )
        if appended is None:
            return None, None
        return appended, attempt

    async def _prepare(
        self,
        upload: WorkspaceUploadRecord,
        runtime_record: RuntimeTransferRecord,
    ) -> RuntimeTransferRecord | None:
        """Verify the retained source and mark the direct transfer ready."""
        source_handle = upload.source_handle
        if source_handle is None or upload.actual_sha256 is None:
            raise ValueError("Workspace upload source manifest is unavailable")
        verified = await self.object_store.verify_source_object(
            source_handle=source_handle,
            expected_size=upload.admission.expected_size,
            expected_sha256=upload.actual_sha256,
        )
        if (
            verified.metadata.content_length != upload.admission.expected_size
            or verified.sha256 != upload.actual_sha256
        ):
            raise ValueError("Workspace upload source verification failed")
        return await self.transfer_coordinator.mark_ready_direct(
            runtime_record,
            expected_revision=runtime_record.revision,
            source_handle=source_handle,
            size=verified.metadata.content_length,
            sha256=verified.sha256,
        )

    def _runtime_admission(
        self,
        upload: WorkspaceUploadRecord,
        attempt: WorkspaceUploadDeliveryAttempt,
    ) -> RuntimeTransferAdmission:
        """Build the exact Runtime Transfer admission for one upload attempt."""

        return RuntimeTransferAdmission(
            transfer_id=attempt.transfer_id,
            attempt_id=attempt.transfer_attempt_id,
            direction=RuntimeTransferDirection.DOWNLOAD,
            runtime_id=upload.admission.runtime_id,
            desired_generation=upload.admission.desired_generation,
            operation_id=attempt.attempt_id,
            session_id=upload.admission.session_id,
            agent_id=upload.admission.agent_id,
            runtime_path=upload.admission.destination_path,
            overwrite=attempt.overwrite,
            conflict_precondition=(
                None
                if attempt.conflict_precondition is None
                else _decode_token(attempt.conflict_precondition)
            ),
            expected_size=upload.admission.expected_size,
            expected_sha256=upload.actual_sha256,
            product_maximum_size=self.product_maximum_size,
            provider_maximum_size=self.provider_maximum_size,
            deadline_at=upload.admission.deadline_at,
            source_expires_at=upload.expires_at,
            resource_class="workspace-upload",
            source_transport=RuntimeTransferSourceTransport.DIRECT_OBJECT,
            source_handle=upload.source_handle,
        )

    async def _settle_runtime_failure(
        self,
        runtime_record: RuntimeTransferRecord,
        failure: RuntimeTransferFailure,
    ) -> RuntimeTransferRecord:
        """Settle an inner transfer that failed before Runner dispatch."""
        settled = await self.transfer_coordinator.settle_terminal(
            runtime_record,
            outcome=RuntimeTransferOutcome.FAILED,
            failure=failure,
            cleanup_completed=False,
            destination_conflict=None,
        )
        return settled or runtime_record

    async def _settle_from_runtime(
        self,
        upload: WorkspaceUploadRecord,
        attempt: WorkspaceUploadDeliveryAttempt,
        runtime_record: RuntimeTransferRecord,
    ) -> None:
        """Project one authoritative inner terminal into Workspace metadata."""
        outcome = runtime_record.terminal_outcome
        failure = runtime_record.failure
        current = await self._current(upload)
        if current is None:
            return
        if (
            current.cancellation_requested_at is not None
            and outcome is not RuntimeTransferOutcome.SUCCEEDED
        ):
            await self._settle(
                current,
                attempt,
                outcome=WorkspaceUploadDeliveryOutcome.CANCELLED,
                failure=WorkspaceUploadFailure.CANCELLED,
            )
            return
        if outcome is RuntimeTransferOutcome.SUCCEEDED:
            await self._settle(
                current,
                attempt,
                outcome=WorkspaceUploadDeliveryOutcome.SUCCEEDED,
                failure=None,
            )
            return
        if outcome is RuntimeTransferOutcome.CANCELLED:
            await self._settle(
                current,
                attempt,
                outcome=WorkspaceUploadDeliveryOutcome.CANCELLED,
                failure=WorkspaceUploadFailure.CANCELLED,
            )
            return
        if outcome is RuntimeTransferOutcome.EXPIRED:
            await self._settle(
                current,
                attempt,
                outcome=WorkspaceUploadDeliveryOutcome.EXPIRED,
                failure=WorkspaceUploadFailure.EXPIRED,
            )
            return
        if failure is RuntimeTransferFailure.DESTINATION_CONFLICT:
            conflict = runtime_record.destination_conflict
            if conflict is None:
                await self._settle(
                    current,
                    attempt,
                    outcome=WorkspaceUploadDeliveryOutcome.FAILED,
                    failure=WorkspaceUploadFailure.RUNTIME,
                )
                return
            token = _encode_token(conflict.conflict_precondition)
            await self._settle(
                current,
                attempt,
                outcome=WorkspaceUploadDeliveryOutcome.CONFLICTED,
                failure=WorkspaceUploadFailure.DESTINATION_CONFLICT,
                conflict_revision=token,
                destination_evidence=WorkspaceUploadDestinationEvidence(
                    kind=conflict.kind,
                    size=conflict.size,
                    modified_at=conflict.modified_at,
                ),
            )
            return
        if failure in {
            RuntimeTransferFailure.ADMISSION,
            RuntimeTransferFailure.FENCED,
            RuntimeTransferFailure.STREAM,
            RuntimeTransferFailure.CONSUMER,
        }:
            mapped = (
                WorkspaceUploadFailure.FENCED
                if failure is RuntimeTransferFailure.FENCED
                else WorkspaceUploadFailure.RUNTIME
            )
            await self._settle(
                current,
                attempt,
                outcome=WorkspaceUploadDeliveryOutcome.RETRYABLE_FAILURE,
                failure=mapped,
            )
            return
        await self._settle(
            current,
            attempt,
            outcome=WorkspaceUploadDeliveryOutcome.FAILED,
            failure=(
                WorkspaceUploadFailure.INTEGRITY
                if failure is RuntimeTransferFailure.INTEGRITY
                else WorkspaceUploadFailure.RUNTIME
            ),
        )

    async def _settle(
        self,
        upload: WorkspaceUploadRecord,
        attempt: WorkspaceUploadDeliveryAttempt,
        *,
        outcome: WorkspaceUploadDeliveryOutcome,
        failure: WorkspaceUploadFailure | None,
        conflict_revision: str | None = None,
        destination_evidence: WorkspaceUploadDestinationEvidence | None = None,
    ) -> WorkspaceUploadRecord | None:
        """CAS-settle one exact current Workspace delivery attempt."""
        return await self.store.settle_delivery_attempt(
            upload.admission.upload_id,
            requester_user_id=upload.admission.requester_user_id,
            workspace_id=upload.admission.workspace_id,
            agent_id=upload.admission.agent_id,
            expected_revision=upload.revision,
            delivery_number=attempt.number,
            outcome=outcome,
            failure=failure,
            conflict_precondition=None,
            conflict_revision=conflict_revision,
            destination_evidence=destination_evidence,
        )

    async def _current(
        self,
        record: WorkspaceUploadRecord,
    ) -> WorkspaceUploadRecord | None:
        """Reload one record under the exact public authority boundary."""
        return await self.store.get(
            record.admission.upload_id,
            requester_user_id=record.admission.requester_user_id,
            workspace_id=record.admission.workspace_id,
            agent_id=record.admission.agent_id,
        )


def _encode_token(value: bytes) -> str:
    """Encode opaque conflict evidence for bounded Workspace metadata."""
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _decode_token(value: str) -> bytes:
    """Decode one Workspace-stored opaque conflict precondition."""
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
