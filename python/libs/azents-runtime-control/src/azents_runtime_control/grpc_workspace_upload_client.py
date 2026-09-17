"""Typed internal gRPC client for Runtime Control Workspace uploads."""

from __future__ import annotations

from collections.abc import Awaitable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Protocol, TypeAlias, TypeVar

import grpc
from google.protobuf import timestamp_pb2

from azents_runtime_control.grpc_tls import (
    GrpcClientTlsConfig,
    create_grpc_aio_channel,
)
from azents_runtime_control.grpc_transfer_coordinator_client import (
    CoordinatorCredentialRequest,
    CoordinatorTransferDirection,
    CoordinatorTransferIdentity,
    coordinator_request_sha256,
)
from azents_runtime_control.proto import (
    runtime_transfer_coordinator_pb2 as pb,
)

if TYPE_CHECKING:
    from azents_runtime_control.proto.runtime_transfer_coordinator_pb2_grpc import (
        RuntimeWorkspaceUploadCoordinatorAsyncStub as _WorkspaceUploadStub,
    )
else:
    from azents_runtime_control.proto.runtime_transfer_coordinator_pb2_grpc import (
        RuntimeWorkspaceUploadCoordinatorStub as _WorkspaceUploadStub,
    )

WORKSPACE_UPLOAD_OPERATION_CREATE = (
    "RuntimeWorkspaceUploadCoordinator/CreateWorkspaceUpload"
)
WORKSPACE_UPLOAD_OPERATION_ISSUE_TICKET = (
    "RuntimeWorkspaceUploadCoordinator/IssueWorkspaceUploadTicket"
)
WORKSPACE_UPLOAD_OPERATION_FINALIZE = (
    "RuntimeWorkspaceUploadCoordinator/FinalizeWorkspaceUpload"
)
WORKSPACE_UPLOAD_OPERATION_GET = "RuntimeWorkspaceUploadCoordinator/GetWorkspaceUpload"
WORKSPACE_UPLOAD_OPERATION_CANCEL = (
    "RuntimeWorkspaceUploadCoordinator/CancelWorkspaceUpload"
)
WORKSPACE_UPLOAD_OPERATION_RETRY = (
    "RuntimeWorkspaceUploadCoordinator/RetryWorkspaceUpload"
)


class WorkspaceUploadPhase(StrEnum):
    """Workspace upload lifecycle phase."""

    QUEUED = "queued"
    UPLOADING = "uploading"
    MOVING_TO_RUNTIME = "moving_to_runtime"
    CONFLICTED = "conflicted"
    RETRYABLE_FAILURE = "retryable_failure"
    SUCCEEDED = "succeeded"
    CANCELLED = "cancelled"
    FAILED = "failed"
    EXPIRED = "expired"


class WorkspaceUploadFailure(StrEnum):
    """Workspace upload failure classification."""

    INVALID_REQUEST = "invalid_request"
    AUTHORIZATION = "authorization"
    TOO_LARGE = "too_large"
    REVISION_CONFLICT = "revision_conflict"
    DESTINATION_CONFLICT = "destination_conflict"
    RUNTIME_UNAVAILABLE = "runtime_unavailable"
    FENCED = "fenced"
    INTEGRITY = "integrity"
    TRANSFER = "transfer"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


class WorkspaceUploadOutcome(StrEnum):
    """Workspace upload terminal outcome."""

    SUCCEEDED = "succeeded"
    CANCELLED = "cancelled"
    FAILED = "failed"
    EXPIRED = "expired"


@dataclass(frozen=True)
class WorkspaceUploadIdentity:
    """Requester and Runtime binding for one upload operation."""

    upload_id: str
    requester_user_id: str
    workspace_id: str
    agent_id: str
    runtime_id: str
    desired_generation: int
    session_id: str | None = None

    def __post_init__(self) -> None:
        for value, name in (
            (self.upload_id, "upload_id"),
            (self.requester_user_id, "requester_user_id"),
            (self.workspace_id, "workspace_id"),
            (self.agent_id, "agent_id"),
            (self.runtime_id, "runtime_id"),
        ):
            _bounded(value, name, 128)
        if self.session_id is not None:
            _bounded(self.session_id, "session_id", 128)
        if self.desired_generation <= 0:
            raise ValueError("desired_generation must be positive")


@dataclass(frozen=True)
class WorkspaceUploadDestinationEvidence:
    """Public-safe destination conflict evidence."""

    kind: str
    size: int | None
    modified_at: datetime
    conflict_precondition: bytes


@dataclass(frozen=True)
class WorkspaceUploadStatus:
    """Public-safe Workspace upload status projection."""

    identity: WorkspaceUploadIdentity
    revision: int
    destination_directory: str
    filename: str
    destination_path: str
    expected_size: int
    received_size: int
    actual_size: int | None
    sha256: str | None
    media_type: str | None
    phase: WorkspaceUploadPhase
    current_delivery_number: int
    outcome: WorkspaceUploadOutcome | None
    failure: WorkspaceUploadFailure | None
    retry_available: bool
    cancel_available: bool
    overwrite_available: bool
    destination_evidence: WorkspaceUploadDestinationEvidence | None


@dataclass(frozen=True)
class WorkspaceUploadCreateRequest:
    """Typed metadata for one upload admission."""

    identity: WorkspaceUploadIdentity
    destination_directory: str
    filename: str
    destination_path: str
    expected_size: int
    expected_sha256: str
    media_type: str | None
    deadline_at: datetime


@dataclass(frozen=True)
class WorkspaceUploadTicket:
    """Short-lived browser PUT capability for one upload."""

    method: str
    url: str
    expires_at: datetime
    headers: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class WorkspaceUploadCancelRequest:
    """Typed exact cancellation preconditions."""

    identity: WorkspaceUploadIdentity
    expected_revision: int
    current_delivery_number: int | None


@dataclass(frozen=True)
class WorkspaceUploadRetryRequest:
    """Typed exact retry and overwrite-fencing preconditions."""

    identity: WorkspaceUploadIdentity
    expected_revision: int
    current_delivery_number: int
    overwrite: bool
    conflict_precondition: bytes | None


class WorkspaceUploadCredentialSupplier(Protocol):
    """Issue one short-lived credential for one exact upload request."""

    def issue(
        self,
        request: CoordinatorCredentialRequest,
    ) -> Awaitable[str]:
        """Issue a request-bound trusted-service credential."""
        ...


_RequestT_contra = TypeVar("_RequestT_contra", contravariant=True)
_ResponseT_co = TypeVar("_ResponseT_co", covariant=True)


class WorkspaceUploadUnaryUnaryCall(Protocol[_RequestT_contra, _ResponseT_co]):
    """Unary Workspace upload RPC callable."""

    def __call__(
        self,
        request: _RequestT_contra,
        /,
        *,
        metadata: Sequence[tuple[str, str]],
    ) -> Awaitable[_ResponseT_co]:
        """Execute one unary Workspace upload RPC."""
        ...


class WorkspaceUploadStub(Protocol):
    """Generated RPC call surface used by the typed client."""

    @property
    def CreateWorkspaceUpload(
        self,
    ) -> WorkspaceUploadUnaryUnaryCall[
        pb.CreateWorkspaceUploadRequest,
        pb.WorkspaceUploadStatusResponse,
    ]: ...

    @property
    def IssueWorkspaceUploadTicket(
        self,
    ) -> WorkspaceUploadUnaryUnaryCall[
        pb.IssueWorkspaceUploadTicketRequest,
        pb.WorkspaceUploadTicketResponse,
    ]: ...

    @property
    def FinalizeWorkspaceUpload(
        self,
    ) -> WorkspaceUploadUnaryUnaryCall[
        pb.FinalizeWorkspaceUploadRequest,
        pb.WorkspaceUploadStatusResponse,
    ]: ...

    @property
    def GetWorkspaceUpload(
        self,
    ) -> WorkspaceUploadUnaryUnaryCall[
        pb.GetWorkspaceUploadRequest,
        pb.WorkspaceUploadStatusResponse,
    ]: ...

    @property
    def CancelWorkspaceUpload(
        self,
    ) -> WorkspaceUploadUnaryUnaryCall[
        pb.CancelWorkspaceUploadRequest,
        pb.WorkspaceUploadStatusResponse,
    ]: ...

    @property
    def RetryWorkspaceUpload(
        self,
    ) -> WorkspaceUploadUnaryUnaryCall[
        pb.RetryWorkspaceUploadRequest,
        pb.WorkspaceUploadStatusResponse,
    ]: ...


WorkspaceUploadCredentialRequestMessage: TypeAlias = (
    pb.CreateWorkspaceUploadRequest
    | pb.IssueWorkspaceUploadTicketRequest
    | pb.FinalizeWorkspaceUploadRequest
    | pb.GetWorkspaceUploadRequest
    | pb.CancelWorkspaceUploadRequest
    | pb.RetryWorkspaceUploadRequest
)


class GrpcRuntimeWorkspaceUploadCoordinatorClient:
    """Secret-free typed client for the internal upload coordinator."""

    def __init__(
        self,
        stub: WorkspaceUploadStub,
        *,
        credential_supplier: WorkspaceUploadCredentialSupplier,
        channel: grpc.aio.Channel | None = None,
    ) -> None:
        self._stub = stub
        self._credential_supplier = credential_supplier
        self._channel = channel

    @classmethod
    def from_endpoint(
        cls,
        endpoint: str,
        *,
        credential_supplier: WorkspaceUploadCredentialSupplier,
        tls: GrpcClientTlsConfig | None,
        allow_insecure: bool,
    ) -> "GrpcRuntimeWorkspaceUploadCoordinatorClient":
        channel = create_grpc_aio_channel(
            endpoint,
            tls=tls,
            allow_insecure=allow_insecure,
        )
        return cls(
            _WorkspaceUploadStub(channel),
            credential_supplier=credential_supplier,
            channel=channel,
        )

    async def close(self) -> None:
        """Close the endpoint-owned channel."""
        if self._channel is not None:
            await self._channel.close()

    async def create(
        self,
        request: WorkspaceUploadCreateRequest,
    ) -> WorkspaceUploadStatus:
        message = create_workspace_upload_request_to_message(request)
        response = await self._stub.CreateWorkspaceUpload(
            message,
            metadata=await self._metadata(
                WORKSPACE_UPLOAD_OPERATION_CREATE,
                message,
            ),
        )
        return workspace_upload_status_response_from_message(response)

    async def issue_ticket(
        self,
        *,
        identity: WorkspaceUploadIdentity,
        expected_revision: int,
    ) -> tuple[WorkspaceUploadStatus, WorkspaceUploadTicket]:
        message = pb.IssueWorkspaceUploadTicketRequest(
            identity=workspace_upload_identity_to_message(identity),
            expected_revision=expected_revision,
        )
        response = await self._stub.IssueWorkspaceUploadTicket(
            message,
            metadata=await self._metadata(
                WORKSPACE_UPLOAD_OPERATION_ISSUE_TICKET,
                message,
            ),
        )
        return workspace_upload_ticket_response_from_message(response)

    async def finalize(
        self,
        *,
        identity: WorkspaceUploadIdentity,
        expected_revision: int,
    ) -> WorkspaceUploadStatus:
        message = pb.FinalizeWorkspaceUploadRequest(
            identity=workspace_upload_identity_to_message(identity),
            expected_revision=expected_revision,
        )
        response = await self._stub.FinalizeWorkspaceUpload(
            message,
            metadata=await self._metadata(
                WORKSPACE_UPLOAD_OPERATION_FINALIZE,
                message,
            ),
        )
        return workspace_upload_status_response_from_message(response)

    async def get(self, identity: WorkspaceUploadIdentity) -> WorkspaceUploadStatus:
        message = pb.GetWorkspaceUploadRequest(
            identity=workspace_upload_identity_to_message(identity)
        )
        response = await self._stub.GetWorkspaceUpload(
            message,
            metadata=await self._metadata(WORKSPACE_UPLOAD_OPERATION_GET, message),
        )
        return workspace_upload_status_response_from_message(response)

    async def cancel(
        self,
        request: WorkspaceUploadCancelRequest,
    ) -> WorkspaceUploadStatus:
        message = cancel_workspace_upload_request_to_message(request)
        response = await self._stub.CancelWorkspaceUpload(
            message,
            metadata=await self._metadata(
                WORKSPACE_UPLOAD_OPERATION_CANCEL,
                message,
            ),
        )
        return workspace_upload_status_response_from_message(response)

    async def retry(
        self,
        request: WorkspaceUploadRetryRequest,
    ) -> WorkspaceUploadStatus:
        message = retry_workspace_upload_request_to_message(request)
        response = await self._stub.RetryWorkspaceUpload(
            message,
            metadata=await self._metadata(
                WORKSPACE_UPLOAD_OPERATION_RETRY,
                message,
            ),
        )
        return workspace_upload_status_response_from_message(response)

    async def _metadata(
        self,
        operation: str,
        message: WorkspaceUploadCredentialRequestMessage,
    ) -> tuple[tuple[str, str]]:
        credential = await self._credential_supplier.issue(
            workspace_upload_credential_request(operation, message)
        )
        if not credential or credential != credential.strip():
            raise ValueError(
                "Workspace upload credential supplier returned invalid token"
            )
        return (("authorization", f"Bearer {credential}"),)


def workspace_upload_credential_identity(
    identity: WorkspaceUploadIdentity,
) -> CoordinatorTransferIdentity:
    """Project upload identity into the shared credential identity envelope."""
    return CoordinatorTransferIdentity(
        transfer_id=identity.upload_id,
        attempt_id="workspace-upload",
        direction=CoordinatorTransferDirection.DOWNLOAD.value,
        runtime_id=identity.runtime_id,
        desired_generation=identity.desired_generation,
        operation_id=identity.upload_id,
        session_id=identity.session_id,
        agent_id=identity.agent_id,
    )


def workspace_upload_credential_request(
    operation: str,
    message: WorkspaceUploadCredentialRequestMessage,
) -> CoordinatorCredentialRequest:
    """Bind one exact upload metadata request to trusted credentials."""
    identity = workspace_upload_identity_from_message(message.identity)
    return CoordinatorCredentialRequest(
        operation=operation,
        identity=workspace_upload_credential_identity(identity),
        request_sha256=coordinator_request_sha256(message),
    )


def workspace_upload_identity_to_message(
    value: WorkspaceUploadIdentity,
) -> pb.WorkspaceUploadIdentity:
    message = pb.WorkspaceUploadIdentity(
        upload_id=value.upload_id,
        requester_user_id=value.requester_user_id,
        workspace_id=value.workspace_id,
        agent_id=value.agent_id,
        runtime_id=value.runtime_id,
        desired_generation=value.desired_generation,
    )
    if value.session_id is not None:
        message.session_id = value.session_id
    return message


def workspace_upload_identity_from_message(
    message: pb.WorkspaceUploadIdentity,
) -> WorkspaceUploadIdentity:
    return WorkspaceUploadIdentity(
        upload_id=message.upload_id,
        requester_user_id=message.requester_user_id,
        workspace_id=message.workspace_id,
        agent_id=message.agent_id,
        runtime_id=message.runtime_id,
        desired_generation=message.desired_generation,
        session_id=message.session_id if message.HasField("session_id") else None,
    )


def create_workspace_upload_request_to_message(
    request: WorkspaceUploadCreateRequest,
) -> pb.CreateWorkspaceUploadRequest:
    message = pb.CreateWorkspaceUploadRequest(
        identity=workspace_upload_identity_to_message(request.identity),
        destination_directory=request.destination_directory,
        filename=request.filename,
        destination_path=request.destination_path,
        expected_size=request.expected_size,
        expected_sha256=request.expected_sha256,
        deadline_at=_timestamp_message(request.deadline_at),
    )
    if request.media_type is not None:
        message.media_type = request.media_type
    return message


def cancel_workspace_upload_request_to_message(
    request: WorkspaceUploadCancelRequest,
) -> pb.CancelWorkspaceUploadRequest:
    return pb.CancelWorkspaceUploadRequest(
        identity=workspace_upload_identity_to_message(request.identity),
        expected_revision=request.expected_revision,
        current_delivery_number=request.current_delivery_number or 0,
    )


def retry_workspace_upload_request_to_message(
    request: WorkspaceUploadRetryRequest,
) -> pb.RetryWorkspaceUploadRequest:
    message = pb.RetryWorkspaceUploadRequest(
        identity=workspace_upload_identity_to_message(request.identity),
        expected_revision=request.expected_revision,
        current_delivery_number=request.current_delivery_number,
        overwrite=request.overwrite,
    )
    if request.conflict_precondition is not None:
        message.conflict_precondition = request.conflict_precondition
    return message


def workspace_upload_status_response_from_message(
    message: pb.WorkspaceUploadStatusResponse,
) -> WorkspaceUploadStatus:
    if not message.HasField("status"):
        raise ValueError("Workspace upload status response is missing status")
    return workspace_upload_status_from_message(message.status)


def workspace_upload_ticket_response_from_message(
    message: pb.WorkspaceUploadTicketResponse,
) -> tuple[WorkspaceUploadStatus, WorkspaceUploadTicket]:
    """Decode one metadata status and short-lived browser PUT capability."""
    if not message.HasField("status") or not message.HasField("ticket"):
        raise ValueError("Workspace upload ticket response is incomplete")
    ticket = message.ticket
    if not ticket.HasField("expires_at"):
        raise ValueError("Workspace upload ticket expiry is missing")
    return (
        workspace_upload_status_from_message(message.status),
        WorkspaceUploadTicket(
            method=ticket.method,
            url=ticket.url,
            expires_at=_datetime_from_message(ticket.expires_at),
            headers=tuple((header.name, header.value) for header in ticket.headers),
        ),
    )


def workspace_upload_status_from_message(
    message: pb.WorkspaceUploadStatus,
) -> WorkspaceUploadStatus:
    destination_evidence = None
    if message.HasField("destination_evidence"):
        evidence = message.destination_evidence
        destination_evidence = WorkspaceUploadDestinationEvidence(
            kind=evidence.kind,
            size=evidence.size if evidence.HasField("size") else None,
            modified_at=_datetime_from_message(evidence.modified_at),
            conflict_precondition=(
                evidence.conflict_precondition
                if evidence.HasField("conflict_precondition")
                else b""
            ),
        )
    return WorkspaceUploadStatus(
        identity=workspace_upload_identity_from_message(message.identity),
        revision=message.revision,
        destination_directory=message.destination_directory,
        filename=message.filename,
        destination_path=message.destination_path,
        expected_size=message.expected_size,
        received_size=message.received_size,
        actual_size=message.actual_size if message.HasField("actual_size") else None,
        sha256=message.sha256 if message.HasField("sha256") else None,
        media_type=message.media_type if message.HasField("media_type") else None,
        phase=_phase_from_proto(message.phase),
        current_delivery_number=message.current_delivery_number,
        outcome=(
            _outcome_from_proto(message.outcome)
            if message.HasField("outcome")
            else None
        ),
        failure=(
            _failure_from_proto(message.failure)
            if message.HasField("failure")
            else None
        ),
        retry_available=message.retry_available,
        cancel_available=message.cancel_available,
        overwrite_available=message.overwrite_available,
        destination_evidence=destination_evidence,
    )


def _phase_from_proto(
    value: pb.WorkspaceUploadPhase.ValueType,
) -> WorkspaceUploadPhase:
    return WorkspaceUploadPhase(
        {
            pb.WORKSPACE_UPLOAD_PHASE_QUEUED: "queued",
            pb.WORKSPACE_UPLOAD_PHASE_UPLOADING: "uploading",
            pb.WORKSPACE_UPLOAD_PHASE_MOVING_TO_RUNTIME: "moving_to_runtime",
            pb.WORKSPACE_UPLOAD_PHASE_CONFLICTED: "conflicted",
            pb.WORKSPACE_UPLOAD_PHASE_RETRYABLE_FAILURE: "retryable_failure",
            pb.WORKSPACE_UPLOAD_PHASE_SUCCEEDED: "succeeded",
            pb.WORKSPACE_UPLOAD_PHASE_CANCELLED: "cancelled",
            pb.WORKSPACE_UPLOAD_PHASE_FAILED: "failed",
            pb.WORKSPACE_UPLOAD_PHASE_EXPIRED: "expired",
        }[value]
    )


def _failure_from_proto(
    value: pb.WorkspaceUploadFailure.ValueType,
) -> WorkspaceUploadFailure:
    return WorkspaceUploadFailure(
        {
            pb.WORKSPACE_UPLOAD_FAILURE_INVALID_REQUEST: "invalid_request",
            pb.WORKSPACE_UPLOAD_FAILURE_AUTHORIZATION: "authorization",
            pb.WORKSPACE_UPLOAD_FAILURE_TOO_LARGE: "too_large",
            pb.WORKSPACE_UPLOAD_FAILURE_REVISION_CONFLICT: "revision_conflict",
            pb.WORKSPACE_UPLOAD_FAILURE_DESTINATION_CONFLICT: "destination_conflict",
            pb.WORKSPACE_UPLOAD_FAILURE_RUNTIME_UNAVAILABLE: "runtime_unavailable",
            pb.WORKSPACE_UPLOAD_FAILURE_FENCED: "fenced",
            pb.WORKSPACE_UPLOAD_FAILURE_INTEGRITY: "integrity",
            pb.WORKSPACE_UPLOAD_FAILURE_TRANSFER: "transfer",
            pb.WORKSPACE_UPLOAD_FAILURE_CANCELLED: "cancelled",
            pb.WORKSPACE_UPLOAD_FAILURE_EXPIRED: "expired",
        }[value]
    )


def _outcome_from_proto(
    value: pb.CoordinatorTransferOutcome.ValueType,
) -> WorkspaceUploadOutcome:
    return WorkspaceUploadOutcome(
        {
            pb.COORDINATOR_TRANSFER_OUTCOME_SUCCEEDED: "succeeded",
            pb.COORDINATOR_TRANSFER_OUTCOME_CANCELLED: "cancelled",
            pb.COORDINATOR_TRANSFER_OUTCOME_FAILED: "failed",
            pb.COORDINATOR_TRANSFER_OUTCOME_EXPIRED: "expired",
        }[value]
    )


def _timestamp_message(value: datetime) -> timestamp_pb2.Timestamp:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Workspace upload deadline must be timezone-aware")
    message = timestamp_pb2.Timestamp()
    message.FromDatetime(value.astimezone(UTC))
    return message


def _datetime_from_message(value: timestamp_pb2.Timestamp) -> datetime:
    return value.ToDatetime(tzinfo=UTC)


def _bounded(value: str, name: str, maximum: int) -> None:
    if not value or len(value.encode("utf-8")) > maximum:
        raise ValueError(f"{name} is empty or exceeds {maximum} bytes")
