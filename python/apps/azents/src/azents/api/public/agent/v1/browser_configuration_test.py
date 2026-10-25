"""Closed browser settings HTTP payloads and permission/conflict propagation."""

from unittest.mock import AsyncMock

import pytest
from azcommon.result import Failure, Success
from azents_runtime_control.browser_configuration import BrowserImplementation
from fastapi import FastAPI
from fastapi.testclient import TestClient

from azents.api.public.agent.v1.browser_configuration import router
from azents.core.auth.deps import WorkspaceMember, get_workspace_member
from azents.core.browser_configuration import (
    AgentBrowserConfiguration,
    BrowserConfigurationDenial,
)
from azents.core.enums import WorkspaceUserRole
from azents.services.browser_configuration import AgentBrowserConfigurationService

PATH = "/workspaces/team/agents/agent/browser-configuration"
INTENT = "a" * 32


def app(service: AsyncMock) -> FastAPI:
    application = FastAPI()
    application.include_router(router)

    async def member() -> WorkspaceMember:
        return WorkspaceMember(
            "user",
            "workspace",
            "member",
            WorkspaceUserRole.MEMBER,
            set(),
            "authentication",
        )

    application.dependency_overrides[get_workspace_member] = member
    application.dependency_overrides[AgentBrowserConfigurationService] = lambda: service
    return application


def service() -> AsyncMock:
    configured = AgentBrowserConfiguration(
        agent_id="agent",
        intent_id=INTENT,
        requested=BrowserImplementation.CAMOUFOX,
        applied=None,
        state="offline",
        reason_code=None,
        runtime_id=None,
        runner_generation=None,
    )
    mock = AsyncMock(spec=AgentBrowserConfigurationService)
    mock.read.return_value = Success(configured)
    mock.replace.return_value = Success(configured)
    return mock


def test_save_forwards_exact_identity_choice_and_explicit_retry() -> None:
    mock = service()
    with TestClient(app(mock)) as client:
        response = client.put(
            PATH,
            json={
                "expected_intent_id": INTENT,
                "implementation": "camoufox",
                "retry": False,
            },
        )
    assert response.status_code == 200 and response.json()["state"] == "offline"
    mock.replace.assert_awaited_once_with(
        agent_id="agent",
        workspace_id="workspace",
        workspace_user_id="member",
        expected_intent_id=INTENT,
        implementation=BrowserImplementation.CAMOUFOX,
        retry=False,
    )


@pytest.mark.parametrize(
    "body",
    [
        {"implementation": "camoufox", "retry": False},
        {
            "expected_intent_id": INTENT,
            "implementation": "arbitrary-browser",
            "retry": False,
        },
        {
            "expected_intent_id": INTENT,
            "implementation": "camoufox",
            "retry": False,
            "executable": "/tmp/browser",
        },
        {
            "expected_intent_id": INTENT,
            "implementation": "camoufox",
            "retry": False,
            "profile": "/tmp/profile",
        },
    ],
)
def test_payload_cannot_omit_fence_or_override_packaged_assets(
    body: dict[str, object],
) -> None:
    mock = service()
    with TestClient(app(mock)) as client:
        response = client.put(PATH, json=body)
    assert response.status_code == 422
    mock.replace.assert_not_awaited()


@pytest.mark.parametrize(
    "denial,status",
    [
        (BrowserConfigurationDenial.ADMIN_REQUIRED, 403),
        (BrowserConfigurationDenial.NOT_FOUND, 404),
        (BrowserConfigurationDenial.STALE_INTENT, 409),
        (BrowserConfigurationDenial.AGENT_INACTIVE, 409),
    ],
)
def test_save_permissions_and_stale_intents_are_not_success(
    denial: BrowserConfigurationDenial, status: int
) -> None:
    mock = service()
    mock.replace.return_value = Failure(denial)
    with TestClient(app(mock)) as client:
        response = client.put(
            PATH,
            json={
                "expected_intent_id": INTENT,
                "implementation": "camoufox",
                "retry": True,
            },
        )
    assert response.status_code == status


def test_read_returns_requested_and_applied_without_allocating_runtime() -> None:
    mock = service()
    with TestClient(app(mock)) as client:
        response = client.get(PATH)
    assert response.status_code == 200
    assert (
        response.json()["requested"] == "camoufox"
        and response.json()["applied"] is None
    )
    mock.replace.assert_not_awaited()
