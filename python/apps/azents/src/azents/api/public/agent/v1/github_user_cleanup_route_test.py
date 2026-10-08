"""Agent deletion exposes actionable GitHub user-token cleanup conflicts."""

from unittest.mock import AsyncMock

import pytest
from azcommon.result import Failure
from fastapi import FastAPI
from fastapi.testclient import TestClient

from azents.api.public.agent.v1 import router
from azents.core.auth.deps import WorkspaceMember, get_workspace_member
from azents.core.enums import WorkspaceUserRole
from azents.core.github_user_oauth import GitHubUserErrorCode, GitHubUserOAuthError
from azents.services.agent import AgentService
from azents.services.agent.data import NotAdmin, UnlimitedRetention

_ROUTE_APP = FastAPI()
_ROUTE_APP.include_router(router, prefix="/agent/v1")


@pytest.fixture(autouse=True)
def _reset_dependencies() -> None:
    _ROUTE_APP.dependency_overrides.clear()


def _client(service: AsyncMock) -> TestClient:
    _ROUTE_APP.dependency_overrides[AgentService] = lambda: service
    _ROUTE_APP.dependency_overrides[get_workspace_member] = lambda: WorkspaceMember(
        user_id="user-1",
        workspace_id="workspace-1",
        workspace_user_id="workspace-user-1",
        role=WorkspaceUserRole.OWNER,
        permissions=set(),
        session_id="auth-session-1",
    )
    return TestClient(_ROUTE_APP)


def test_delete_returns_actionable_cleanup_conflict() -> None:
    service = AsyncMock(spec=AgentService)
    message = (
        "Disconnect the affected GitHub user Toolkits and complete token "
        "cleanup before deleting this Agent."
    )
    service.delete_by_id.side_effect = GitHubUserOAuthError(
        GitHubUserErrorCode.CLEANUP_REQUIRED, message
    )
    response = _client(service).delete("/agent/v1/workspaces/workspace/agents/agent-1")
    assert response.status_code == 409
    assert response.json() == {
        "detail": {"code": "cleanup_required", "message": message}
    }
    service.delete_by_id.assert_awaited_once_with(
        "agent-1",
        workspace_id="workspace-1",
        workspace_user_id="workspace-user-1",
        role=WorkspaceUserRole.OWNER,
    )


@pytest.mark.parametrize(
    "failure", [NotAdmin("agent-1"), UnlimitedRetention("agent-1")]
)
def test_existing_agent_denials_remain_unchanged(
    failure: NotAdmin | UnlimitedRetention,
) -> None:
    service = AsyncMock(spec=AgentService)
    service.delete_by_id.return_value = Failure(failure)
    response = _client(service).delete("/agent/v1/workspaces/workspace/agents/agent-1")
    assert response.status_code == (403 if isinstance(failure, NotAdmin) else 409)
    assert "cleanup_required" not in response.text


def test_unrelated_domain_failure_is_not_misreported_as_cleanup() -> None:
    service = AsyncMock(spec=AgentService)
    service.delete_by_id.side_effect = GitHubUserOAuthError(
        GitHubUserErrorCode.STALE, "Unexpected publication boundary"
    )
    with pytest.raises(GitHubUserOAuthError):
        _client(service).delete("/agent/v1/workspaces/workspace/agents/agent-1")
