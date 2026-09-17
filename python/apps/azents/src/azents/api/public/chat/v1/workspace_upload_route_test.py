"""Public Workspace upload route and contract tests."""

from __future__ import annotations

import datetime
import json
from unittest.mock import AsyncMock, Mock

import pytest
from azcommon.result import Success
from azents_runtime_control.grpc_workspace_upload_client import (
    WorkspaceUploadDestinationEvidence,
    WorkspaceUploadFailure,
    WorkspaceUploadIdentity,
    WorkspaceUploadPhase,
    WorkspaceUploadStatus,
    WorkspaceUploadTicket,
)
from fastapi import HTTPException
from fastapi.openapi.utils import get_openapi

from azents.api.public.chat.v1 import (
    _raise_workspace_upload_error,
    cancel_agent_workspace_upload,
    create_agent_workspace_upload,
    finalize_agent_workspace_upload,
    get_agent_workspace_upload,
    retry_agent_workspace_upload,
    router,
)
from azents.api.public.chat.v1.data import (
    WorkspaceUploadCancelRequest,
    WorkspaceUploadCreateRequest,
    WorkspaceUploadFinalizeRequest,
    WorkspaceUploadRetryRequest,
    WorkspaceUploadStatusResponse,
)
from azents.core.auth.deps import CurrentUser
from azents.services.chat.workspace_upload import (
    WorkspaceUploadAccessDenied,
    WorkspaceUploadAdmissionRejected,
    WorkspaceUploadAgentNotFound,
    WorkspaceUploadCoordinatorUnavailable,
    WorkspaceUploadCreateOutput,
    WorkspaceUploadDestinationInvalid,
    WorkspaceUploadError,
    WorkspaceUploadInvalidRequest,
    WorkspaceUploadNotFound,
    WorkspaceUploadPathUnavailable,
    WorkspaceUploadRevisionConflict,
    WorkspaceUploadRuntimeUnavailable,
    WorkspaceUploadService,
)

_AGENT_ID = "0123456789abcdef0123456789abcdef"
_UPLOAD_ID = "abcdefabcdefabcdefabcdefabcdefab"
_USER_ID = "user-1"
_NOW = datetime.datetime(2026, 9, 17, tzinfo=datetime.UTC)
_DIGEST = "a" * 64


def _status() -> WorkspaceUploadStatus:
    """Build one status with bounded conflict evidence."""
    return WorkspaceUploadStatus(
        identity=WorkspaceUploadIdentity(
            upload_id=_UPLOAD_ID,
            requester_user_id=_USER_ID,
            workspace_id="workspace-1",
            agent_id=_AGENT_ID,
            runtime_id="runtime-1",
            desired_generation=1,
            session_id=None,
        ),
        revision=4,
        destination_directory="/runtime/home/reports",
        filename="report.txt",
        destination_path="/runtime/home/reports/report.txt",
        expected_size=12,
        received_size=12,
        actual_size=12,
        sha256=_DIGEST,
        media_type="text/plain",
        phase=WorkspaceUploadPhase.CONFLICTED,
        current_delivery_number=1,
        outcome=None,
        failure=WorkspaceUploadFailure.DESTINATION_CONFLICT,
        retry_available=True,
        cancel_available=True,
        overwrite_available=True,
        destination_evidence=WorkspaceUploadDestinationEvidence(
            kind="file",
            size=10,
            modified_at=_NOW,
            conflict_precondition=b"\x01\x02",
        ),
    )


def _ticket() -> WorkspaceUploadTicket:
    """Build one transient direct PUT ticket."""
    return WorkspaceUploadTicket(
        method="PUT",
        url="https://objects.example/upload?signature=secret",
        expires_at=_NOW + datetime.timedelta(minutes=10),
        headers=(("content-type", "text/plain"),),
    )


def _current_user() -> CurrentUser:
    """Build the authenticated requester fixture."""
    return CurrentUser(user_id=_USER_ID, session_id="auth-session")


def test_workspace_upload_routes_are_json_only() -> None:
    """Workspace upload routes expose JSON control and no binary body path."""
    openapi = get_openapi(
        title="test",
        version="1",
        routes=router.routes,
    )
    paths = {
        path: path_data
        for path, path_data in openapi["paths"].items()
        if "/workspace/uploads" in path
    }
    assert set(paths) == {
        "/agents/{agent_id}/workspace/uploads",
        "/agents/{agent_id}/workspace/uploads/{upload_id}",
        "/agents/{agent_id}/workspace/uploads/{upload_id}/finalize",
        "/agents/{agent_id}/workspace/uploads/{upload_id}/cancel",
        "/agents/{agent_id}/workspace/uploads/{upload_id}/retry",
    }
    for path_data in paths.values():
        assert "multipart/form-data" not in json.dumps(path_data)
        assert "application/octet-stream" not in json.dumps(path_data)
        if "post" in path_data:
            assert "application/json" in path_data["post"]["requestBody"]["content"]


@pytest.mark.asyncio
async def test_create_route_returns_status_and_transient_ticket() -> None:
    """Create route returns the status and direct PUT capability separately."""
    service = Mock(spec=WorkspaceUploadService)
    service.create = AsyncMock(
        return_value=Success(
            WorkspaceUploadCreateOutput(status=_status(), ticket=_ticket())
        )
    )
    request = WorkspaceUploadCreateRequest(
        destination_directory="/runtime/home/reports",
        filename="report.txt",
        expected_size=12,
        expected_sha256=_DIGEST,
        media_type="text/plain",
        session_id=None,
    )

    response = await create_agent_workspace_upload(
        agent_id=_AGENT_ID,
        request=request,
        current_user=_current_user(),
        workspace_upload_service=service,
    )

    assert response.status.identity.upload_id == _UPLOAD_ID
    assert response.ticket.method == "PUT"
    assert response.ticket.url.endswith("signature=secret")
    assert response.status.destination_evidence is not None
    assert response.status.destination_evidence.conflict_precondition == "AQI"
    service.create.assert_awaited_once_with(
        agent_id=_AGENT_ID,
        user_id=_USER_ID,
        destination_directory="/runtime/home/reports",
        filename="report.txt",
        expected_size=12,
        expected_sha256=_DIGEST,
        media_type="text/plain",
        session_id=None,
    )


@pytest.mark.asyncio
async def test_get_route_forwards_requester_scope() -> None:
    """Status route forwards the authenticated requester and upload identity."""
    service = Mock(spec=WorkspaceUploadService)
    service.get = AsyncMock(return_value=Success(_status()))

    response = await get_agent_workspace_upload(
        agent_id=_AGENT_ID,
        upload_id=_UPLOAD_ID,
        current_user=_current_user(),
        workspace_upload_service=service,
    )

    assert response.identity.upload_id == _UPLOAD_ID
    service.get.assert_awaited_once_with(
        agent_id=_AGENT_ID,
        user_id=_USER_ID,
        upload_id=_UPLOAD_ID,
    )


@pytest.mark.asyncio
async def test_finalize_route_forwards_revision() -> None:
    """Finalize route keeps the caller's exact revision precondition."""
    service = Mock(spec=WorkspaceUploadService)
    service.finalize = AsyncMock(return_value=Success(_status()))

    await finalize_agent_workspace_upload(
        agent_id=_AGENT_ID,
        upload_id=_UPLOAD_ID,
        request=WorkspaceUploadFinalizeRequest(expected_revision=4),
        current_user=_current_user(),
        workspace_upload_service=service,
    )

    service.finalize.assert_awaited_once_with(
        agent_id=_AGENT_ID,
        user_id=_USER_ID,
        upload_id=_UPLOAD_ID,
        expected_revision=4,
    )


@pytest.mark.asyncio
async def test_cancel_route_forwards_optional_delivery_number() -> None:
    """Cancel route preserves an optional exact delivery attempt number."""
    service = Mock(spec=WorkspaceUploadService)
    service.cancel = AsyncMock(return_value=Success(_status()))

    await cancel_agent_workspace_upload(
        agent_id=_AGENT_ID,
        upload_id=_UPLOAD_ID,
        request=WorkspaceUploadCancelRequest(
            expected_revision=4,
            current_delivery_number=1,
        ),
        current_user=_current_user(),
        workspace_upload_service=service,
    )

    service.cancel.assert_awaited_once_with(
        agent_id=_AGENT_ID,
        user_id=_USER_ID,
        upload_id=_UPLOAD_ID,
        expected_revision=4,
        current_delivery_number=1,
    )


@pytest.mark.asyncio
async def test_retry_route_forwards_explicit_overwrite_fence() -> None:
    """Retry route preserves explicit overwrite and opaque conflict fencing."""
    service = Mock(spec=WorkspaceUploadService)
    service.retry = AsyncMock(return_value=Success(_status()))

    await retry_agent_workspace_upload(
        agent_id=_AGENT_ID,
        upload_id=_UPLOAD_ID,
        request=WorkspaceUploadRetryRequest(
            expected_revision=4,
            current_delivery_number=1,
            overwrite=True,
            conflict_precondition="AQI",
        ),
        current_user=_current_user(),
        workspace_upload_service=service,
    )

    service.retry.assert_awaited_once_with(
        agent_id=_AGENT_ID,
        user_id=_USER_ID,
        upload_id=_UPLOAD_ID,
        expected_revision=4,
        current_delivery_number=1,
        overwrite=True,
        conflict_precondition="AQI",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "status_code"),
    [
        (WorkspaceUploadAgentNotFound(agent_id=_AGENT_ID), 404),
        (WorkspaceUploadAccessDenied(agent_id=_AGENT_ID), 403),
        (WorkspaceUploadRuntimeUnavailable(detail="Runtime is not ready."), 409),
        (WorkspaceUploadPathUnavailable(), 409),
        (WorkspaceUploadInvalidRequest(detail="invalid request"), 400),
        (WorkspaceUploadDestinationInvalid(detail="invalid destination"), 400),
        (WorkspaceUploadCoordinatorUnavailable(), 409),
        (WorkspaceUploadNotFound(), 404),
        (WorkspaceUploadRevisionConflict(detail="stale revision"), 409),
        (WorkspaceUploadAdmissionRejected(detail="too many uploads"), 429),
    ],
)
async def test_workspace_upload_error_mapping(
    error: WorkspaceUploadError,
    status_code: int,
) -> None:
    """Expected service failures map to stable client-actionable statuses."""
    with pytest.raises(HTTPException) as raised:
        _raise_workspace_upload_error(error)

    assert raised.value.status_code == status_code


def test_status_projection_contains_no_storage_ticket() -> None:
    """Public status keeps conflict evidence but never includes a ticket URL."""
    payload = WorkspaceUploadStatusResponse.from_domain(_status()).model_dump(
        mode="json"
    )
    serialized = json.dumps(payload)
    assert "signature=secret" not in serialized
    assert "url" not in payload
    assert payload["destination_evidence"]["conflict_precondition"] == "AQI"
