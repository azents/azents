"""Authenticated Runtime Control gRPC Workspace upload servicer."""

from __future__ import annotations

import base64
from datetime import UTC, datetime
from typing import NoReturn, Protocol

import grpc
from azents_runtime_control.grpc_workspace_upload_client import (
    WORKSPACE_UPLOAD_OPERATION_CANCEL,
    WORKSPACE_UPLOAD_OPERATION_CREATE,
    WORKSPACE_UPLOAD_OPERATION_FINALIZE,
    WORKSPACE_UPLOAD_OPERATION_GET,
    WORKSPACE_UPLOAD_OPERATION_ISSUE_TICKET,
    WORKSPACE_UPLOAD_OPERATION_RETRY,
    WorkspaceUploadCredentialRequestMessage,
    WorkspaceUploadIdentity,
    workspace_upload_identity_from_message,
)
from azents_runtime_control.proto import (
    runtime_transfer_coordinator_pb2 as pb,
)
from azents_runtime_control.proto import (
    runtime_transfer_coordinator_pb2_grpc as pb_grpc,
)
from google.protobuf import timestamp_pb2

from azents.runtime.control_protocol.grpc.auth import (
    GrpcAbortContext,
)
from azents.runtime.transfer.workspace_upload import (
    WorkspaceUploadAdmission,
    WorkspaceUploadFailure,
    WorkspaceUploadOutcome,
    WorkspaceUploadPhase,
    WorkspaceUploadRecord,
)
from azents.runtime.transfer.workspace_upload_object import (
    WorkspaceUploadUploadTicket,
)


class _WorkspaceUploadCoordinator(Protocol):
    """Metadata coordinator operations exposed to the gRPC adapter."""

    async def create(
        self,
        admission: WorkspaceUploadAdmission,
    ) -> WorkspaceUploadRecord | None: ...

    async def issue_upload_ticket(
        self,
        upload_id: str,
        *,
        requester_user_id: str,
        workspace_id: str,
        agent_id: str,
    ) -> WorkspaceUploadUploadTicket | None: ...

    async def get(
        self,
        upload_id: str,
        *,
        requester_user_id: str,
        workspace_id: str,
        agent_id: str,
    ) -> WorkspaceUploadRecord | None: ...

    async def finalize(
        self,
        upload_id: str,
        *,
        requester_user_id: str,
        workspace_id: str,
        agent_id: str,
        expected_revision: int,
    ) -> WorkspaceUploadRecord | None: ...

    async def cancel(
        self,
        upload_id: str,
        *,
        requester_user_id: str,
        workspace_id: str,
        agent_id: str,
        expected_revision: int,
        current_delivery_number: int | None,
    ) -> WorkspaceUploadRecord | None: ...

    async def retry(
        self,
        upload_id: str,
        *,
        requester_user_id: str,
        workspace_id: str,
        agent_id: str,
        expected_revision: int,
        current_delivery_number: int,
        overwrite: bool,
        conflict_precondition: str | None,
    ) -> WorkspaceUploadRecord | None: ...


class _WorkspaceUploadCredentialAuth(Protocol):
    """Authenticate metadata-only Workspace upload RPCs."""

    async def authenticate_workspace(
        self,
        context: GrpcAbortContext,
        *,
        operation: str,
        request: WorkspaceUploadCredentialRequestMessage,
    ) -> object: ...


class RuntimeWorkspaceUploadCoordinatorGrpcServicer(
    pb_grpc.RuntimeWorkspaceUploadCoordinatorServicer
):
    """Metadata-only Runtime Control RPCs for Workspace uploads."""

    def __init__(
        self,
        *,
        coordinator: _WorkspaceUploadCoordinator,
        credential_auth: _WorkspaceUploadCredentialAuth,
    ) -> None:
        self._coordinator = coordinator
        self._credential_auth = credential_auth

    async def CreateWorkspaceUpload(
        self,
        request: pb.CreateWorkspaceUploadRequest,
        context: grpc.aio.ServicerContext,
    ) -> pb.WorkspaceUploadStatusResponse:
        """Create one requester-bound upload metadata record."""
        await self._credential_auth.authenticate_workspace(
            context,
            operation=WORKSPACE_UPLOAD_OPERATION_CREATE,
            request=request,
        )
        try:
            admission = _admission_from_create_request(request)
        except (KeyError, ValueError) as exc:
            await _abort(context, grpc.StatusCode.INVALID_ARGUMENT, str(exc))
        record = await self._coordinator.create(admission)
        if record is None:
            await _abort(
                context,
                grpc.StatusCode.RESOURCE_EXHAUSTED,
                "Workspace upload admission is unavailable",
            )
        return pb.WorkspaceUploadStatusResponse(status=_status_message(record))

    async def IssueWorkspaceUploadTicket(
        self,
        request: pb.IssueWorkspaceUploadTicketRequest,
        context: grpc.aio.ServicerContext,
    ) -> pb.WorkspaceUploadTicketResponse:
        """Issue one short-lived direct browser PUT capability."""
        await self._credential_auth.authenticate_workspace(
            context,
            operation=WORKSPACE_UPLOAD_OPERATION_ISSUE_TICKET,
            request=request,
        )
        identity = await _identity_or_abort(request.identity, context)
        await _positive_or_abort(
            request.expected_revision, "expected_revision", context
        )
        record = await self._coordinator.get(
            identity.upload_id,
            requester_user_id=identity.requester_user_id,
            workspace_id=identity.workspace_id,
            agent_id=identity.agent_id,
        )
        if record is None:
            await _abort(
                context,
                grpc.StatusCode.NOT_FOUND,
                "Workspace upload is unavailable",
            )
        if record.revision != request.expected_revision:
            await _abort(
                context,
                grpc.StatusCode.FAILED_PRECONDITION,
                "Workspace upload ticket precondition is stale",
            )
        try:
            ticket = await self._coordinator.issue_upload_ticket(
                identity.upload_id,
                requester_user_id=identity.requester_user_id,
                workspace_id=identity.workspace_id,
                agent_id=identity.agent_id,
            )
        except ValueError as exc:
            await _abort(context, grpc.StatusCode.FAILED_PRECONDITION, str(exc))
        if ticket is None:
            await _abort(
                context,
                grpc.StatusCode.FAILED_PRECONDITION,
                "Workspace upload ticket is unavailable",
            )
        ticket_message = pb.WorkspaceUploadTicket(
            method=ticket.method,
            url=ticket.url,
            expires_at=_timestamp(ticket.expires_at),
        )
        ticket_message.headers.extend(
            pb.WorkspaceUploadHeader(name=name, value=value)
            for name, value in ticket.headers.items()
        )
        return pb.WorkspaceUploadTicketResponse(
            status=_status_message(record),
            ticket=ticket_message,
        )

    async def FinalizeWorkspaceUpload(
        self,
        request: pb.FinalizeWorkspaceUploadRequest,
        context: grpc.aio.ServicerContext,
    ) -> pb.WorkspaceUploadStatusResponse:
        """Verify the direct S3 ingress object and start delivery."""
        await self._credential_auth.authenticate_workspace(
            context,
            operation=WORKSPACE_UPLOAD_OPERATION_FINALIZE,
            request=request,
        )
        identity = await _identity_or_abort(request.identity, context)
        await _positive_or_abort(
            request.expected_revision, "expected_revision", context
        )
        record = await self._coordinator.finalize(
            identity.upload_id,
            requester_user_id=identity.requester_user_id,
            workspace_id=identity.workspace_id,
            agent_id=identity.agent_id,
            expected_revision=request.expected_revision,
        )
        if record is None:
            await _abort(
                context,
                grpc.StatusCode.FAILED_PRECONDITION,
                "Workspace upload finalization precondition is stale",
            )
        return pb.WorkspaceUploadStatusResponse(status=_status_message(record))

    async def GetWorkspaceUpload(
        self,
        request: pb.GetWorkspaceUploadRequest,
        context: grpc.aio.ServicerContext,
    ) -> pb.WorkspaceUploadStatusResponse:
        """Read one requester-bound upload status."""
        await self._credential_auth.authenticate_workspace(
            context,
            operation=WORKSPACE_UPLOAD_OPERATION_GET,
            request=request,
        )
        identity = await _identity_or_abort(request.identity, context)
        record = await self._coordinator.get(
            identity.upload_id,
            requester_user_id=identity.requester_user_id,
            workspace_id=identity.workspace_id,
            agent_id=identity.agent_id,
        )
        if record is None:
            await _abort(
                context,
                grpc.StatusCode.NOT_FOUND,
                "Workspace upload is unavailable",
            )
        return pb.WorkspaceUploadStatusResponse(status=_status_message(record))

    async def CancelWorkspaceUpload(
        self,
        request: pb.CancelWorkspaceUploadRequest,
        context: grpc.aio.ServicerContext,
    ) -> pb.WorkspaceUploadStatusResponse:
        """Request idempotent cancellation of one upload operation."""
        await self._credential_auth.authenticate_workspace(
            context,
            operation=WORKSPACE_UPLOAD_OPERATION_CANCEL,
            request=request,
        )
        identity = await _identity_or_abort(request.identity, context)
        await _positive_or_abort(
            request.expected_revision, "expected_revision", context
        )
        current_delivery_number = (
            request.current_delivery_number
            if request.current_delivery_number > 0
            else None
        )
        record = await self._coordinator.cancel(
            identity.upload_id,
            requester_user_id=identity.requester_user_id,
            workspace_id=identity.workspace_id,
            agent_id=identity.agent_id,
            expected_revision=request.expected_revision,
            current_delivery_number=current_delivery_number,
        )
        if record is None:
            await _abort(
                context,
                grpc.StatusCode.FAILED_PRECONDITION,
                "Workspace upload cancellation precondition is stale",
            )
        return pb.WorkspaceUploadStatusResponse(status=_status_message(record))

    async def RetryWorkspaceUpload(
        self,
        request: pb.RetryWorkspaceUploadRequest,
        context: grpc.aio.ServicerContext,
    ) -> pb.WorkspaceUploadStatusResponse:
        """Queue one exact source-owned immutable delivery retry."""
        await self._credential_auth.authenticate_workspace(
            context,
            operation=WORKSPACE_UPLOAD_OPERATION_RETRY,
            request=request,
        )
        identity = await _identity_or_abort(request.identity, context)
        await _positive_or_abort(
            request.expected_revision, "expected_revision", context
        )
        await _positive_or_abort(
            request.current_delivery_number,
            "current_delivery_number",
            context,
        )
        conflict_precondition = (
            _encode_token(request.conflict_precondition)
            if request.HasField("conflict_precondition")
            else None
        )
        record = await self._coordinator.retry(
            identity.upload_id,
            requester_user_id=identity.requester_user_id,
            workspace_id=identity.workspace_id,
            agent_id=identity.agent_id,
            expected_revision=request.expected_revision,
            current_delivery_number=request.current_delivery_number,
            overwrite=request.overwrite,
            conflict_precondition=conflict_precondition,
        )
        if record is None:
            await _abort(
                context,
                grpc.StatusCode.FAILED_PRECONDITION,
                "Workspace upload retry precondition is stale",
            )
        return pb.WorkspaceUploadStatusResponse(status=_status_message(record))


def add_runtime_workspace_upload_coordinator_servicer(
    server: grpc.aio.Server,
    *,
    coordinator: _WorkspaceUploadCoordinator,
    credential_auth: _WorkspaceUploadCredentialAuth,
) -> None:
    """Register the internal Workspace upload service."""
    pb_grpc.add_RuntimeWorkspaceUploadCoordinatorServicer_to_server(
        RuntimeWorkspaceUploadCoordinatorGrpcServicer(
            coordinator=coordinator,
            credential_auth=credential_auth,
        ),
        server,
    )


def _admission_from_create_request(
    request: pb.CreateWorkspaceUploadRequest,
) -> WorkspaceUploadAdmission:
    identity = workspace_upload_identity_from_message(request.identity)
    if not request.HasField("deadline_at"):
        raise ValueError("deadline_at is required")
    _nonnegative(request.expected_size, "expected_size")
    if not request.expected_sha256:
        raise ValueError("expected_sha256 is required")
    return WorkspaceUploadAdmission(
        upload_id=identity.upload_id,
        requester_user_id=identity.requester_user_id,
        workspace_id=identity.workspace_id,
        agent_id=identity.agent_id,
        runtime_id=identity.runtime_id,
        desired_generation=identity.desired_generation,
        session_id=identity.session_id,
        deadline_at=request.deadline_at.ToDatetime(tzinfo=UTC),
        destination_directory=request.destination_directory,
        filename=request.filename,
        destination_path=request.destination_path,
        expected_size=request.expected_size,
        media_type=request.media_type if request.HasField("media_type") else None,
        expected_sha256=request.expected_sha256,
    )


async def _identity_or_abort(
    message: pb.WorkspaceUploadIdentity,
    context: GrpcAbortContext,
) -> WorkspaceUploadIdentity:
    try:
        return workspace_upload_identity_from_message(message)
    except ValueError as exc:
        await _abort(context, grpc.StatusCode.INVALID_ARGUMENT, str(exc))


def _status_message(record: WorkspaceUploadRecord) -> pb.WorkspaceUploadStatus:
    admission = record.admission
    message = pb.WorkspaceUploadStatus(
        identity=pb.WorkspaceUploadIdentity(
            upload_id=admission.upload_id,
            requester_user_id=admission.requester_user_id,
            workspace_id=admission.workspace_id,
            agent_id=admission.agent_id,
            runtime_id=admission.runtime_id,
            desired_generation=admission.desired_generation,
        ),
        revision=record.revision,
        destination_directory=admission.destination_directory,
        filename=admission.filename,
        destination_path=admission.destination_path,
        expected_size=admission.expected_size,
        received_size=record.received_size,
        phase=_phase_to_proto(record.phase),
        current_delivery_number=record.current_delivery_number or 0,
        retry_available=(
            record.source_handle is not None
            and record.phase
            in {
                WorkspaceUploadPhase.CONFLICTED,
                WorkspaceUploadPhase.RETRYABLE_FAILURE,
            }
        ),
        cancel_available=not _terminal(record.phase),
        overwrite_available=(
            record.phase is WorkspaceUploadPhase.CONFLICTED
            and bool(record.delivery_attempts)
            and record.delivery_attempts[-1].conflict_revision is not None
        ),
    )
    if admission.session_id is not None:
        message.identity.session_id = admission.session_id
    # Terminal cleanup removes the ephemeral source object and its internal
    # manifest fields. A successful upload still has authoritative manifest
    # evidence: Runtime delivery could only settle success after verifying the
    # exact admission size and SHA-256. Keep that evidence visible at the
    # public status boundary without retaining the deleted source handle.
    actual_size = record.actual_size
    actual_sha256 = record.actual_sha256
    if record.phase is WorkspaceUploadPhase.SUCCEEDED:
        actual_size = (
            actual_size if actual_size is not None else admission.expected_size
        )
        actual_sha256 = (
            actual_sha256 if actual_sha256 is not None else admission.expected_sha256
        )
    if actual_size is not None:
        message.actual_size = actual_size
    if actual_sha256 is not None:
        message.sha256 = actual_sha256
    if admission.media_type is not None:
        message.media_type = admission.media_type
    if record.outcome is not None:
        message.outcome = _outcome_to_proto(record.outcome)
    if record.failure is not None:
        message.failure = _failure_to_proto(record.failure)
    latest_attempt = record.delivery_attempts[-1] if record.delivery_attempts else None
    if latest_attempt is not None and latest_attempt.destination_evidence is not None:
        evidence = latest_attempt.destination_evidence
        message.destination_evidence.CopyFrom(
            pb.DestinationEvidence(
                kind=evidence.kind,
                modified_at=_timestamp(evidence.modified_at),
            )
        )
        if evidence.size is not None:
            message.destination_evidence.size = evidence.size
        if latest_attempt.conflict_revision is not None:
            message.destination_evidence.conflict_precondition = _decode_token(
                latest_attempt.conflict_revision
            )
    return message


def _phase_to_proto(
    value: WorkspaceUploadPhase,
) -> pb.WorkspaceUploadPhase.ValueType:
    return {
        WorkspaceUploadPhase.QUEUED: pb.WORKSPACE_UPLOAD_PHASE_QUEUED,
        WorkspaceUploadPhase.UPLOADING: pb.WORKSPACE_UPLOAD_PHASE_UPLOADING,
        WorkspaceUploadPhase.MOVING_TO_RUNTIME: (
            pb.WORKSPACE_UPLOAD_PHASE_MOVING_TO_RUNTIME
        ),
        WorkspaceUploadPhase.CONFLICTED: pb.WORKSPACE_UPLOAD_PHASE_CONFLICTED,
        WorkspaceUploadPhase.RETRYABLE_FAILURE: (
            pb.WORKSPACE_UPLOAD_PHASE_RETRYABLE_FAILURE
        ),
        WorkspaceUploadPhase.SUCCEEDED: pb.WORKSPACE_UPLOAD_PHASE_SUCCEEDED,
        WorkspaceUploadPhase.CANCELLED: pb.WORKSPACE_UPLOAD_PHASE_CANCELLED,
        WorkspaceUploadPhase.FAILED: pb.WORKSPACE_UPLOAD_PHASE_FAILED,
        WorkspaceUploadPhase.EXPIRED: pb.WORKSPACE_UPLOAD_PHASE_EXPIRED,
    }[value]


def _failure_to_proto(
    value: WorkspaceUploadFailure,
) -> pb.WorkspaceUploadFailure.ValueType:
    return {
        WorkspaceUploadFailure.ADMISSION: (
            pb.WORKSPACE_UPLOAD_FAILURE_RUNTIME_UNAVAILABLE
        ),
        WorkspaceUploadFailure.AUTHORIZATION: (
            pb.WORKSPACE_UPLOAD_FAILURE_AUTHORIZATION
        ),
        WorkspaceUploadFailure.CANCELLED: pb.WORKSPACE_UPLOAD_FAILURE_CANCELLED,
        WorkspaceUploadFailure.DESTINATION_CONFLICT: (
            pb.WORKSPACE_UPLOAD_FAILURE_DESTINATION_CONFLICT
        ),
        WorkspaceUploadFailure.FENCED: pb.WORKSPACE_UPLOAD_FAILURE_FENCED,
        WorkspaceUploadFailure.INGRESS: pb.WORKSPACE_UPLOAD_FAILURE_TRANSFER,
        WorkspaceUploadFailure.INTEGRITY: pb.WORKSPACE_UPLOAD_FAILURE_INTEGRITY,
        WorkspaceUploadFailure.RUNTIME: pb.WORKSPACE_UPLOAD_FAILURE_RUNTIME_UNAVAILABLE,
        WorkspaceUploadFailure.SIZE: pb.WORKSPACE_UPLOAD_FAILURE_TOO_LARGE,
        WorkspaceUploadFailure.EXPIRED: pb.WORKSPACE_UPLOAD_FAILURE_EXPIRED,
    }[value]


def _outcome_to_proto(
    value: WorkspaceUploadOutcome,
) -> pb.CoordinatorTransferOutcome.ValueType:
    return {
        WorkspaceUploadOutcome.SUCCEEDED: pb.COORDINATOR_TRANSFER_OUTCOME_SUCCEEDED,
        WorkspaceUploadOutcome.CANCELLED: pb.COORDINATOR_TRANSFER_OUTCOME_CANCELLED,
        WorkspaceUploadOutcome.FAILED: pb.COORDINATOR_TRANSFER_OUTCOME_FAILED,
        WorkspaceUploadOutcome.EXPIRED: pb.COORDINATOR_TRANSFER_OUTCOME_EXPIRED,
    }[value]


def _terminal(value: WorkspaceUploadPhase) -> bool:
    return value in {
        WorkspaceUploadPhase.SUCCEEDED,
        WorkspaceUploadPhase.CANCELLED,
        WorkspaceUploadPhase.FAILED,
        WorkspaceUploadPhase.EXPIRED,
    }


def _timestamp(value: datetime) -> timestamp_pb2.Timestamp:
    message = timestamp_pb2.Timestamp()
    message.FromDatetime(value)
    return message


def _encode_token(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _decode_token(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _positive(value: int, name: str) -> None:
    if value <= 0:
        raise ValueError(f"{name} must be positive")


async def _positive_or_abort(
    value: int,
    name: str,
    context: GrpcAbortContext,
) -> None:
    """Abort an RPC with INVALID_ARGUMENT when a positive field is missing."""
    try:
        _positive(value, name)
    except ValueError as exc:
        await _abort(context, grpc.StatusCode.INVALID_ARGUMENT, str(exc))


def _nonnegative(value: int, name: str) -> None:
    if value < 0:
        raise ValueError(f"{name} must not be negative")


async def _abort(
    context: GrpcAbortContext,
    code: grpc.StatusCode,
    details: str,
) -> NoReturn:
    await context.abort(code, details)
    raise AssertionError("unreachable")
