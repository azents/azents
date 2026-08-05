"""Trusted Runtime transfer coordinator gRPC servicer."""

# Protobuf generated modules expose dynamic message/RPC attributes.
# ruff: noqa: E501

from datetime import UTC, datetime
from typing import NoReturn

import grpc
from azents_runtime_control.grpc_transfer_coordinator_client import (
    CoordinatorCancellationReason,
    CoordinatorCleanupStatus,
    CoordinatorRequestMessage,
    CoordinatorTransferDirection,
    CoordinatorTransferFailure,
    CoordinatorTransferOutcome,
    coordinator_identity_from_message,
)
from azents_runtime_control.proto import (
    runtime_transfer_coordinator_pb2 as pb,
)
from azents_runtime_control.proto import (
    runtime_transfer_coordinator_pb2_grpc as pb_grpc,
)
from azents_runtime_control.transfer import CoordinatorTransferIdentity
from google.protobuf import timestamp_pb2

from azents.runtime.control_protocol.grpc.auth import (
    GrpcAbortContext,
    RuntimeTransferCoordinatorCredentialGrpcAuth,
)
from azents.runtime.transfer.coordinator import (
    RuntimeTransferCoordinator,
    RuntimeTransferDispatchError,
    object_handle_for,
)
from azents.runtime.transfer.data import (
    RuntimeTransferAdmission,
    RuntimeTransferCancellationReason,
    RuntimeTransferCleanupStatus,
    RuntimeTransferDirection,
    RuntimeTransferDispatchStatus,
    RuntimeTransferFailure,
    RuntimeTransferOutcome,
    RuntimeTransferPhase,
    RuntimeTransferPreparationCleanupState,
    RuntimeTransferRecord,
)


class RuntimeTransferCoordinatorGrpcServicer(
    pb_grpc.RuntimeTransferCoordinatorServicer
):
    """Metadata-only trusted transfer state transition RPC surface."""

    def __init__(
        self,
        *,
        coordinator: RuntimeTransferCoordinator,
        credential_auth: RuntimeTransferCoordinatorCredentialGrpcAuth,
    ) -> None:
        """Initialize authenticated coordinator dependencies.

        :param coordinator: trusted state and dispatch coordinator
        :param credential_auth: exact metadata credential verifier
        """
        self._coordinator = coordinator
        self._credential_auth = credential_auth

    async def AdmitTransfer(
        self,
        request: pb.AdmitTransferRequest,
        context: grpc.aio.ServicerContext[
            pb.AdmitTransferRequest,
            pb.AdmitTransferResponse,
        ],
    ) -> pb.AdmitTransferResponse:
        """Admit one metadata-only transfer attempt."""
        await self._authenticate(
            context, "RuntimeTransferCoordinator/AdmitTransfer", request
        )
        try:
            admission = _admission_from_request(request)
            _bounded(request.lease_id, "lease_id", 128)
        except (KeyError, ValueError) as exc:
            await _abort(context, grpc.StatusCode.INVALID_ARGUMENT, str(exc))
        record = await self._coordinator.admit(admission, lease_id=request.lease_id)
        if record is None:
            await _abort(
                context,
                grpc.StatusCode.RESOURCE_EXHAUSTED,
                "Transfer admission is unavailable",
            )
        return pb.AdmitTransferResponse(
            status=_status_message(record),
            admitted_object_handle=pb.OpaqueObjectHandle(
                value=object_handle_for(record)
            ),
        )

    async def MarkTransferReady(
        self,
        request: pb.MarkTransferReadyRequest,
        context: grpc.aio.ServicerContext[
            pb.MarkTransferReadyRequest,
            pb.TransferStatusResponse,
        ],
    ) -> pb.TransferStatusResponse:
        """Mark one admitted transfer ready."""
        await self._authenticate(
            context,
            "RuntimeTransferCoordinator/MarkTransferReady",
            request,
        )
        record = await self._record(context, request.identity)
        try:
            _positive_revision(request.expected_revision)
            _bounded(request.object_handle.value, "object_handle", 512)
            manifest = request.object_manifest
            if not manifest.HasField("size"):
                raise ValueError("Object manifest size is required")
            if (
                record.admission.direction is RuntimeTransferDirection.DOWNLOAD
                and not manifest.HasField("sha256")
            ):
                raise ValueError("Download object manifest SHA-256 is required")
            updated = await self._coordinator.mark_ready(
                record,
                expected_revision=request.expected_revision,
                object_handle=request.object_handle.value,
                size=manifest.size,
                sha256=(manifest.sha256 if manifest.HasField("sha256") else None),
            )
        except ValueError as exc:
            await _abort(context, grpc.StatusCode.INVALID_ARGUMENT, str(exc))
        return await _status_response_or_abort(context, updated)

    async def DispatchTransfer(
        self,
        request: pb.DispatchTransferRequest,
        context: grpc.aio.ServicerContext[
            pb.DispatchTransferRequest,
            pb.TransferStatusResponse,
        ],
    ) -> pb.TransferStatusResponse:
        """Bind and deliver one stable Runner transfer intent."""
        await self._authenticate(
            context,
            "RuntimeTransferCoordinator/DispatchTransfer",
            request,
        )
        record = await self._record(context, request.identity)
        try:
            _positive_revision(request.expected_revision)
            _bounded(request.dispatch_id, "dispatch_id", 128)
            dispatch = await self._coordinator.dispatch(
                record,
                expected_revision=request.expected_revision,
                dispatch_id=request.dispatch_id,
            )
        except RuntimeTransferDispatchError as exc:
            await _abort(context, grpc.StatusCode.FAILED_PRECONDITION, str(exc))
        return pb.TransferStatusResponse(status=_status_message(dispatch.record))

    async def CancelTransfer(
        self,
        request: pb.CancelTransferRequest,
        context: grpc.aio.ServicerContext[
            pb.CancelTransferRequest,
            pb.TransferStatusResponse,
        ],
    ) -> pb.TransferStatusResponse:
        """Request cancellation for one transfer attempt."""
        await self._authenticate(
            context,
            "RuntimeTransferCoordinator/CancelTransfer",
            request,
        )
        record = await self._record(context, request.identity)
        try:
            _positive_revision(request.expected_revision)
            reason = RuntimeTransferCancellationReason(
                _cancellation_reason(request.reason).value
            )
        except (KeyError, ValueError) as exc:
            await _abort(context, grpc.StatusCode.INVALID_ARGUMENT, str(exc))
        updated = await self._coordinator.cancel(
            record,
            expected_revision=request.expected_revision,
            reason=reason,
        )
        return await _status_response_or_abort(context, updated)

    async def GetVerifiedObject(
        self,
        request: pb.GetVerifiedObjectRequest,
        context: grpc.aio.ServicerContext[
            pb.GetVerifiedObjectRequest,
            pb.GetVerifiedObjectResponse,
        ],
    ) -> pb.GetVerifiedObjectResponse:
        """Return one claimed verified opaque object handle."""
        await self._authenticate(
            context,
            "RuntimeTransferCoordinator/GetVerifiedObject",
            request,
        )
        record = await self._record(context, request.identity)
        try:
            _positive_revision(request.expected_revision)
            _bounded(request.consumer_claim_id, "consumer_claim_id", 128)
        except ValueError as exc:
            await _abort(context, grpc.StatusCode.INVALID_ARGUMENT, str(exc))
        verified = await self._coordinator.state_store.get_verified_object(
            record.admission.transfer_id,
            attempt_id=record.admission.attempt_id,
            expected_revision=request.expected_revision,
            claim_id=request.consumer_claim_id,
        )
        if verified is None or verified.object is None:
            await _abort(
                context,
                grpc.StatusCode.FAILED_PRECONDITION,
                "Verified object is unavailable",
            )
        return pb.GetVerifiedObjectResponse(
            status=_status_message(verified),
            verified_object_handle=pb.OpaqueObjectHandle(value=verified.object.key),
            actual_manifest=pb.ObjectManifest(
                size=verified.actual_size
                if verified.actual_size is not None
                else verified.object.size,
                sha256=verified.actual_sha256 or verified.object.sha256,
            ),
        )

    async def ClaimConsumer(
        self,
        request: pb.ClaimConsumerRequest,
        context: grpc.aio.ServicerContext[
            pb.ClaimConsumerRequest,
            pb.TransferStatusResponse,
        ],
    ) -> pb.TransferStatusResponse:
        """Claim one available transfer consumer."""
        await self._authenticate(
            context, "RuntimeTransferCoordinator/ClaimConsumer", request
        )
        record = await self._record(context, request.identity)
        await _validate_consumer_request(context, request)
        updated = await self._coordinator.state_store.claim_consumer(
            record.admission.transfer_id,
            attempt_id=record.admission.attempt_id,
            expected_revision=request.expected_revision,
            claim_id=request.consumer_claim_id,
        )
        return await _status_response_or_abort(context, updated)

    async def RenewConsumerLease(
        self,
        request: pb.RenewConsumerLeaseRequest,
        context: grpc.aio.ServicerContext[
            pb.RenewConsumerLeaseRequest,
            pb.TransferStatusResponse,
        ],
    ) -> pb.TransferStatusResponse:
        """Renew one live revision-fenced consumer claim."""
        await self._authenticate(
            context, "RuntimeTransferCoordinator/RenewConsumerLease", request
        )
        record = await self._record(context, request.identity)
        await _validate_consumer_request(context, request)
        updated = await self._coordinator.state_store.renew_consumer_lease(
            record.admission.transfer_id,
            attempt_id=record.admission.attempt_id,
            expected_revision=request.expected_revision,
            claim_id=request.consumer_claim_id,
        )
        return await _status_response_or_abort(context, updated)

    async def AcknowledgeConsumer(
        self,
        request: pb.AcknowledgeConsumerRequest,
        context: grpc.aio.ServicerContext[
            pb.AcknowledgeConsumerRequest,
            pb.TransferStatusResponse,
        ],
    ) -> pb.TransferStatusResponse:
        """Acknowledge one claimed transfer consumer."""
        await self._authenticate(
            context,
            "RuntimeTransferCoordinator/AcknowledgeConsumer",
            request,
        )
        record = await self._record(context, request.identity)
        await _validate_consumer_request(context, request)
        updated = await self._coordinator.state_store.acknowledge_consumer(
            record.admission.transfer_id,
            attempt_id=record.admission.attempt_id,
            expected_revision=request.expected_revision,
            claim_id=request.consumer_claim_id,
        )
        return await _status_response_or_abort(context, updated)

    async def AbandonConsumer(
        self,
        request: pb.AbandonConsumerRequest,
        context: grpc.aio.ServicerContext[
            pb.AbandonConsumerRequest,
            pb.TransferStatusResponse,
        ],
    ) -> pb.TransferStatusResponse:
        """Abandon one claimed transfer consumer."""
        await self._authenticate(
            context,
            "RuntimeTransferCoordinator/AbandonConsumer",
            request,
        )
        record = await self._record(context, request.identity)
        await _validate_consumer_request(context, request)
        updated = await self._coordinator.state_store.abandon_consumer(
            record.admission.transfer_id,
            attempt_id=record.admission.attempt_id,
            expected_revision=request.expected_revision,
            claim_id=request.consumer_claim_id,
        )
        return await _status_response_or_abort(context, updated)

    async def SettleTransfer(
        self,
        request: pb.SettleTransferRequest,
        context: grpc.aio.ServicerContext[
            pb.SettleTransferRequest,
            pb.TransferStatusResponse,
        ],
    ) -> pb.TransferStatusResponse:
        """Settle one transfer attempt with an exact outcome/failure pair."""
        await self._authenticate(
            context, "RuntimeTransferCoordinator/SettleTransfer", request
        )
        record = await self._record(context, request.identity)
        try:
            _positive_revision(request.expected_revision)
            outcome = _outcome(request.outcome)
            failure = _settlement_failure(request, outcome)
        except (KeyError, ValueError) as exc:
            await _abort(context, grpc.StatusCode.INVALID_ARGUMENT, str(exc))
        if record.revision != request.expected_revision:
            updated = None
        else:
            updated = await self._coordinator.settle_terminal(
                record,
                outcome=outcome,
                failure=failure,
                cleanup_completed=False,
            )
        return await _status_response_or_abort(context, updated)

    async def RecordCleanup(
        self,
        request: pb.RecordCleanupRequest,
        context: grpc.aio.ServicerContext[
            pb.RecordCleanupRequest,
            pb.TransferStatusResponse,
        ],
    ) -> pb.TransferStatusResponse:
        """Record bounded physical cleanup evidence."""
        await self._authenticate(
            context, "RuntimeTransferCoordinator/RecordCleanup", request
        )
        record = await self._record(context, request.identity)
        try:
            _positive_revision(request.expected_revision)
            status = RuntimeTransferCleanupStatus(
                CoordinatorCleanupStatus(_cleanup_status(request.cleanup_status)).value
            )
        except (KeyError, ValueError) as exc:
            await _abort(context, grpc.StatusCode.INVALID_ARGUMENT, str(exc))
        updated = await self._coordinator.state_store.record_cleanup(
            record.admission.transfer_id,
            attempt_id=record.admission.attempt_id,
            expected_revision=request.expected_revision,
            status=status,
        )
        return await _status_response_or_abort(context, updated)

    async def RegisterPreparationCleanup(
        self,
        request: pb.RegisterPreparationCleanupRequest,
        context: grpc.aio.ServicerContext[
            pb.RegisterPreparationCleanupRequest,
            pb.TransferStatusResponse,
        ],
    ) -> pb.TransferStatusResponse:
        """Register opaque source-preparation multipart cleanup responsibility."""
        await self._authenticate(
            context,
            "RuntimeTransferCoordinator/RegisterPreparationCleanup",
            request,
        )
        record = await self._record(context, request.identity)
        try:
            _positive_revision(request.expected_revision)
            _bounded(
                request.preparation_object_handle.value,
                "preparation_object_handle",
                512,
            )
            _bounded(
                request.multipart_cleanup_handle.value,
                "multipart_cleanup_handle",
                512,
            )
        except ValueError as exc:
            await _abort(context, grpc.StatusCode.INVALID_ARGUMENT, str(exc))
        updated = await self._coordinator.state_store.register_preparation_cleanup(
            record.admission.transfer_id,
            attempt_id=record.admission.attempt_id,
            runtime_id=record.admission.runtime_id,
            desired_generation=record.admission.desired_generation,
            expected_revision=request.expected_revision,
            preparation_object_handle=request.preparation_object_handle.value,
            multipart_cleanup_handle=request.multipart_cleanup_handle.value,
        )
        return await _status_response_or_abort(context, updated)

    async def PromotePreparationCleanup(
        self,
        request: pb.PromotePreparationCleanupRequest,
        context: grpc.aio.ServicerContext[
            pb.PromotePreparationCleanupRequest,
            pb.TransferStatusResponse,
        ],
    ) -> pb.TransferStatusResponse:
        """Promote cleanup responsibility after preparation object completion."""
        await self._authenticate(
            context,
            "RuntimeTransferCoordinator/PromotePreparationCleanup",
            request,
        )
        record = await self._record(context, request.identity)
        try:
            _positive_revision(request.expected_revision)
            _bounded(
                request.preparation_object_handle.value,
                "preparation_object_handle",
                512,
            )
        except ValueError as exc:
            await _abort(context, grpc.StatusCode.INVALID_ARGUMENT, str(exc))
        updated = await self._coordinator.state_store.promote_preparation_cleanup(
            record.admission.transfer_id,
            attempt_id=record.admission.attempt_id,
            runtime_id=record.admission.runtime_id,
            desired_generation=record.admission.desired_generation,
            expected_revision=request.expected_revision,
            preparation_object_handle=request.preparation_object_handle.value,
        )
        return await _status_response_or_abort(context, updated)

    async def ClearPreparationCleanup(
        self,
        request: pb.ClearPreparationCleanupRequest,
        context: grpc.aio.ServicerContext[
            pb.ClearPreparationCleanupRequest,
            pb.TransferStatusResponse,
        ],
    ) -> pb.TransferStatusResponse:
        """Clear exact cleanup evidence after trusted source cleanup succeeds."""
        await self._authenticate(
            context,
            "RuntimeTransferCoordinator/ClearPreparationCleanup",
            request,
        )
        record = await self._record(context, request.identity)
        try:
            _positive_revision(request.expected_revision)
        except ValueError as exc:
            await _abort(context, grpc.StatusCode.INVALID_ARGUMENT, str(exc))
        updated = await self._coordinator.state_store.clear_preparation_cleanup(
            record.admission.transfer_id,
            attempt_id=record.admission.attempt_id,
            expected_revision=request.expected_revision,
        )
        return await _status_response_or_abort(context, updated)

    async def GetTransferStatus(
        self,
        request: pb.GetTransferStatusRequest,
        context: grpc.aio.ServicerContext[
            pb.GetTransferStatusRequest,
            pb.TransferStatusResponse,
        ],
    ) -> pb.TransferStatusResponse:
        """Return one metadata-only transfer status projection."""
        await self._authenticate(
            context,
            "RuntimeTransferCoordinator/GetTransferStatus",
            request,
        )
        record = await self._record(context, request.identity)
        return pb.TransferStatusResponse(status=_status_message(record))

    async def _authenticate(
        self,
        context: GrpcAbortContext,
        operation: str,
        request: CoordinatorRequestMessage,
    ) -> None:
        await self._credential_auth.authenticate(
            context,
            operation=operation,
            request=request,
        )

    async def _record(
        self,
        context: GrpcAbortContext,
        identity: pb.CoordinatorTransferIdentity,
    ) -> RuntimeTransferRecord:
        try:
            requested = coordinator_identity_from_message(identity)
            _validate_identity(requested)
        except (KeyError, ValueError) as exc:
            await _abort(context, grpc.StatusCode.INVALID_ARGUMENT, str(exc))
        record = await self._coordinator.state_store.get(requested.transfer_id)
        if record is None:
            await _abort(
                context, grpc.StatusCode.NOT_FOUND, "Transfer attempt is unavailable"
            )
        if (
            record.admission.attempt_id != requested.attempt_id
            or record.admission.runtime_id != requested.runtime_id
            or record.admission.desired_generation != requested.desired_generation
            or record.admission.direction.value != requested.direction
            or record.admission.operation_id != requested.operation_id
            or record.admission.session_id != requested.session_id
            or record.admission.agent_id != requested.agent_id
        ):
            await _abort(
                context,
                grpc.StatusCode.PERMISSION_DENIED,
                "Transfer identity is not authorized",
            )
        return record


def add_runtime_transfer_coordinator_servicer(
    server: grpc.aio.Server,
    *,
    coordinator: RuntimeTransferCoordinator,
    credential_auth: RuntimeTransferCoordinatorCredentialGrpcAuth,
) -> None:
    """Add the trusted transfer coordinator servicer to a gRPC server.

    :param server: gRPC server to extend
    :param coordinator: trusted Transfer State coordinator
    :param credential_auth: exact metadata credential verifier
    """
    pb_grpc.add_RuntimeTransferCoordinatorServicer_to_server(
        RuntimeTransferCoordinatorGrpcServicer(
            coordinator=coordinator,
            credential_auth=credential_auth,
        ),
        server,
    )


def _admission_from_request(
    request: pb.AdmitTransferRequest,
) -> RuntimeTransferAdmission:
    identity = coordinator_identity_from_message(request.identity)
    _validate_identity(identity)
    if (
        not request.HasField("overwrite")
        or not request.expected_manifest.HasField("size")
        or not request.HasField("product_maximum_size")
        or not request.HasField("provider_maximum_size")
    ):
        raise ValueError("Required admission field presence is missing")
    return RuntimeTransferAdmission(
        transfer_id=identity.transfer_id,
        attempt_id=identity.attempt_id,
        direction=RuntimeTransferDirection(
            CoordinatorTransferDirection(identity.direction).value
        ),
        runtime_id=identity.runtime_id,
        desired_generation=identity.desired_generation,
        operation_id=identity.operation_id,
        session_id=identity.session_id,
        agent_id=identity.agent_id,
        runtime_path=request.runtime_path,
        overwrite=request.overwrite,
        expected_size=request.expected_manifest.size,
        expected_sha256=(
            request.expected_manifest.sha256
            if request.expected_manifest.HasField("sha256")
            else None
        ),
        product_maximum_size=request.product_maximum_size,
        provider_maximum_size=request.provider_maximum_size,
        deadline_at=_datetime(request.deadline_at),
        source_expires_at=(
            _datetime(request.source_expires_at)
            if request.HasField("source_expires_at")
            else None
        ),
        resource_class=request.resource_class,
    )


async def _status_response_or_abort(
    context: GrpcAbortContext,
    record: RuntimeTransferRecord | None,
) -> pb.TransferStatusResponse:
    if record is None:
        await _abort(
            context,
            grpc.StatusCode.FAILED_PRECONDITION,
            "Transfer transition is unavailable",
        )
    return pb.TransferStatusResponse(status=_status_message(record))


def _status_message(
    record: RuntimeTransferRecord,
) -> pb.CoordinatorTransferStatus:
    admission = record.admission
    message = pb.CoordinatorTransferStatus(
        identity=pb.CoordinatorTransferIdentity(
            transfer_id=admission.transfer_id,
            attempt_id=admission.attempt_id,
            runtime_id=admission.runtime_id,
            desired_generation=admission.desired_generation,
            direction=_direction(admission.direction),
            operation_id=admission.operation_id,
        ),
        phase=_phase(record.phase),
        revision=record.revision,
        dispatch_status=_dispatch_status(record.dispatch_status),
        expected_manifest=pb.ExpectedManifest(size=admission.expected_size),
        deadline_at=_timestamp(admission.deadline_at),
        logical_expires_at=_timestamp(record.logical_expires_at),
        cleanup_status=_cleanup_status_to_proto(record.cleanup_status),
        cancellation_requested=record.cancellation_requested_at is not None,
        preparation_cleanup_state=_preparation_cleanup_state_to_proto(
            record.preparation_cleanup_state
        ),
    )
    if admission.session_id is not None:
        message.identity.session_id = admission.session_id
    if admission.agent_id is not None:
        message.identity.agent_id = admission.agent_id
    if admission.expected_sha256 is not None:
        message.expected_manifest.sha256 = admission.expected_sha256
    if record.accepted_runner_generation is not None:
        message.accepted_runner_generation = record.accepted_runner_generation
    if record.dispatch_id is not None:
        message.dispatch_id = record.dispatch_id
    if record.object is not None and record.object.sha256 is not None:
        message.actual_manifest.size = record.actual_size or record.object.size
        message.actual_manifest.sha256 = record.actual_sha256 or record.object.sha256
    if record.terminal_outcome is not None:
        message.outcome = _outcome_to_proto(record.terminal_outcome)
    if record.failure is not None:
        message.failure = _failure_to_proto(record.failure)
    return message


async def _abort(
    context: GrpcAbortContext,
    code: grpc.StatusCode,
    details: str,
) -> NoReturn:
    await context.abort(code, details)
    raise AssertionError("unreachable")


def _datetime(value: timestamp_pb2.Timestamp) -> datetime:
    return value.ToDatetime(tzinfo=UTC)


def _timestamp(value: datetime) -> timestamp_pb2.Timestamp:
    message = timestamp_pb2.Timestamp()
    message.FromDatetime(value)
    return message


def _direction(
    value: RuntimeTransferDirection,
) -> pb.CoordinatorTransferDirection.ValueType:
    return {
        RuntimeTransferDirection.DOWNLOAD: pb.COORDINATOR_TRANSFER_DIRECTION_DOWNLOAD,
        RuntimeTransferDirection.UPLOAD: pb.COORDINATOR_TRANSFER_DIRECTION_UPLOAD,
    }[value]


def _phase(value: RuntimeTransferPhase) -> pb.CoordinatorTransferPhase.ValueType:
    return {
        RuntimeTransferPhase.PREPARING: pb.COORDINATOR_TRANSFER_PHASE_PREPARING,
        RuntimeTransferPhase.READY: pb.COORDINATOR_TRANSFER_PHASE_READY,
        RuntimeTransferPhase.STREAMING: pb.COORDINATOR_TRANSFER_PHASE_STREAMING,
        RuntimeTransferPhase.VERIFYING: pb.COORDINATOR_TRANSFER_PHASE_VERIFYING,
        RuntimeTransferPhase.AVAILABLE: pb.COORDINATOR_TRANSFER_PHASE_AVAILABLE,
        RuntimeTransferPhase.CONSUMING: pb.COORDINATOR_TRANSFER_PHASE_CONSUMING,
        RuntimeTransferPhase.CONSUMED: pb.COORDINATOR_TRANSFER_PHASE_CONSUMED,
        RuntimeTransferPhase.COMMITTED: pb.COORDINATOR_TRANSFER_PHASE_COMMITTED,
        RuntimeTransferPhase.TERMINAL: pb.COORDINATOR_TRANSFER_PHASE_TERMINAL,
    }[value]


def _dispatch_status(
    value: RuntimeTransferDispatchStatus,
) -> pb.CoordinatorDispatchStatus.ValueType:
    return {
        RuntimeTransferDispatchStatus.NOT_BOUND: pb.COORDINATOR_DISPATCH_STATUS_NOT_BOUND,
        RuntimeTransferDispatchStatus.BOUND: pb.COORDINATOR_DISPATCH_STATUS_BOUND,
        RuntimeTransferDispatchStatus.DELIVERABLE: pb.COORDINATOR_DISPATCH_STATUS_DELIVERABLE,
        RuntimeTransferDispatchStatus.ENQUEUED: pb.COORDINATOR_DISPATCH_STATUS_ENQUEUED,
    }[value]


def _outcome(
    value: pb.CoordinatorTransferOutcome.ValueType,
) -> RuntimeTransferOutcome:
    return RuntimeTransferOutcome(
        {
            pb.COORDINATOR_TRANSFER_OUTCOME_SUCCEEDED: CoordinatorTransferOutcome.SUCCEEDED,
            pb.COORDINATOR_TRANSFER_OUTCOME_FAILED: CoordinatorTransferOutcome.FAILED,
            pb.COORDINATOR_TRANSFER_OUTCOME_CANCELLED: CoordinatorTransferOutcome.CANCELLED,
            pb.COORDINATOR_TRANSFER_OUTCOME_EXPIRED: CoordinatorTransferOutcome.EXPIRED,
            pb.COORDINATOR_TRANSFER_OUTCOME_SUPERSEDED: CoordinatorTransferOutcome.SUPERSEDED,
        }[value].value
    )


def _outcome_to_proto(
    value: RuntimeTransferOutcome,
) -> pb.CoordinatorTransferOutcome.ValueType:
    return {
        RuntimeTransferOutcome.SUCCEEDED: pb.COORDINATOR_TRANSFER_OUTCOME_SUCCEEDED,
        RuntimeTransferOutcome.FAILED: pb.COORDINATOR_TRANSFER_OUTCOME_FAILED,
        RuntimeTransferOutcome.CANCELLED: pb.COORDINATOR_TRANSFER_OUTCOME_CANCELLED,
        RuntimeTransferOutcome.EXPIRED: pb.COORDINATOR_TRANSFER_OUTCOME_EXPIRED,
        RuntimeTransferOutcome.SUPERSEDED: pb.COORDINATOR_TRANSFER_OUTCOME_SUPERSEDED,
    }[value]


def _settlement_failure(
    request: pb.SettleTransferRequest,
    outcome: RuntimeTransferOutcome,
) -> RuntimeTransferFailure | None:
    selected = request.WhichOneof("failure_choice")
    if outcome is RuntimeTransferOutcome.SUCCEEDED:
        if selected != "no_failure" or not request.no_failure:
            raise ValueError("Successful settlement requires explicit no_failure")
        return None
    if selected != "failure":
        raise ValueError("Terminal failure classification is required")
    failure = _failure(request.failure)
    expected = {
        RuntimeTransferOutcome.FAILED: {
            RuntimeTransferFailure.ADMISSION,
            RuntimeTransferFailure.FENCED,
            RuntimeTransferFailure.INTEGRITY,
            RuntimeTransferFailure.STREAM,
            RuntimeTransferFailure.CONSUMER,
        },
        RuntimeTransferOutcome.CANCELLED: {RuntimeTransferFailure.CANCELLED},
        RuntimeTransferOutcome.EXPIRED: {RuntimeTransferFailure.EXPIRED},
        RuntimeTransferOutcome.SUPERSEDED: {RuntimeTransferFailure.FENCED},
    }[outcome]
    if failure not in expected:
        raise ValueError("Settlement outcome and failure do not match")
    return failure


def _failure(
    value: pb.CoordinatorTransferFailure.ValueType,
) -> RuntimeTransferFailure:
    return RuntimeTransferFailure(
        {
            pb.COORDINATOR_TRANSFER_FAILURE_ADMISSION: CoordinatorTransferFailure.ADMISSION,
            pb.COORDINATOR_TRANSFER_FAILURE_CANCELLED: CoordinatorTransferFailure.CANCELLED,
            pb.COORDINATOR_TRANSFER_FAILURE_EXPIRED: CoordinatorTransferFailure.EXPIRED,
            pb.COORDINATOR_TRANSFER_FAILURE_FENCED: CoordinatorTransferFailure.FENCED,
            pb.COORDINATOR_TRANSFER_FAILURE_INTEGRITY: CoordinatorTransferFailure.INTEGRITY,
            pb.COORDINATOR_TRANSFER_FAILURE_STREAM: CoordinatorTransferFailure.STREAM,
            pb.COORDINATOR_TRANSFER_FAILURE_CONSUMER: CoordinatorTransferFailure.CONSUMER,
        }[value].value
    )


def _failure_to_proto(
    value: RuntimeTransferFailure,
) -> pb.CoordinatorTransferFailure.ValueType:
    return {
        RuntimeTransferFailure.ADMISSION: pb.COORDINATOR_TRANSFER_FAILURE_ADMISSION,
        RuntimeTransferFailure.CANCELLED: pb.COORDINATOR_TRANSFER_FAILURE_CANCELLED,
        RuntimeTransferFailure.EXPIRED: pb.COORDINATOR_TRANSFER_FAILURE_EXPIRED,
        RuntimeTransferFailure.FENCED: pb.COORDINATOR_TRANSFER_FAILURE_FENCED,
        RuntimeTransferFailure.INTEGRITY: pb.COORDINATOR_TRANSFER_FAILURE_INTEGRITY,
        RuntimeTransferFailure.STREAM: pb.COORDINATOR_TRANSFER_FAILURE_STREAM,
        RuntimeTransferFailure.CONSUMER: pb.COORDINATOR_TRANSFER_FAILURE_CONSUMER,
    }[value]


def _cleanup_status(
    value: pb.CoordinatorCleanupStatus.ValueType,
) -> CoordinatorCleanupStatus:
    return {
        pb.COORDINATOR_CLEANUP_STATUS_NOT_REQUIRED: CoordinatorCleanupStatus.NOT_REQUIRED,
        pb.COORDINATOR_CLEANUP_STATUS_PENDING: CoordinatorCleanupStatus.PENDING,
        pb.COORDINATOR_CLEANUP_STATUS_COMPLETE: CoordinatorCleanupStatus.COMPLETE,
        pb.COORDINATOR_CLEANUP_STATUS_RETRYABLE_FAILURE: CoordinatorCleanupStatus.RETRYABLE_FAILURE,
    }[value]


def _cleanup_status_to_proto(
    value: RuntimeTransferCleanupStatus,
) -> pb.CoordinatorCleanupStatus.ValueType:
    return {
        RuntimeTransferCleanupStatus.NOT_REQUIRED: pb.COORDINATOR_CLEANUP_STATUS_NOT_REQUIRED,
        RuntimeTransferCleanupStatus.PENDING: pb.COORDINATOR_CLEANUP_STATUS_PENDING,
        RuntimeTransferCleanupStatus.COMPLETE: pb.COORDINATOR_CLEANUP_STATUS_COMPLETE,
        RuntimeTransferCleanupStatus.RETRYABLE_FAILURE: pb.COORDINATOR_CLEANUP_STATUS_RETRYABLE_FAILURE,
    }[value]


def _preparation_cleanup_state_to_proto(
    value: RuntimeTransferPreparationCleanupState,
) -> pb.CoordinatorPreparationCleanupState.ValueType:
    return {
        RuntimeTransferPreparationCleanupState.NOT_REQUIRED: (
            pb.COORDINATOR_PREPARATION_CLEANUP_STATE_NOT_REQUIRED
        ),
        RuntimeTransferPreparationCleanupState.MULTIPART_PENDING: (
            pb.COORDINATOR_PREPARATION_CLEANUP_STATE_MULTIPART_PENDING
        ),
        RuntimeTransferPreparationCleanupState.COMPLETED_OBJECT_PENDING: (
            pb.COORDINATOR_PREPARATION_CLEANUP_STATE_COMPLETED_OBJECT_PENDING
        ),
    }[value]


def _cancellation_reason(
    value: pb.CoordinatorCancellationReason.ValueType,
) -> CoordinatorCancellationReason:
    return {
        pb.COORDINATOR_CANCELLATION_REASON_CALLER: CoordinatorCancellationReason.CALLER,
        pb.COORDINATOR_CANCELLATION_REASON_DEADLINE: CoordinatorCancellationReason.DEADLINE,
        pb.COORDINATOR_CANCELLATION_REASON_SUPERSEDED: CoordinatorCancellationReason.SUPERSEDED,
        pb.COORDINATOR_CANCELLATION_REASON_SHUTDOWN: CoordinatorCancellationReason.SHUTDOWN,
    }[value]


async def _validate_consumer_request(
    context: GrpcAbortContext,
    request: pb.ClaimConsumerRequest
    | pb.RenewConsumerLeaseRequest
    | pb.AcknowledgeConsumerRequest
    | pb.AbandonConsumerRequest,
) -> None:
    try:
        _positive_revision(request.expected_revision)
        _bounded(request.consumer_claim_id, "consumer_claim_id", 128)
    except ValueError as exc:
        await _abort(context, grpc.StatusCode.INVALID_ARGUMENT, str(exc))


def _validate_identity(identity: CoordinatorTransferIdentity) -> None:
    for value, name in (
        (identity.transfer_id, "transfer_id"),
        (identity.attempt_id, "attempt_id"),
        (identity.runtime_id, "runtime_id"),
        (identity.operation_id, "operation_id"),
    ):
        _bounded(value, name, 128)
    if identity.session_id is not None:
        _bounded(identity.session_id, "session_id", 128)
    if identity.agent_id is not None:
        _bounded(identity.agent_id, "agent_id", 128)
    if identity.desired_generation <= 0:
        raise ValueError("desired_generation must be positive")


def _positive_revision(value: int) -> None:
    if value <= 0:
        raise ValueError("expected_revision must be positive")


def _bounded(value: str, name: str, maximum_bytes: int) -> None:
    if not value:
        raise ValueError(f"{name} must not be empty")
    if len(value.encode("utf-8")) > maximum_bytes:
        raise ValueError(f"{name} exceeds {maximum_bytes} UTF-8 bytes")
