"""Runtime Control gRPC metadata authentication tests."""

# Protobuf generated modules expose dynamic message attributes.

import dataclasses
from datetime import UTC, datetime, timedelta
from typing import NoReturn

import grpc
import pytest
from azents_runtime_control.grpc_transfer_coordinator_client import (
    COORDINATOR_OPERATION_DISPATCH_TRANSFER,
    coordinator_credential_request,
    coordinator_identity_to_message,
)
from azents_runtime_control.proto import runtime_transfer_coordinator_pb2
from azents_runtime_control.transfer import CoordinatorTransferIdentity
from cryptography.fernet import Fernet

from azents.core.runtime_runner_credential import RuntimeRunnerCredentialVerifier
from azents.core.runtime_transfer_coordinator_credential import (
    RuntimeTransferCoordinatorCredentialVerifier,
    new_coordinator_claims,
)
from azents.runtime.control_protocol.grpc.auth import (
    RuntimeTransferCoordinatorCredentialGrpcAuth,
)

_NOW = datetime(2026, 7, 25, 12, 0, tzinfo=UTC)


class GrpcAbort(RuntimeError):
    """Test representation of a gRPC abort."""


@dataclasses.dataclass(frozen=True)
class FakeGrpcContext:
    """Minimal coordinator RPC context for metadata tests."""

    metadata: tuple[tuple[str, str], ...]

    def invocation_metadata(self) -> tuple[tuple[str, str], ...]:
        """Return configured invocation metadata.

        :returns: metadata visible to the RPC
        """
        return self.metadata

    async def abort(
        self,
        code: grpc.StatusCode,
        details: str,
    ) -> NoReturn:
        """Abort the test RPC.

        :param code: gRPC status code
        :param details: gRPC status detail
        :raises GrpcAbort: always
        """
        raise GrpcAbort(f"{code.name}: {details}")


@pytest.mark.asyncio
async def test_coordinator_auth_verifies_exact_request_metadata() -> None:
    verifier = _verifier()
    request = _request(dispatch_id="dispatch-1")
    token = _issue(verifier, request)
    auth = RuntimeTransferCoordinatorCredentialGrpcAuth(verifier)

    claims = await auth.authenticate(
        FakeGrpcContext(metadata=(("authorization", f"Bearer {token}"),)),
        operation=COORDINATOR_OPERATION_DISPATCH_TRANSFER,
        request=request,
    )

    assert claims.service_identity == "azents-api"
    assert claims.identity == _identity()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "metadata",
    [
        (),
        (
            ("authorization", "Bearer token-1"),
            ("authorization", "Bearer token-2"),
        ),
        (("authorization", "Basic coordinator-token"),),
    ],
)
async def test_coordinator_auth_requires_exactly_one_bearer(
    metadata: tuple[tuple[str, str], ...],
) -> None:
    auth = RuntimeTransferCoordinatorCredentialGrpcAuth(_verifier())

    with pytest.raises(GrpcAbort, match="UNAUTHENTICATED"):
        await auth.authenticate(
            FakeGrpcContext(metadata=metadata),
            operation=COORDINATOR_OPERATION_DISPATCH_TRANSFER,
            request=_request(dispatch_id="dispatch-1"),
        )


@pytest.mark.asyncio
async def test_coordinator_auth_rejects_request_or_operation_mismatch() -> None:
    verifier = _verifier()
    token = _issue(verifier, _request(dispatch_id="dispatch-1"))
    auth = RuntimeTransferCoordinatorCredentialGrpcAuth(verifier)

    with pytest.raises(GrpcAbort, match="UNAUTHENTICATED"):
        await auth.authenticate(
            FakeGrpcContext(metadata=(("authorization", f"Bearer {token}"),)),
            operation=COORDINATOR_OPERATION_DISPATCH_TRANSFER,
            request=_request(dispatch_id="dispatch-2"),
        )
    with pytest.raises(GrpcAbort, match="UNAUTHENTICATED"):
        await auth.authenticate(
            FakeGrpcContext(metadata=(("authorization", f"Bearer {token}"),)),
            operation="RuntimeTransferCoordinator/CancelTransfer",
            request=_request(dispatch_id="dispatch-1"),
        )


@pytest.mark.asyncio
async def test_coordinator_auth_rejects_runner_credential() -> None:
    root = Fernet.generate_key().decode()
    verifier = _verifier(root)
    runner_token = (
        RuntimeRunnerCredentialVerifier(root)
        .issue(
            runtime_id="runtime-1",
            desired_generation=2,
        )
        .token
    )
    auth = RuntimeTransferCoordinatorCredentialGrpcAuth(verifier)

    with pytest.raises(GrpcAbort, match="UNAUTHENTICATED"):
        await auth.authenticate(
            FakeGrpcContext(metadata=(("authorization", f"Bearer {runner_token}"),)),
            operation=COORDINATOR_OPERATION_DISPATCH_TRANSFER,
            request=_request(dispatch_id="dispatch-1"),
        )


def _verifier(
    root: str | None = None,
) -> RuntimeTransferCoordinatorCredentialVerifier:
    return RuntimeTransferCoordinatorCredentialVerifier(
        root or Fernet.generate_key().decode(),
        clock=lambda: _NOW,
    )


def _issue(
    verifier: RuntimeTransferCoordinatorCredentialVerifier,
    request: runtime_transfer_coordinator_pb2.DispatchTransferRequest,
) -> str:
    credential_request = coordinator_credential_request(
        COORDINATOR_OPERATION_DISPATCH_TRANSFER,
        request,
    )
    return verifier.issue(
        new_coordinator_claims(
            service_identity="azents-api",
            operation=credential_request.operation,
            identity=credential_request.identity,
            request_sha256=credential_request.request_sha256,
            issued_at=_NOW,
            not_before=_NOW,
            expires_at=_NOW + timedelta(seconds=30),
            nonce="nonce-1",
        )
    )


def _request(
    *,
    dispatch_id: str,
) -> runtime_transfer_coordinator_pb2.DispatchTransferRequest:
    request = runtime_transfer_coordinator_pb2.DispatchTransferRequest(
        expected_revision=7,
        dispatch_id=dispatch_id,
    )
    request.identity.CopyFrom(coordinator_identity_to_message(_identity()))
    return request


def _identity() -> CoordinatorTransferIdentity:
    return CoordinatorTransferIdentity(
        transfer_id="transfer-1",
        attempt_id="attempt-1",
        runtime_id="runtime-1",
        desired_generation=2,
        direction="download",
        operation_id="operation-1",
        session_id="session-1",
        agent_id="agent-1",
    )
