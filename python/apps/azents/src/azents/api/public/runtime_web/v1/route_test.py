"""Runtime Web v1 Agent service API tests."""

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
from azents.rdb.models.runtime_web import RuntimeWebActorKind
from azents.services.runtime_web.data import (
    RuntimeWebConflict,
    RuntimeWebServicePage,
    RuntimeWebServiceProjection,
)
from azents.services.runtime_web.service import (
    RuntimeWebService,
    get_runtime_web_service,
)
from azents.utils.fastapi.route import as_route_mounter

_NOW = datetime.datetime(2026, 9, 15, 0, 0, tzinfo=datetime.UTC)
_SERVICE_ID = "s" * 32


def _projection(
    *,
    url: str | None = "https://service.example.test",
    on: bool = False,
) -> RuntimeWebServiceProjection:
    return RuntimeWebServiceProjection(
        id=_SERVICE_ID,
        port=3000,
        label="Preview",
        url=url,
        configuration_state="configured" if url is not None else "unconfigured",
        on=on,
        selected_duration_seconds=3_600,
        expires_at=_NOW + datetime.timedelta(hours=1) if on else None,
        revision=2,
        created_at=_NOW,
        updated_at=_NOW,
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


def test_create_and_list_routes_use_agent_scope_without_session_identity() -> None:
    service = AsyncMock(spec=RuntimeWebService)
    service.create_service.return_value = Success(_projection())
    service.list_services.return_value = Success(
        RuntimeWebServicePage(items=[_projection()], total_count=1)
    )
    client = _client(service)

    created = client.post(
        "/runtime-web/v1/workspaces/workspace/agents/agent-1/services",
        json={
            "port": 3000,
            "label": "Preview",
            "selected_duration_seconds": 3600,
            "turn_on": False,
            "operation_key": "create-operation",
        },
    )
    listed = client.get("/runtime-web/v1/workspaces/workspace/agents/agent-1/services")

    assert created.status_code == 200
    assert created.json()["id"] == _SERVICE_ID
    assert created.json()["on"] is False
    assert listed.status_code == 200
    assert listed.json()["total_count"] == 1
    _, create_kwargs = service.create_service.await_args
    assert create_kwargs["workspace_id"] == "workspace-1"
    assert create_kwargs["agent_id"] == "agent-1"
    assert create_kwargs["actor"].kind is RuntimeWebActorKind.USER
    _, list_kwargs = service.list_services.await_args
    assert list_kwargs["workspace_user_id"] == "workspace-user-1"


def test_update_on_off_reset_and_delete_preserve_exact_revision() -> None:
    service = AsyncMock(spec=RuntimeWebService)
    service.update_service.return_value = Success(_projection())
    service.turn_on.return_value = Success(_projection(on=True))
    service.turn_off.return_value = Success(_projection())
    service.reset_expiration.return_value = Success(_projection(on=True))
    service.delete_service.return_value = Success(True)
    client = _client(service)
    base = f"/runtime-web/v1/workspaces/workspace/agents/agent-1/services/{_SERVICE_ID}"

    assert (
        client.patch(
            base,
            json={
                "expected_revision": 2,
                "label": None,
                "operation_key": "update-operation",
            },
        ).status_code
        == 200
    )
    assert (
        client.post(
            f"{base}/on",
            json={
                "expected_revision": 2,
                "selected_duration_seconds": 21600,
                "operation_key": "on-operation",
            },
        ).status_code
        == 200
    )
    assert (
        client.post(
            f"{base}/off",
            json={"expected_revision": 3, "operation_key": "off-operation"},
        ).status_code
        == 200
    )
    assert (
        client.post(
            f"{base}/reset",
            json={"expected_revision": 4, "operation_key": "reset-operation"},
        ).status_code
        == 200
    )
    assert client.request(
        "DELETE",
        base,
        json={"expected_revision": 5, "operation_key": "delete-operation"},
    ).json() == {"deleted": True}

    _, update = service.update_service.await_args
    assert update["label_present"] is True
    assert update["label"] is None
    _, turn_on = service.turn_on.await_args
    assert turn_on["expected_revision"] == 2
    assert turn_on["selected_duration_seconds"] == 21_600
    _, deleted = service.delete_service.await_args
    assert deleted["service_id"] == _SERVICE_ID
    assert deleted["expected_revision"] == 5


def test_trusted_service_id_routes_reauthorize_current_user() -> None:
    service = AsyncMock(spec=RuntimeWebService)
    service.get_service_by_id_for_user.return_value = Success(_projection())
    service.turn_on_by_id_for_user.return_value = Success(_projection(on=True))
    client = _client(service)

    projected = client.get(f"/runtime-web/v1/services/{_SERVICE_ID}")
    activated = client.post(
        f"/runtime-web/v1/services/{_SERVICE_ID}/on",
        json={
            "expected_revision": 2,
            "selected_duration_seconds": 86400,
            "operation_key": "activate-operation",
        },
    )

    assert projected.status_code == 200
    assert activated.status_code == 200
    _, get_kwargs = service.get_service_by_id_for_user.await_args
    assert get_kwargs == {"service_id": _SERVICE_ID, "user_id": "user-1"}
    _, on_kwargs = service.turn_on_by_id_for_user.await_args
    assert on_kwargs["service_id"] == _SERVICE_ID
    assert on_kwargs["user_id"] == "user-1"
    assert on_kwargs["actor"].execution_id == "auth-session-1"


def test_conflict_and_invalid_duration_use_bounded_public_errors() -> None:
    service = AsyncMock(spec=RuntimeWebService)
    service.create_service.return_value = Failure(RuntimeWebConflict())
    client = _client(service)

    conflict = client.post(
        "/runtime-web/v1/workspaces/workspace/agents/agent-1/services",
        json={
            "port": 3000,
            "label": None,
            "selected_duration_seconds": 3600,
            "turn_on": False,
            "operation_key": "create-operation",
        },
    )
    invalid = client.post(
        "/runtime-web/v1/workspaces/workspace/agents/agent-1/services",
        json={
            "port": 3000,
            "label": None,
            "selected_duration_seconds": 7200,
            "turn_on": False,
            "operation_key": "invalid-operation",
        },
    )

    assert conflict.status_code == 409
    assert conflict.json() == {"detail": {"code": "conflict", "scope": None}}
    assert invalid.status_code == 422
