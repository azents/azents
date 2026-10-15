"""Public Browser REST mounting, closed DTOs and authenticated forwarding."""

from typing import Literal
from unittest.mock import AsyncMock

import pytest
from azents_runtime_control.browser_contract import (
    BrowserFrame,
    BrowserPage,
    BrowserTask,
)
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from azents.api.public.browser.v1 import mount
from azents.core.auth.deps import WorkspaceMember, get_workspace_member
from azents.core.enums import WorkspaceUserRole
from azents.services.runtime_browser.data import (
    RuntimeBrowserCreatedPage,
    RuntimeBrowserOperationError,
    RuntimeBrowserProjection,
    RuntimeBrowserRequestError,
    RuntimeBrowserResource,
)
from azents.services.runtime_browser.deps import get_runtime_browser_service
from azents.services.runtime_browser.service import RuntimeBrowserService
from azents.utils.fastapi.route import as_route_mounter

_PATH = "/browser/v1/workspaces/team/agents/agent-1/sessions/concrete-session"
_PAGE = BrowserPage(
    "page-1",
    "task-1",
    "incarnation-1",
    "https://example.test/",
    "Fixture",
    (BrowserFrame("frame-1", "https://example.test/", "Main"),),
)
_TASK = BrowserTask("task-1", "Research", "task-incarnation", (_PAGE,))


def _app(service: AsyncMock) -> FastAPI:
    app = FastAPI()
    mount(as_route_mounter(app))

    async def member() -> WorkspaceMember:
        return WorkspaceMember(
            "user-a",
            "workspace-1",
            "member-a",
            WorkspaceUserRole.MEMBER,
            set(),
            "auth-a",
        )

    app.dependency_overrides[get_workspace_member] = member
    app.dependency_overrides[get_runtime_browser_service] = lambda: service
    return app


def _service() -> AsyncMock:
    service = AsyncMock(spec=RuntimeBrowserService)
    service.projection.return_value = RuntimeBrowserProjection(
        True, None, True, (_TASK,)
    )
    service.close_page.return_value = RuntimeBrowserProjection(True, None, True, ())
    return service


def test_create_returns_current_projection_and_exact_new_tab() -> None:
    service = _service()
    service.create_page.return_value = RuntimeBrowserCreatedPage(
        RuntimeBrowserProjection(True, None, True, (_TASK,)), _PAGE
    )
    with TestClient(_app(service)) as client:
        result = client.post(_PATH + "/pages", json={})
    assert result.status_code == 200
    assert result.json()["page"]["id"] == _PAGE.id
    assert result.json()["projection"]["tasks"][0]["pages"][0]["id"] == _PAGE.id
    service.create_page.assert_awaited_once_with(
        user_id="user-a",
        authentication_session_id="auth-a",
        resource=RuntimeBrowserResource("team", "agent-1", "concrete-session"),
    )


@pytest.mark.parametrize(
    "body",
    [{"url": "https://example.test"}, {"session_id": "other"}, {"task_id": "task"}],
)
def test_create_body_cannot_override_blank_tab_or_authority(
    body: dict[str, str],
) -> None:
    service = _service()
    with TestClient(_app(service)) as client:
        result = client.post(_PATH + "/pages", json=body)
    assert result.status_code == 422
    service.create_page.assert_not_awaited()


def test_projection_exposes_only_frozen_fields_and_concrete_session() -> None:
    service = _service()
    with TestClient(_app(service)) as client:
        result = client.get(_PATH)
    assert result.status_code == 200
    body = result.json()
    assert set(body) == {"available", "reason_code", "allow_input", "tasks"}
    assert body["tasks"][0]["pages"][0]["title"] == "Fixture"
    assert body["tasks"][0]["pages"][0]["frames"][0]["id"] == "frame-1"
    service.projection.assert_awaited_once_with(
        user_id="user-a",
        authentication_session_id="auth-a",
        resource=RuntimeBrowserResource("team", "agent-1", "concrete-session"),
    )


def test_close_forwards_exact_target_and_returns_current_projection() -> None:
    service = _service()
    with TestClient(_app(service)) as client:
        result = client.post(
            _PATH + "/pages/page-1/close",
            json={
                "task_id": "task-1",
                "resource_incarnation": "incarnation-1",
            },
        )
    assert result.status_code == 200 and result.json()["tasks"] == []
    service.close_page.assert_awaited_once_with(
        user_id="user-a",
        authentication_session_id="auth-a",
        resource=RuntimeBrowserResource("team", "agent-1", "concrete-session"),
        task_id="task-1",
        page_id="page-1",
        resource_incarnation="incarnation-1",
    )


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"task_id": "task-1"},
        {"task_id": "", "resource_incarnation": "incarnation-1"},
        {"task_id": True, "resource_incarnation": "incarnation-1"},
        {
            "task_id": "task-1",
            "resource_incarnation": "incarnation-1",
            "session_id": "other",
        },
        {
            "task_id": "task-1",
            "resource_incarnation": "incarnation-1",
            "frame_id": "other",
        },
        {
            "task_id": "task-1",
            "resource_incarnation": "incarnation-1",
            "working_directory": "/other",
        },
    ],
)
def test_close_body_is_closed_and_cannot_supply_authority_overrides(
    body: dict[str, str | bool],
) -> None:
    service = _service()
    with TestClient(_app(service)) as client:
        result = client.post(_PATH + "/pages/page-1/close", json=body)
    assert result.status_code == 422
    service.close_page.assert_not_awaited()


@pytest.mark.parametrize("status", [401, 403, 404, 409])
@pytest.mark.parametrize("close", [False, True])
def test_domain_access_failures_are_normal_http_errors_without_success_objects(
    status: Literal[401, 403, 404, 409], close: bool
) -> None:
    service = _service()
    service.projection.side_effect = RuntimeBrowserRequestError(status, "Denied")
    service.close_page.side_effect = RuntimeBrowserRequestError(status, "Denied")
    with TestClient(_app(service)) as client:
        result = (
            client.post(
                _PATH + "/pages/page-1/close",
                json={
                    "task_id": "task-1",
                    "resource_incarnation": "incarnation-1",
                },
            )
            if close
            else client.get(_PATH)
        )
    assert result.status_code == status and result.json() == {"detail": "Denied"}
    if status == 401:
        assert result.headers["www-authenticate"] == "Bearer"


def test_actual_command_failure_remains_failure_not_hidden_unavailable_success() -> (
    None
):
    service = _service()
    service.projection.side_effect = RuntimeBrowserOperationError("Command failed")
    with TestClient(_app(service), raise_server_exceptions=False) as client:
        result = client.get(_PATH)
    assert result.status_code == 500
    assert "tasks" not in result.text


def test_member_auth_dependency_rejection_runs_before_browser_service() -> None:
    service = _service()
    app = _app(service)

    async def denied_member() -> WorkspaceMember:
        raise HTTPException(status_code=401, detail="Not authenticated")

    app.dependency_overrides[get_workspace_member] = denied_member
    with TestClient(app) as client:
        result = client.get(_PATH)
    assert result.status_code == 401
    service.projection.assert_not_awaited()


def test_openapi_has_typed_projection_create_close_operations() -> None:
    schema = _app(_service()).openapi()
    paths = schema["paths"]
    assert len(paths) == 3
    projection = paths[
        _PATH.replace("team", "{handle}")
        .replace("agent-1", "{agent_id}")
        .replace("concrete-session", "{session_id}")
    ]
    assert projection["get"]["operationId"] == "browser_v1_get_browser_projection"
    close = next(path for path in paths if path.endswith("/close"))
    assert paths[close]["post"]["operationId"] == "browser_v1_close_browser_page"
    create = next(path for path in paths if path.endswith("/pages"))
    assert paths[create]["post"]["operationId"] == "browser_v1_create_browser_page"
    assert not {"ws", "ticket", "open"} & {path.rsplit("/", 1)[-1] for path in paths}
    properties = schema["components"]["schemas"]["BrowserProjectionResponse"][
        "properties"
    ]
    assert set(properties) == {"available", "reason_code", "allow_input", "tasks"}
