"""Existing Toolkit deletion sequences required user-token cleanup first."""

import datetime
from unittest.mock import create_autospec

import pytest
from azcommon.result import Success
from fastapi import FastAPI
from fastapi.testclient import TestClient

from azents.api.public.toolkit.v1 import router
from azents.core.auth.deps import WorkspaceMember, get_workspace_member
from azents.core.auth.roles import get_permissions_for_role
from azents.core.enums import WorkspaceUserRole
from azents.core.github_user_oauth import (
    GitHubUserErrorCode,
    GitHubUserOAuthError,
    GitHubUserRequester,
)
from azents.services.github_user_oauth.service import GitHubUserOAuthService
from azents.services.toolkit import ToolkitService
from azents.services.toolkit.data import ToolkitOutput


def _member() -> WorkspaceMember:
    return WorkspaceMember(
        user_id="manager",
        session_id="login",
        workspace_id="workspace",
        workspace_user_id="membership",
        role=WorkspaceUserRole.OWNER,
        permissions=get_permissions_for_role(WorkspaceUserRole.OWNER),
    )


def _toolkit(agent_id: str | None, auth_type: str) -> ToolkitOutput:
    now = datetime.datetime.now(datetime.UTC)
    return ToolkitOutput(
        id="toolkit",
        workspace_id="workspace",
        owner_agent_id=agent_id,
        toolkit_type="github",
        slug="github",
        name="GitHub",
        config={"github_auth_type": auth_type},
        credentials=None,
        enabled=True,
        always_expose_tools=False,
        revision=1,
        created_at=now,
        updated_at=now,
    )


@pytest.mark.parametrize("agent_id", [None, "owning-agent"])
@pytest.mark.parametrize("cleanup_fails", [False, True])
def test_toolkit_delete_never_precedes_user_token_cleanup(
    agent_id: str | None, cleanup_fails: bool
) -> None:
    toolkit_service = create_autospec(ToolkitService, instance=True)
    user_service = create_autospec(GitHubUserOAuthService, instance=True)
    toolkit_service.get_by_id.return_value = Success(
        _toolkit(agent_id, "github_app_user")
    )
    toolkit_service.get_agent_owned.return_value = Success(
        _toolkit(agent_id, "github_app_user")
    )
    toolkit_service.delete_by_id.return_value = Success(None)
    toolkit_service.delete_agent_owned.return_value = Success(None)
    events: list[str] = []

    async def cleanup(requester: GitHubUserRequester) -> None:
        assert requester.agent_id == agent_id
        assert requester.toolkit_id == "toolkit"
        assert requester.session_id == "login"
        events.append("revoke")
        if cleanup_fails:
            raise GitHubUserOAuthError(
                GitHubUserErrorCode.CLEANUP_REQUIRED,
                "GitHub token cleanup is incomplete. Retry cleanup.",
            )

    async def delete(*args: object, **kwargs: object) -> Success[None]:
        events.append("delete")
        return Success(None)

    user_service.disconnect.side_effect = cleanup
    toolkit_service.delete_by_id.side_effect = delete
    toolkit_service.delete_agent_owned.side_effect = delete
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_workspace_member] = _member
    app.dependency_overrides[ToolkitService] = lambda: toolkit_service
    app.dependency_overrides[GitHubUserOAuthService] = lambda: user_service
    path = "/workspaces/ws"
    if agent_id is not None:
        path += f"/agents/{agent_id}"
    with TestClient(app) as client:
        response = client.delete(path + "/toolkit-configs/toolkit")
    assert response.status_code == (409 if cleanup_fails else 204)
    assert events == (["revoke"] if cleanup_fails else ["revoke", "delete"])


def test_existing_pat_delete_does_not_use_user_oauth_cleanup() -> None:
    toolkit_service = create_autospec(ToolkitService, instance=True)
    user_service = create_autospec(GitHubUserOAuthService, instance=True)
    toolkit_service.get_by_id.return_value = Success(_toolkit(None, "pat"))
    toolkit_service.delete_by_id.return_value = Success(None)
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_workspace_member] = _member
    app.dependency_overrides[ToolkitService] = lambda: toolkit_service
    app.dependency_overrides[GitHubUserOAuthService] = lambda: user_service
    with TestClient(app) as client:
        response = client.delete("/workspaces/ws/toolkit-configs/toolkit")
    assert response.status_code == 204
    user_service.disconnect.assert_not_awaited()
