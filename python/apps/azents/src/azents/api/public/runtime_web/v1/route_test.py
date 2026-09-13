"""Runtime Web v1 Public API tests."""

import datetime
from unittest.mock import AsyncMock

from azcommon.result import Failure, Success
from fastapi import FastAPI
from fastapi.testclient import TestClient

from azents.api.public.runtime_web.v1 import mount
from azents.core.auth.deps import (
    CurrentUser,
    WorkspaceMember,
    get_current_user,
    get_workspace_member,
)
from azents.core.enums import WorkspaceUserRole
from azents.rdb.models.runtime_web import (
    RuntimeWebRequesterKind,
    RuntimeWebRequestState,
)
from azents.repos.runtime_web.data import RuntimeWebEndpoint, RuntimeWebRequest
from azents.services.runtime_web.data import (
    RuntimeWebConflict,
    RuntimeWebServiceProjection,
)
from azents.services.runtime_web.service import (
    RuntimeWebService,
    get_runtime_web_service,
)
from azents.utils.fastapi.route import as_route_mounter

_NOW = datetime.datetime(2026, 9, 12, 0, 0, tzinfo=datetime.UTC)
_ENDPOINT_ID = "endpoint000000000000000000000000"


def _projection(
    *, url: str | None = "https://service.example.test"
) -> RuntimeWebServiceProjection:
    endpoint = RuntimeWebEndpoint(
        id=_ENDPOINT_ID,
        workspace_id="workspace-1",
        agent_id="agent-1",
        agent_session_id="session-1",
        port=3000,
        hostname_key="host-key",
        label="Preview",
        authority_revision=2,
        close_barrier=0,
        current_pending_request_id="request-1",
        current_cycle_id=None,
        created_at=_NOW,
        updated_at=_NOW,
    )
    request = RuntimeWebRequest(
        id="request-1",
        endpoint_id=endpoint.id,
        requester_kind=RuntimeWebRequesterKind.USER,
        operation_key="operation",
        state=RuntimeWebRequestState.PENDING,
        revision=1,
        requester_user_id="user-1",
        requester_agent_id=None,
        requester_execution_id="auth-session-1",
        requester_call_id=None,
        label_snapshot="Preview",
        decided_by_user_id=None,
        decided_at=None,
        created_at=_NOW,
        updated_at=_NOW,
    )
    return RuntimeWebServiceProjection(
        endpoint=endpoint,
        url=url,
        configuration_state="configured" if url is not None else "unconfigured",
        current_request=request,
        current_cycle=None,
        active=False,
        duration_seconds=7200,
        duration_configuration_revision=4,
        observed_at=_NOW,
    )


def _client(service: RuntimeWebService) -> TestClient:
    app = FastAPI()
    mount(as_route_mounter(app))
    app.dependency_overrides[get_workspace_member] = lambda: WorkspaceMember(
        user_id="user-1",
        workspace_id="workspace-1",
        workspace_user_id="workspace-user-1",
        role=WorkspaceUserRole.MEMBER,
        permissions=set(),
        session_id="auth-session-1",
    )
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        user_id="user-1",
        session_id="auth-session-1",
    )
    app.dependency_overrides[get_runtime_web_service] = lambda: service
    return TestClient(app)


def test_request_route_maps_exact_session_actor_and_projection() -> None:
    """Exposure request maps authenticated identity and returns current state."""
    service = AsyncMock(spec=RuntimeWebService)
    service.request_exposure.return_value = Success(_projection())

    response = _client(service).post(
        "/runtime-web/v1/workspaces/workspace/agents/agent-1/sessions/session-1/"
        "services/3000/requests",
        json={"label": "Preview", "operation_key": "operation-1"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["endpoint"]["url"] == "https://service.example.test"
    assert body["current_request"]["state"] == "pending"
    _, kwargs = service.request_exposure.await_args
    assert kwargs["workspace_id"] == "workspace-1"
    assert kwargs["agent_id"] == "agent-1"
    assert kwargs["session_id"] == "session-1"
    assert kwargs["user_id"] == "user-1"
    assert kwargs["actor"].actor_id == "user-1"
    assert kwargs["actor"].execution_id == "auth-session-1"


def test_request_route_maps_conflict_to_bounded_status() -> None:
    """Revision/configuration conflicts use the stable 409 boundary."""
    service = AsyncMock(spec=RuntimeWebService)
    service.request_exposure.return_value = Failure(RuntimeWebConflict())

    response = _client(service).post(
        "/runtime-web/v1/workspaces/workspace/agents/agent-1/sessions/session-1/"
        "services/3000/requests",
        json={"label": None, "operation_key": "operation-1"},
    )

    assert response.status_code == 409
    assert response.json() == {"detail": {"code": "conflict", "scope": None}}


def test_projection_reports_unconfigured_without_hostname_disclosure() -> None:
    """Phase 1 projection exposes no invented public URL or hostname key."""
    service = AsyncMock(spec=RuntimeWebService)
    service.get_service.return_value = Success(_projection(url=None))

    response = _client(service).get(
        "/runtime-web/v1/workspaces/workspace/agents/agent-1/sessions/session-1/"
        "services/3000"
    )

    assert response.status_code == 200
    endpoint = response.json()["endpoint"]
    assert endpoint["url"] is None
    assert endpoint["configuration_state"] == "unconfigured"
    assert "hostname_key" not in response.text
    _, kwargs = service.get_service.await_args
    assert kwargs["actor"].kind is RuntimeWebRequesterKind.USER


def test_port_path_is_bounded_before_service_dispatch() -> None:
    """Invalid Runtime ports fail as request validation errors."""
    service = AsyncMock(spec=RuntimeWebService)

    response = _client(service).get(
        "/runtime-web/v1/workspaces/workspace/agents/agent-1/sessions/session-1/"
        "services/65536"
    )

    assert response.status_code == 422
    service.get_service.assert_not_awaited()


def test_approve_and_reject_use_authenticated_session_idempotency_scope() -> None:
    """User decisions retain the authenticated Session as execution identity."""
    service = AsyncMock(spec=RuntimeWebService)
    service.approve_request.return_value = Success(_projection())
    service.reject_request.return_value = Success(_projection())
    client = _client(service)

    approved = client.post(
        "/runtime-web/v1/workspaces/workspace/agents/agent-1/sessions/session-1/"
        "requests/request-1/approve",
        json={
            "expected_revision": 1,
            "duration_seconds": 7200,
            "duration_configuration_revision": 4,
            "operation_key": "approve-operation",
        },
    )
    rejected = client.post(
        "/runtime-web/v1/workspaces/workspace/agents/agent-1/sessions/session-1/"
        "requests/request-1/reject",
        json={
            "expected_revision": 1,
            "operation_key": "reject-operation",
        },
    )

    assert approved.status_code == 200
    assert rejected.status_code == 200
    _, approve = service.approve_request.await_args
    _, reject = service.reject_request.await_args
    assert approve["actor"].execution_id == "auth-session-1"
    assert reject["actor"].execution_id == "auth-session-1"


def test_endpoint_id_routes_reauthorize_and_preserve_exact_revision() -> None:
    """Opaque endpoint routes resolve current context before exact mutation."""
    service = AsyncMock(spec=RuntimeWebService)
    service.get_service_by_endpoint_id.return_value = Success(_projection())
    service.approve_request.return_value = Success(_projection())
    client = _client(service)

    projected = client.get(f"/runtime-web/v1/services/{_ENDPOINT_ID}")
    approved = client.post(
        f"/runtime-web/v1/services/{_ENDPOINT_ID}/requests/request-1/approve",
        json={
            "expected_revision": 1,
            "duration_seconds": 7200,
            "duration_configuration_revision": 4,
            "operation_key": "approve-endpoint-operation",
        },
    )

    assert projected.status_code == 200
    assert approved.status_code == 200
    _, projection = service.get_service_by_endpoint_id.await_args_list[0]
    assert projection["endpoint_id"] == _ENDPOINT_ID
    assert projection["user_id"] == "user-1"
    assert projection["actor"].execution_id == "auth-session-1"
    _, approval = service.approve_request.await_args
    assert approval["workspace_id"] == "workspace-1"
    assert approval["agent_id"] == "agent-1"
    assert approval["session_id"] == "session-1"
    assert approval["request_id"] == "request-1"
    assert approval["expected_revision"] == 1
