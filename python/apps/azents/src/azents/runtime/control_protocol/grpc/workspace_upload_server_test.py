"""Workspace upload coordinator gRPC socket-boundary tests."""

from __future__ import annotations

from collections.abc import Awaitable
from typing import NoReturn

import grpc
import pytest
from azents_runtime_control.grpc_workspace_upload_client import (
    WorkspaceUploadCredentialRequestMessage,
)
from azents_runtime_control.proto import (
    runtime_transfer_coordinator_pb2 as pb,
)
from azents_runtime_control.proto import (
    runtime_transfer_coordinator_pb2_grpc as pb_grpc,
)

from azents.runtime.control_protocol.grpc.workspace_upload_server import (
    add_runtime_workspace_upload_coordinator_servicer,
)
from azents.runtime.transfer.workspace_upload import WorkspaceUploadAdmission


class _NoopCredentialAuth:
    """Authenticate test calls without requiring a signed credential."""

    async def authenticate_workspace(
        self,
        context: object,
        *,
        operation: str,
        request: WorkspaceUploadCredentialRequestMessage,
    ) -> object:
        del context, operation, request
        return object()


class _NeverCalledCoordinator:
    """Fail the test if validation allows an invalid request to reach state."""

    async def create(
        self,
        admission: WorkspaceUploadAdmission,
    ) -> NoReturn:
        del admission
        raise AssertionError("invalid request reached WorkspaceUploadCoordinator")

    async def issue_upload_ticket(
        self,
        upload_id: str,
        *,
        requester_user_id: str,
        workspace_id: str,
        agent_id: str,
    ) -> NoReturn:
        del upload_id, requester_user_id, workspace_id, agent_id
        raise AssertionError("invalid request reached WorkspaceUploadCoordinator")

    async def get(
        self,
        upload_id: str,
        *,
        requester_user_id: str,
        workspace_id: str,
        agent_id: str,
    ) -> NoReturn:
        del upload_id, requester_user_id, workspace_id, agent_id
        raise AssertionError("invalid request reached WorkspaceUploadCoordinator")

    async def finalize(
        self,
        upload_id: str,
        *,
        requester_user_id: str,
        workspace_id: str,
        agent_id: str,
        expected_revision: int,
    ) -> NoReturn:
        del (
            upload_id,
            requester_user_id,
            workspace_id,
            agent_id,
            expected_revision,
        )
        raise AssertionError("invalid request reached WorkspaceUploadCoordinator")

    async def cancel(
        self,
        upload_id: str,
        *,
        requester_user_id: str,
        workspace_id: str,
        agent_id: str,
        expected_revision: int,
        current_delivery_number: int | None,
    ) -> NoReturn:
        del (
            upload_id,
            requester_user_id,
            workspace_id,
            agent_id,
            expected_revision,
            current_delivery_number,
        )
        raise AssertionError("invalid request reached WorkspaceUploadCoordinator")

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
    ) -> NoReturn:
        del (
            upload_id,
            requester_user_id,
            workspace_id,
            agent_id,
            expected_revision,
            current_delivery_number,
            overwrite,
            conflict_precondition,
        )
        raise AssertionError("invalid request reached WorkspaceUploadCoordinator")


def _identity() -> pb.WorkspaceUploadIdentity:
    """Return one valid Workspace upload identity."""
    return pb.WorkspaceUploadIdentity(
        upload_id="upload-1",
        requester_user_id="user-1",
        workspace_id="workspace-1",
        agent_id="agent-1",
        runtime_id="runtime-1",
        desired_generation=1,
    )


async def _assert_invalid_argument(
    call: object,
    *,
    expected_detail: str,
) -> None:
    """Assert one socket-boundary RPC returns INVALID_ARGUMENT."""
    if not isinstance(call, Awaitable):
        raise AssertionError("gRPC call did not return an awaitable")
    with pytest.raises(grpc.aio.AioRpcError) as error:
        await call
    assert error.value.code() is grpc.StatusCode.INVALID_ARGUMENT
    assert error.value.details() == expected_detail


@pytest.mark.asyncio
async def test_positive_workspace_upload_preconditions_abort_before_coordination() -> (
    None
):
    """Reject zero revisions and delivery numbers at the gRPC boundary."""
    server = grpc.aio.server()
    add_runtime_workspace_upload_coordinator_servicer(
        server,
        coordinator=_NeverCalledCoordinator(),
        credential_auth=_NoopCredentialAuth(),
    )
    port = server.add_insecure_port("127.0.0.1:0")
    assert port != 0
    await server.start()
    channel = grpc.aio.insecure_channel(f"127.0.0.1:{port}")
    stub = pb_grpc.RuntimeWorkspaceUploadCoordinatorStub(channel)
    identity = _identity()
    try:
        await _assert_invalid_argument(
            stub.IssueWorkspaceUploadTicket(
                pb.IssueWorkspaceUploadTicketRequest(
                    identity=identity,
                    expected_revision=0,
                )
            ),
            expected_detail="expected_revision must be positive",
        )
        await _assert_invalid_argument(
            stub.FinalizeWorkspaceUpload(
                pb.FinalizeWorkspaceUploadRequest(
                    identity=identity,
                    expected_revision=0,
                )
            ),
            expected_detail="expected_revision must be positive",
        )
        await _assert_invalid_argument(
            stub.CancelWorkspaceUpload(
                pb.CancelWorkspaceUploadRequest(
                    identity=identity,
                    expected_revision=0,
                )
            ),
            expected_detail="expected_revision must be positive",
        )
        await _assert_invalid_argument(
            stub.RetryWorkspaceUpload(
                pb.RetryWorkspaceUploadRequest(
                    identity=identity,
                    expected_revision=0,
                    current_delivery_number=1,
                )
            ),
            expected_detail="expected_revision must be positive",
        )
        await _assert_invalid_argument(
            stub.RetryWorkspaceUpload(
                pb.RetryWorkspaceUploadRequest(
                    identity=identity,
                    expected_revision=1,
                    current_delivery_number=0,
                )
            ),
            expected_detail="current_delivery_number must be positive",
        )
    finally:
        await channel.close()
        await server.stop(None)
