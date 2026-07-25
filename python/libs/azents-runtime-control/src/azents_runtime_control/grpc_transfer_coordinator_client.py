"""Typed gRPC client and values for trusted Runtime transfer coordination."""

# pyright: reportAttributeAccessIssue=false, reportArgumentType=false
# Protobuf generated modules expose dynamic message attributes.

import hashlib
from collections.abc import Awaitable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol

import grpc
from google.protobuf import timestamp_pb2
from google.protobuf.message import Message

from azents_runtime_control.grpc_tls import (
    GrpcClientTlsConfig,
    create_grpc_aio_channel,
)
from azents_runtime_control.proto import (
    runtime_transfer_coordinator_pb2,
    runtime_transfer_coordinator_pb2_grpc,
)
from azents_runtime_control.transfer import CoordinatorTransferIdentity

COORDINATOR_OPERATION_ADMIT_TRANSFER = "RuntimeTransferCoordinator/AdmitTransfer"
COORDINATOR_OPERATION_MARK_TRANSFER_READY = (
    "RuntimeTransferCoordinator/MarkTransferReady"
)
COORDINATOR_OPERATION_DISPATCH_TRANSFER = "RuntimeTransferCoordinator/DispatchTransfer"
COORDINATOR_OPERATION_CANCEL_TRANSFER = "RuntimeTransferCoordinator/CancelTransfer"
COORDINATOR_OPERATION_GET_VERIFIED_OBJECT = (
    "RuntimeTransferCoordinator/GetVerifiedObject"
)
COORDINATOR_OPERATION_CLAIM_CONSUMER = "RuntimeTransferCoordinator/ClaimConsumer"
COORDINATOR_OPERATION_ACKNOWLEDGE_CONSUMER = (
    "RuntimeTransferCoordinator/AcknowledgeConsumer"
)
COORDINATOR_OPERATION_ABANDON_CONSUMER = "RuntimeTransferCoordinator/AbandonConsumer"
COORDINATOR_OPERATION_SETTLE_TRANSFER = "RuntimeTransferCoordinator/SettleTransfer"
COORDINATOR_OPERATION_RECORD_CLEANUP = "RuntimeTransferCoordinator/RecordCleanup"
COORDINATOR_OPERATION_GET_TRANSFER_STATUS = (
    "RuntimeTransferCoordinator/GetTransferStatus"
)


class CoordinatorTransferDirection(StrEnum):
    """Trusted coordinator transfer direction."""

    DOWNLOAD = "download"
    UPLOAD = "upload"


class CoordinatorTransferPhase(StrEnum):
    """Trusted coordinator transfer lifecycle phase."""

    PREPARING = "preparing"
    READY = "ready"
    STREAMING = "streaming"
    VERIFYING = "verifying"
    AVAILABLE = "available"
    CONSUMING = "consuming"
    CONSUMED = "consumed"
    COMMITTED = "committed"
    TERMINAL = "terminal"


class CoordinatorTransferOutcome(StrEnum):
    """Trusted coordinator terminal outcome."""

    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"
    SUPERSEDED = "superseded"


class CoordinatorTransferFailure(StrEnum):
    """Trusted coordinator terminal failure classification."""

    ADMISSION = "admission"
    CANCELLED = "cancelled"
    EXPIRED = "expired"
    FENCED = "fenced"
    INTEGRITY = "integrity"
    STREAM = "stream"
    CONSUMER = "consumer"


class CoordinatorCleanupStatus(StrEnum):
    """Trusted coordinator object cleanup status."""

    NOT_REQUIRED = "not_required"
    PENDING = "pending"
    COMPLETE = "complete"
    RETRYABLE_FAILURE = "retryable_failure"


class CoordinatorCancellationReason(StrEnum):
    """Trusted coordinator cancellation cause."""

    CALLER = "caller"
    DEADLINE = "deadline"
    SUPERSEDED = "superseded"
    SHUTDOWN = "shutdown"


class CoordinatorDispatchStatus(StrEnum):
    """Trusted coordinator Runner dispatch state."""

    NOT_BOUND = "not_bound"
    BOUND = "bound"
    DELIVERABLE = "deliverable"
    ENQUEUED = "enqueued"


@dataclass(frozen=True)
class CoordinatorExpectedManifest:
    """Expected metadata for a transfer object."""

    size: int | None
    sha256: str | None


@dataclass(frozen=True)
class CoordinatorObjectManifest:
    """Verified metadata for a transfer object."""

    size: int | None
    sha256: str


@dataclass(frozen=True)
class CoordinatorOpaqueObjectHandle:
    """Opaque trusted-service object reference without storage authority."""

    value: str


@dataclass(frozen=True)
class CoordinatorTransferStatus:
    """Metadata-only projection of one trusted transfer attempt."""

    identity: CoordinatorTransferIdentity
    phase: CoordinatorTransferPhase
    revision: int
    accepted_runner_generation: int | None
    dispatch_id: str | None
    dispatch_status: CoordinatorDispatchStatus
    expected_manifest: CoordinatorExpectedManifest
    actual_manifest: CoordinatorObjectManifest | None
    deadline_at: datetime
    logical_expires_at: datetime
    outcome: CoordinatorTransferOutcome | None
    failure: CoordinatorTransferFailure | None
    cleanup_status: CoordinatorCleanupStatus
    cancellation_requested: bool


@dataclass(frozen=True)
class CoordinatorAdmitTransferRequest:
    """Values for trusted transfer admission."""

    identity: CoordinatorTransferIdentity
    lease_id: str
    runtime_path: str
    overwrite: bool | None
    expected_manifest: CoordinatorExpectedManifest
    product_maximum_size: int | None
    provider_maximum_size: int | None
    deadline_at: datetime
    source_expires_at: datetime | None
    resource_class: str


@dataclass(frozen=True)
class CoordinatorAdmitTransferResult:
    """Trusted admission result with its opaque object handle."""

    status: CoordinatorTransferStatus
    admitted_object_handle: CoordinatorOpaqueObjectHandle


@dataclass(frozen=True)
class CoordinatorMarkTransferReadyRequest:
    """Values for marking a trusted transfer ready."""

    identity: CoordinatorTransferIdentity
    expected_revision: int
    object_handle: CoordinatorOpaqueObjectHandle
    object_manifest: CoordinatorObjectManifest


@dataclass(frozen=True)
class CoordinatorDispatchTransferRequest:
    """Values for binding and dispatching a transfer."""

    identity: CoordinatorTransferIdentity
    expected_revision: int
    dispatch_id: str


@dataclass(frozen=True)
class CoordinatorCancelTransferRequest:
    """Values for a trusted transfer cancellation."""

    identity: CoordinatorTransferIdentity
    expected_revision: int
    reason: CoordinatorCancellationReason


@dataclass(frozen=True)
class CoordinatorGetVerifiedObjectRequest:
    """Values for resolving a verified object for one consumer claim."""

    identity: CoordinatorTransferIdentity
    expected_revision: int
    consumer_claim_id: str


@dataclass(frozen=True)
class CoordinatorGetVerifiedObjectResult:
    """Verified object result for a currently claimed consumer."""

    status: CoordinatorTransferStatus
    verified_object_handle: CoordinatorOpaqueObjectHandle
    actual_manifest: CoordinatorObjectManifest


@dataclass(frozen=True)
class CoordinatorConsumerRequest:
    """Values for a consumer claim, acknowledgement, or abandonment."""

    identity: CoordinatorTransferIdentity
    expected_revision: int
    consumer_claim_id: str


@dataclass(frozen=True)
class CoordinatorSettleTransferRequest:
    """Values for one trusted terminal transfer settlement."""

    identity: CoordinatorTransferIdentity
    expected_revision: int
    outcome: CoordinatorTransferOutcome
    failure: CoordinatorTransferFailure | None


@dataclass(frozen=True)
class CoordinatorRecordCleanupRequest:
    """Values for recording trusted physical cleanup evidence."""

    identity: CoordinatorTransferIdentity
    expected_revision: int
    cleanup_status: CoordinatorCleanupStatus


@dataclass(frozen=True)
class CoordinatorGetTransferStatusRequest:
    """Values for reading a trusted transfer status projection."""

    identity: CoordinatorTransferIdentity


@dataclass(frozen=True)
class CoordinatorCredentialRequest:
    """Secret-free exact request values supplied to a credential authority."""

    operation: str
    identity: CoordinatorTransferIdentity
    request_sha256: str


class CoordinatorCredentialSupplier(Protocol):
    """Issue one short-lived trusted-service credential per RPC call."""

    def issue(
        self,
        request: CoordinatorCredentialRequest,
    ) -> Awaitable[str]:
        """Issue a credential for one exact coordinator request."""
        ...


class CoordinatorUnaryUnaryCall(Protocol):
    """Unary coordinator RPC callable."""

    def __call__(
        self,
        request: Message,
        /,
        *,
        metadata: Sequence[tuple[str, str]],
    ) -> Awaitable[Message]:
        """Execute one coordinator RPC."""
        ...


class RuntimeTransferCoordinatorStub(Protocol):
    """Typed callable surface required from the generated coordinator stub."""

    AdmitTransfer: CoordinatorUnaryUnaryCall
    MarkTransferReady: CoordinatorUnaryUnaryCall
    DispatchTransfer: CoordinatorUnaryUnaryCall
    CancelTransfer: CoordinatorUnaryUnaryCall
    GetVerifiedObject: CoordinatorUnaryUnaryCall
    ClaimConsumer: CoordinatorUnaryUnaryCall
    AcknowledgeConsumer: CoordinatorUnaryUnaryCall
    AbandonConsumer: CoordinatorUnaryUnaryCall
    SettleTransfer: CoordinatorUnaryUnaryCall
    RecordCleanup: CoordinatorUnaryUnaryCall
    GetTransferStatus: CoordinatorUnaryUnaryCall


class GrpcRuntimeTransferCoordinatorClient:
    """Secret-free typed gRPC client for trusted transfer coordination."""

    def __init__(
        self,
        stub: object,
        *,
        credential_supplier: CoordinatorCredentialSupplier,
        channel: grpc.aio.Channel | None,
    ) -> None:
        """Initialize the client with a generated stub and credential supplier.

        :param stub: generated coordinator RPC stub
        :param credential_supplier: authority that issues exact RPC credentials
        :param channel: owned gRPC channel, when created from an endpoint
        """
        self._stub = stub
        self._credential_supplier = credential_supplier
        self._channel = channel

    @classmethod
    def from_endpoint(
        cls,
        endpoint: str,
        *,
        credential_supplier: CoordinatorCredentialSupplier,
        tls: GrpcClientTlsConfig | None,
        allow_insecure: bool,
    ) -> "GrpcRuntimeTransferCoordinatorClient":
        """Create a coordinator client with TLS or explicit insecure transport.

        :param endpoint: coordinator gRPC endpoint
        :param credential_supplier: authority that issues exact RPC credentials
        :param tls: TLS configuration, when secure transport is used
        :param allow_insecure: whether plaintext transport is explicitly allowed
        :returns: configured coordinator client
        """
        channel = create_grpc_aio_channel(
            endpoint,
            tls=tls,
            allow_insecure=allow_insecure,
        )
        stub = runtime_transfer_coordinator_pb2_grpc.RuntimeTransferCoordinatorStub(
            channel
        )
        return cls(
            stub,
            credential_supplier=credential_supplier,
            channel=channel,
        )

    async def close(self) -> None:
        """Close the endpoint-owned gRPC channel, if any."""
        if self._channel is not None:
            await self._channel.close()

    async def admit_transfer(
        self,
        request: CoordinatorAdmitTransferRequest,
    ) -> CoordinatorAdmitTransferResult:
        """Admit one trusted transfer attempt.

        :param request: typed transfer admission values
        :returns: admitted status and opaque trusted object handle
        """
        message = admit_transfer_request_to_message(request)
        response = await self._stub.AdmitTransfer(
            message,
            metadata=await self._metadata(
                COORDINATOR_OPERATION_ADMIT_TRANSFER,
                message,
            ),
        )
        return admit_transfer_result_from_message(response)

    async def mark_transfer_ready(
        self,
        request: CoordinatorMarkTransferReadyRequest,
    ) -> CoordinatorTransferStatus:
        """Mark one trusted transfer object ready.

        :param request: typed ready transition values
        :returns: current transfer status
        """
        message = mark_transfer_ready_request_to_message(request)
        response = await self._stub.MarkTransferReady(
            message,
            metadata=await self._metadata(
                COORDINATOR_OPERATION_MARK_TRANSFER_READY,
                message,
            ),
        )
        return transfer_status_response_from_message(response)

    async def dispatch_transfer(
        self,
        request: CoordinatorDispatchTransferRequest,
    ) -> CoordinatorTransferStatus:
        """Bind and dispatch one transfer intent.

        :param request: typed dispatch transition values
        :returns: current transfer status
        """
        message = dispatch_transfer_request_to_message(request)
        response = await self._stub.DispatchTransfer(
            message,
            metadata=await self._metadata(
                COORDINATOR_OPERATION_DISPATCH_TRANSFER,
                message,
            ),
        )
        return transfer_status_response_from_message(response)

    async def cancel_transfer(
        self,
        request: CoordinatorCancelTransferRequest,
    ) -> CoordinatorTransferStatus:
        """Cancel one trusted transfer attempt.

        :param request: typed cancellation values
        :returns: current transfer status
        """
        message = cancel_transfer_request_to_message(request)
        response = await self._stub.CancelTransfer(
            message,
            metadata=await self._metadata(
                COORDINATOR_OPERATION_CANCEL_TRANSFER,
                message,
            ),
        )
        return transfer_status_response_from_message(response)

    async def get_verified_object(
        self,
        request: CoordinatorGetVerifiedObjectRequest,
    ) -> CoordinatorGetVerifiedObjectResult:
        """Resolve one claimed verified object.

        :param request: typed verified-object request values
        :returns: status, opaque handle, and verified manifest
        """
        message = get_verified_object_request_to_message(request)
        response = await self._stub.GetVerifiedObject(
            message,
            metadata=await self._metadata(
                COORDINATOR_OPERATION_GET_VERIFIED_OBJECT,
                message,
            ),
        )
        return get_verified_object_result_from_message(response)

    async def claim_consumer(
        self,
        request: CoordinatorConsumerRequest,
    ) -> CoordinatorTransferStatus:
        """Claim one transfer consumer.

        :param request: typed consumer claim values
        :returns: current transfer status
        """
        message = consumer_request_to_message(
            request,
            request_type=runtime_transfer_coordinator_pb2.ClaimConsumerRequest,
        )
        response = await self._stub.ClaimConsumer(
            message,
            metadata=await self._metadata(
                COORDINATOR_OPERATION_CLAIM_CONSUMER,
                message,
            ),
        )
        return transfer_status_response_from_message(response)

    async def acknowledge_consumer(
        self,
        request: CoordinatorConsumerRequest,
    ) -> CoordinatorTransferStatus:
        """Acknowledge one claimed transfer consumer.

        :param request: typed consumer acknowledgement values
        :returns: current transfer status
        """
        message = consumer_request_to_message(
            request,
            request_type=(runtime_transfer_coordinator_pb2.AcknowledgeConsumerRequest),
        )
        response = await self._stub.AcknowledgeConsumer(
            message,
            metadata=await self._metadata(
                COORDINATOR_OPERATION_ACKNOWLEDGE_CONSUMER,
                message,
            ),
        )
        return transfer_status_response_from_message(response)

    async def abandon_consumer(
        self,
        request: CoordinatorConsumerRequest,
    ) -> CoordinatorTransferStatus:
        """Abandon one claimed transfer consumer.

        :param request: typed consumer abandonment values
        :returns: current transfer status
        """
        message = consumer_request_to_message(
            request,
            request_type=runtime_transfer_coordinator_pb2.AbandonConsumerRequest,
        )
        response = await self._stub.AbandonConsumer(
            message,
            metadata=await self._metadata(
                COORDINATOR_OPERATION_ABANDON_CONSUMER,
                message,
            ),
        )
        return transfer_status_response_from_message(response)

    async def settle_transfer(
        self,
        request: CoordinatorSettleTransferRequest,
    ) -> CoordinatorTransferStatus:
        """Settle one trusted transfer attempt.

        :param request: typed terminal transition values
        :returns: current transfer status
        """
        message = settle_transfer_request_to_message(request)
        response = await self._stub.SettleTransfer(
            message,
            metadata=await self._metadata(
                COORDINATOR_OPERATION_SETTLE_TRANSFER,
                message,
            ),
        )
        return transfer_status_response_from_message(response)

    async def record_cleanup(
        self,
        request: CoordinatorRecordCleanupRequest,
    ) -> CoordinatorTransferStatus:
        """Record cleanup evidence for one transfer attempt.

        :param request: typed cleanup transition values
        :returns: current transfer status
        """
        message = record_cleanup_request_to_message(request)
        response = await self._stub.RecordCleanup(
            message,
            metadata=await self._metadata(
                COORDINATOR_OPERATION_RECORD_CLEANUP,
                message,
            ),
        )
        return transfer_status_response_from_message(response)

    async def get_transfer_status(
        self,
        request: CoordinatorGetTransferStatusRequest,
    ) -> CoordinatorTransferStatus:
        """Read one transfer status projection.

        :param request: typed status request values
        :returns: current transfer status
        """
        message = get_transfer_status_request_to_message(request)
        response = await self._stub.GetTransferStatus(
            message,
            metadata=await self._metadata(
                COORDINATOR_OPERATION_GET_TRANSFER_STATUS,
                message,
            ),
        )
        return transfer_status_response_from_message(response)

    async def _metadata(
        self,
        operation: str,
        message: Message,
    ) -> tuple[tuple[str, str]]:
        credential_request = coordinator_credential_request(
            operation,
            message,
        )
        credential = await self._credential_supplier.issue(credential_request)
        if not credential or credential != credential.strip():
            raise ValueError(
                "Coordinator credential supplier returned an invalid token"
            )
        return (("authorization", f"Bearer {credential}"),)


def coordinator_request_sha256(message: Message) -> str:
    """Return the deterministic SHA-256 digest for one protobuf request.

    :param message: complete coordinator protobuf request
    :returns: lowercase hexadecimal request digest
    """
    return hashlib.sha256(message.SerializeToString(deterministic=True)).hexdigest()


def coordinator_credential_request(
    operation: str,
    message: Message,
) -> CoordinatorCredentialRequest:
    """Build secret-free credential values from one exact protobuf request.

    :param operation: exact coordinator RPC operation
    :param message: complete coordinator protobuf request
    :returns: request values for an injected credential authority
    """
    return CoordinatorCredentialRequest(
        operation=operation,
        identity=coordinator_identity_from_message(message.identity),
        request_sha256=coordinator_request_sha256(message),
    )


def coordinator_identity_to_message(
    value: CoordinatorTransferIdentity,
) -> runtime_transfer_coordinator_pb2.CoordinatorTransferIdentity:
    """Map a shared transfer identity to its protobuf representation.

    :param value: trusted shared transfer identity
    :returns: protobuf transfer identity
    """
    message = runtime_transfer_coordinator_pb2.CoordinatorTransferIdentity(
        transfer_id=value.transfer_id,
        attempt_id=value.attempt_id,
        runtime_id=value.runtime_id,
        desired_generation=value.desired_generation,
        direction=_DIRECTION_TO_PROTO[CoordinatorTransferDirection(value.direction)],
        operation_id=value.operation_id,
    )
    if value.session_id is not None:
        message.session_id = value.session_id
    if value.agent_id is not None:
        message.agent_id = value.agent_id
    return message


def coordinator_identity_from_message(
    message: runtime_transfer_coordinator_pb2.CoordinatorTransferIdentity,
) -> CoordinatorTransferIdentity:
    """Map a protobuf transfer identity to shared credential scope.

    :param message: protobuf transfer identity
    :returns: shared trusted transfer identity
    """
    return CoordinatorTransferIdentity(
        transfer_id=message.transfer_id,
        attempt_id=message.attempt_id,
        runtime_id=message.runtime_id,
        desired_generation=message.desired_generation,
        direction=_DIRECTION_FROM_PROTO[message.direction].value,
        operation_id=message.operation_id,
        session_id=message.session_id if message.HasField("session_id") else None,
        agent_id=message.agent_id if message.HasField("agent_id") else None,
    )


def expected_manifest_to_message(
    value: CoordinatorExpectedManifest,
) -> runtime_transfer_coordinator_pb2.ExpectedManifest:
    """Map expected metadata to protobuf.

    :param value: expected transfer object metadata
    :returns: protobuf expected manifest
    """
    message = runtime_transfer_coordinator_pb2.ExpectedManifest()
    if value.size is not None:
        message.size = value.size
    if value.sha256 is not None:
        message.sha256 = value.sha256
    return message


def expected_manifest_from_message(
    message: runtime_transfer_coordinator_pb2.ExpectedManifest,
) -> CoordinatorExpectedManifest:
    """Map expected metadata from protobuf.

    :param message: protobuf expected manifest
    :returns: shared expected manifest
    """
    return CoordinatorExpectedManifest(
        size=message.size if message.HasField("size") else None,
        sha256=message.sha256 if message.HasField("sha256") else None,
    )


def object_manifest_to_message(
    value: CoordinatorObjectManifest,
) -> runtime_transfer_coordinator_pb2.ObjectManifest:
    """Map verified metadata to protobuf.

    :param value: verified transfer object metadata
    :returns: protobuf object manifest
    """
    message = runtime_transfer_coordinator_pb2.ObjectManifest(sha256=value.sha256)
    if value.size is not None:
        message.size = value.size
    return message


def object_manifest_from_message(
    message: runtime_transfer_coordinator_pb2.ObjectManifest,
) -> CoordinatorObjectManifest:
    """Map verified metadata from protobuf.

    :param message: protobuf object manifest
    :returns: shared verified manifest
    """
    return CoordinatorObjectManifest(
        size=message.size if message.HasField("size") else None,
        sha256=message.sha256,
    )


def opaque_object_handle_to_message(
    value: CoordinatorOpaqueObjectHandle,
) -> runtime_transfer_coordinator_pb2.OpaqueObjectHandle:
    """Map an opaque trusted object reference to protobuf.

    :param value: trusted opaque object reference
    :returns: protobuf opaque object handle
    """
    return runtime_transfer_coordinator_pb2.OpaqueObjectHandle(value=value.value)


def opaque_object_handle_from_message(
    message: runtime_transfer_coordinator_pb2.OpaqueObjectHandle,
) -> CoordinatorOpaqueObjectHandle:
    """Map an opaque trusted object reference from protobuf.

    :param message: protobuf opaque object handle
    :returns: trusted opaque object reference
    """
    return CoordinatorOpaqueObjectHandle(value=message.value)


def transfer_status_from_message(
    message: runtime_transfer_coordinator_pb2.CoordinatorTransferStatus,
) -> CoordinatorTransferStatus:
    """Map a protobuf transfer status to shared values.

    :param message: protobuf transfer status
    :returns: shared metadata-only transfer status
    """
    return CoordinatorTransferStatus(
        identity=coordinator_identity_from_message(message.identity),
        phase=_PHASE_FROM_PROTO[message.phase],
        revision=message.revision,
        accepted_runner_generation=(
            message.accepted_runner_generation
            if message.HasField("accepted_runner_generation")
            else None
        ),
        dispatch_id=(message.dispatch_id if message.HasField("dispatch_id") else None),
        dispatch_status=_DISPATCH_STATUS_FROM_PROTO[message.dispatch_status],
        expected_manifest=expected_manifest_from_message(message.expected_manifest),
        actual_manifest=(
            object_manifest_from_message(message.actual_manifest)
            if message.HasField("actual_manifest")
            else None
        ),
        deadline_at=_datetime_from_message(message.deadline_at),
        logical_expires_at=_datetime_from_message(message.logical_expires_at),
        outcome=(
            _OUTCOME_FROM_PROTO[message.outcome]
            if message.outcome
            != runtime_transfer_coordinator_pb2.COORDINATOR_TRANSFER_OUTCOME_UNSPECIFIED
            else None
        ),
        failure=(
            _FAILURE_FROM_PROTO[message.failure]
            if message.failure
            != runtime_transfer_coordinator_pb2.COORDINATOR_TRANSFER_FAILURE_UNSPECIFIED
            else None
        ),
        cleanup_status=_CLEANUP_STATUS_FROM_PROTO[message.cleanup_status],
        cancellation_requested=message.cancellation_requested,
    )


def admit_transfer_request_to_message(
    value: CoordinatorAdmitTransferRequest,
) -> runtime_transfer_coordinator_pb2.AdmitTransferRequest:
    """Map typed admission values to protobuf.

    :param value: typed admission values
    :returns: protobuf admission request
    """
    message = runtime_transfer_coordinator_pb2.AdmitTransferRequest(
        lease_id=value.lease_id,
        runtime_path=value.runtime_path,
        expected_manifest=expected_manifest_to_message(value.expected_manifest),
        deadline_at=_timestamp_message(value.deadline_at),
        resource_class=value.resource_class,
    )
    message.identity.CopyFrom(coordinator_identity_to_message(value.identity))
    if value.overwrite is not None:
        message.overwrite = value.overwrite
    if value.product_maximum_size is not None:
        message.product_maximum_size = value.product_maximum_size
    if value.provider_maximum_size is not None:
        message.provider_maximum_size = value.provider_maximum_size
    if value.source_expires_at is not None:
        message.source_expires_at.CopyFrom(_timestamp_message(value.source_expires_at))
    return message


def mark_transfer_ready_request_to_message(
    value: CoordinatorMarkTransferReadyRequest,
) -> runtime_transfer_coordinator_pb2.MarkTransferReadyRequest:
    """Map typed ready values to protobuf.

    :param value: typed ready transition values
    :returns: protobuf ready request
    """
    message = runtime_transfer_coordinator_pb2.MarkTransferReadyRequest(
        expected_revision=value.expected_revision,
        object_handle=opaque_object_handle_to_message(value.object_handle),
        object_manifest=object_manifest_to_message(value.object_manifest),
    )
    message.identity.CopyFrom(coordinator_identity_to_message(value.identity))
    return message


def dispatch_transfer_request_to_message(
    value: CoordinatorDispatchTransferRequest,
) -> runtime_transfer_coordinator_pb2.DispatchTransferRequest:
    """Map typed dispatch values to protobuf.

    :param value: typed dispatch transition values
    :returns: protobuf dispatch request
    """
    message = runtime_transfer_coordinator_pb2.DispatchTransferRequest(
        expected_revision=value.expected_revision,
        dispatch_id=value.dispatch_id,
    )
    message.identity.CopyFrom(coordinator_identity_to_message(value.identity))
    return message


def cancel_transfer_request_to_message(
    value: CoordinatorCancelTransferRequest,
) -> runtime_transfer_coordinator_pb2.CancelTransferRequest:
    """Map typed cancellation values to protobuf.

    :param value: typed cancellation values
    :returns: protobuf cancellation request
    """
    message = runtime_transfer_coordinator_pb2.CancelTransferRequest(
        expected_revision=value.expected_revision,
        reason=_CANCELLATION_REASON_TO_PROTO[value.reason],
    )
    message.identity.CopyFrom(coordinator_identity_to_message(value.identity))
    return message


def get_verified_object_request_to_message(
    value: CoordinatorGetVerifiedObjectRequest,
) -> runtime_transfer_coordinator_pb2.GetVerifiedObjectRequest:
    """Map typed verified-object values to protobuf.

    :param value: typed verified-object request values
    :returns: protobuf verified-object request
    """
    message = runtime_transfer_coordinator_pb2.GetVerifiedObjectRequest(
        expected_revision=value.expected_revision,
        consumer_claim_id=value.consumer_claim_id,
    )
    message.identity.CopyFrom(coordinator_identity_to_message(value.identity))
    return message


def consumer_request_to_message(
    value: CoordinatorConsumerRequest,
    *,
    request_type: type[Message],
) -> Message:
    """Map typed consumer values to one of the consumer request protobufs.

    :param value: typed consumer request values
    :param request_type: generated consumer protobuf message class
    :returns: protobuf consumer request
    """
    message = request_type(
        expected_revision=value.expected_revision,
        consumer_claim_id=value.consumer_claim_id,
    )
    message.identity.CopyFrom(coordinator_identity_to_message(value.identity))
    return message


def settle_transfer_request_to_message(
    value: CoordinatorSettleTransferRequest,
) -> runtime_transfer_coordinator_pb2.SettleTransferRequest:
    """Map typed settlement values to protobuf.

    :param value: typed terminal transition values
    :returns: protobuf settlement request
    """
    message = runtime_transfer_coordinator_pb2.SettleTransferRequest(
        expected_revision=value.expected_revision,
        outcome=_OUTCOME_TO_PROTO[value.outcome],
    )
    message.identity.CopyFrom(coordinator_identity_to_message(value.identity))
    if value.failure is None:
        message.no_failure = True
    else:
        message.failure = _FAILURE_TO_PROTO[value.failure]
    return message


def record_cleanup_request_to_message(
    value: CoordinatorRecordCleanupRequest,
) -> runtime_transfer_coordinator_pb2.RecordCleanupRequest:
    """Map typed cleanup values to protobuf.

    :param value: typed cleanup transition values
    :returns: protobuf cleanup request
    """
    message = runtime_transfer_coordinator_pb2.RecordCleanupRequest(
        expected_revision=value.expected_revision,
        cleanup_status=_CLEANUP_STATUS_TO_PROTO[value.cleanup_status],
    )
    message.identity.CopyFrom(coordinator_identity_to_message(value.identity))
    return message


def get_transfer_status_request_to_message(
    value: CoordinatorGetTransferStatusRequest,
) -> runtime_transfer_coordinator_pb2.GetTransferStatusRequest:
    """Map typed status values to protobuf.

    :param value: typed status request values
    :returns: protobuf status request
    """
    message = runtime_transfer_coordinator_pb2.GetTransferStatusRequest()
    message.identity.CopyFrom(coordinator_identity_to_message(value.identity))
    return message


def admit_transfer_result_from_message(
    message: Message,
) -> CoordinatorAdmitTransferResult:
    """Map a protobuf admission response to shared values.

    :param message: protobuf admission response
    :returns: typed admission result
    """
    return CoordinatorAdmitTransferResult(
        status=transfer_status_from_message(message.status),
        admitted_object_handle=opaque_object_handle_from_message(
            message.admitted_object_handle
        ),
    )


def get_verified_object_result_from_message(
    message: Message,
) -> CoordinatorGetVerifiedObjectResult:
    """Map a protobuf verified-object response to shared values.

    :param message: protobuf verified-object response
    :returns: typed verified-object result
    """
    return CoordinatorGetVerifiedObjectResult(
        status=transfer_status_from_message(message.status),
        verified_object_handle=opaque_object_handle_from_message(
            message.verified_object_handle
        ),
        actual_manifest=object_manifest_from_message(message.actual_manifest),
    )


def transfer_status_response_from_message(
    message: Message,
) -> CoordinatorTransferStatus:
    """Map a protobuf status response to shared values.

    :param message: protobuf transfer status response
    :returns: typed transfer status
    """
    return transfer_status_from_message(message.status)


def _timestamp_message(value: datetime) -> timestamp_pb2.Timestamp:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Coordinator timestamps must be timezone-aware")
    message = timestamp_pb2.Timestamp()
    message.FromDatetime(value.astimezone(UTC))
    return message


def _datetime_from_message(value: timestamp_pb2.Timestamp) -> datetime:
    return value.ToDatetime(tzinfo=UTC)


_DIRECTION_TO_PROTO = {
    CoordinatorTransferDirection.DOWNLOAD: (
        runtime_transfer_coordinator_pb2.COORDINATOR_TRANSFER_DIRECTION_DOWNLOAD
    ),
    CoordinatorTransferDirection.UPLOAD: (
        runtime_transfer_coordinator_pb2.COORDINATOR_TRANSFER_DIRECTION_UPLOAD
    ),
}
_DIRECTION_FROM_PROTO = {value: key for key, value in _DIRECTION_TO_PROTO.items()}
_PHASE_FROM_PROTO = {
    runtime_transfer_coordinator_pb2.COORDINATOR_TRANSFER_PHASE_PREPARING: (
        CoordinatorTransferPhase.PREPARING
    ),
    runtime_transfer_coordinator_pb2.COORDINATOR_TRANSFER_PHASE_READY: (
        CoordinatorTransferPhase.READY
    ),
    runtime_transfer_coordinator_pb2.COORDINATOR_TRANSFER_PHASE_STREAMING: (
        CoordinatorTransferPhase.STREAMING
    ),
    runtime_transfer_coordinator_pb2.COORDINATOR_TRANSFER_PHASE_VERIFYING: (
        CoordinatorTransferPhase.VERIFYING
    ),
    runtime_transfer_coordinator_pb2.COORDINATOR_TRANSFER_PHASE_AVAILABLE: (
        CoordinatorTransferPhase.AVAILABLE
    ),
    runtime_transfer_coordinator_pb2.COORDINATOR_TRANSFER_PHASE_CONSUMING: (
        CoordinatorTransferPhase.CONSUMING
    ),
    runtime_transfer_coordinator_pb2.COORDINATOR_TRANSFER_PHASE_CONSUMED: (
        CoordinatorTransferPhase.CONSUMED
    ),
    runtime_transfer_coordinator_pb2.COORDINATOR_TRANSFER_PHASE_COMMITTED: (
        CoordinatorTransferPhase.COMMITTED
    ),
    runtime_transfer_coordinator_pb2.COORDINATOR_TRANSFER_PHASE_TERMINAL: (
        CoordinatorTransferPhase.TERMINAL
    ),
}
_OUTCOME_TO_PROTO = {
    CoordinatorTransferOutcome.SUCCEEDED: (
        runtime_transfer_coordinator_pb2.COORDINATOR_TRANSFER_OUTCOME_SUCCEEDED
    ),
    CoordinatorTransferOutcome.FAILED: (
        runtime_transfer_coordinator_pb2.COORDINATOR_TRANSFER_OUTCOME_FAILED
    ),
    CoordinatorTransferOutcome.CANCELLED: (
        runtime_transfer_coordinator_pb2.COORDINATOR_TRANSFER_OUTCOME_CANCELLED
    ),
    CoordinatorTransferOutcome.EXPIRED: (
        runtime_transfer_coordinator_pb2.COORDINATOR_TRANSFER_OUTCOME_EXPIRED
    ),
    CoordinatorTransferOutcome.SUPERSEDED: (
        runtime_transfer_coordinator_pb2.COORDINATOR_TRANSFER_OUTCOME_SUPERSEDED
    ),
}
_OUTCOME_FROM_PROTO = {value: key for key, value in _OUTCOME_TO_PROTO.items()}
_FAILURE_TO_PROTO = {
    CoordinatorTransferFailure.ADMISSION: (
        runtime_transfer_coordinator_pb2.COORDINATOR_TRANSFER_FAILURE_ADMISSION
    ),
    CoordinatorTransferFailure.CANCELLED: (
        runtime_transfer_coordinator_pb2.COORDINATOR_TRANSFER_FAILURE_CANCELLED
    ),
    CoordinatorTransferFailure.EXPIRED: (
        runtime_transfer_coordinator_pb2.COORDINATOR_TRANSFER_FAILURE_EXPIRED
    ),
    CoordinatorTransferFailure.FENCED: (
        runtime_transfer_coordinator_pb2.COORDINATOR_TRANSFER_FAILURE_FENCED
    ),
    CoordinatorTransferFailure.INTEGRITY: (
        runtime_transfer_coordinator_pb2.COORDINATOR_TRANSFER_FAILURE_INTEGRITY
    ),
    CoordinatorTransferFailure.STREAM: (
        runtime_transfer_coordinator_pb2.COORDINATOR_TRANSFER_FAILURE_STREAM
    ),
    CoordinatorTransferFailure.CONSUMER: (
        runtime_transfer_coordinator_pb2.COORDINATOR_TRANSFER_FAILURE_CONSUMER
    ),
}
_FAILURE_FROM_PROTO = {value: key for key, value in _FAILURE_TO_PROTO.items()}
_CLEANUP_STATUS_TO_PROTO = {
    CoordinatorCleanupStatus.NOT_REQUIRED: (
        runtime_transfer_coordinator_pb2.COORDINATOR_CLEANUP_STATUS_NOT_REQUIRED
    ),
    CoordinatorCleanupStatus.PENDING: (
        runtime_transfer_coordinator_pb2.COORDINATOR_CLEANUP_STATUS_PENDING
    ),
    CoordinatorCleanupStatus.COMPLETE: (
        runtime_transfer_coordinator_pb2.COORDINATOR_CLEANUP_STATUS_COMPLETE
    ),
    CoordinatorCleanupStatus.RETRYABLE_FAILURE: (
        runtime_transfer_coordinator_pb2.COORDINATOR_CLEANUP_STATUS_RETRYABLE_FAILURE
    ),
}
_CLEANUP_STATUS_FROM_PROTO = {
    value: key for key, value in _CLEANUP_STATUS_TO_PROTO.items()
}
_CANCELLATION_REASON_TO_PROTO = {
    CoordinatorCancellationReason.CALLER: (
        runtime_transfer_coordinator_pb2.COORDINATOR_CANCELLATION_REASON_CALLER
    ),
    CoordinatorCancellationReason.DEADLINE: (
        runtime_transfer_coordinator_pb2.COORDINATOR_CANCELLATION_REASON_DEADLINE
    ),
    CoordinatorCancellationReason.SUPERSEDED: (
        runtime_transfer_coordinator_pb2.COORDINATOR_CANCELLATION_REASON_SUPERSEDED
    ),
    CoordinatorCancellationReason.SHUTDOWN: (
        runtime_transfer_coordinator_pb2.COORDINATOR_CANCELLATION_REASON_SHUTDOWN
    ),
}
_DISPATCH_STATUS_FROM_PROTO = {
    runtime_transfer_coordinator_pb2.COORDINATOR_DISPATCH_STATUS_NOT_BOUND: (
        CoordinatorDispatchStatus.NOT_BOUND
    ),
    runtime_transfer_coordinator_pb2.COORDINATOR_DISPATCH_STATUS_BOUND: (
        CoordinatorDispatchStatus.BOUND
    ),
    runtime_transfer_coordinator_pb2.COORDINATOR_DISPATCH_STATUS_DELIVERABLE: (
        CoordinatorDispatchStatus.DELIVERABLE
    ),
    runtime_transfer_coordinator_pb2.COORDINATOR_DISPATCH_STATUS_ENQUEUED: (
        CoordinatorDispatchStatus.ENQUEUED
    ),
}
