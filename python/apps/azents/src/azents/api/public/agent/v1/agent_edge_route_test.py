"""Narrow Agent status contracts relocated from assembled lifecycle E2E."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, Mock

from azcommon.result import Failure, Success
from fastapi import FastAPI
from fastapi.testclient import TestClient

from azents.core.auth.deps import WorkspaceMember, get_workspace_member
from azents.core.enums import WorkspaceUserRole
from azents.repos.agent_admin.data import DuplicateAdmin
from azents.repos.agent_operations import AgentOperationsRepository
from azents.services.agent import AgentService

from . import router


def _client(repository: AsyncMock) -> TestClient:
    """Exercise real HTTP routing and service decisions with an inert repository."""
    service = AgentService(
        repository=repository,
        github_user_oauth_service=Mock(),
        model_catalog_read_service=Mock(),
        model_metadata_service=Mock(),
        active_model_capabilities_service=Mock(),
        image_generation_catalog_service=Mock(),
        runtime_profile_service=Mock(),
        upload_service=Mock(),
        s3_service=Mock(),
        workspace_s3_bucket=None,
        avatar_cdn_base_url=None,
        terminal_policy_invalidation_publisher=Mock(),
    )
    app = FastAPI()
    app.include_router(router, prefix="/agent/v1")
    app.dependency_overrides[AgentService] = lambda: service
    app.dependency_overrides[get_workspace_member] = lambda: WorkspaceMember(
        user_id="owner-1",
        workspace_id="workspace-1",
        workspace_user_id="workspace-owner-1",
        role=WorkspaceUserRole.OWNER,
        permissions=set(),
        session_id="auth-session-1",
    )
    return TestClient(app)


def test_nonexistent_agent_returns_404_from_real_service() -> None:
    """An absent repository record maps to the safe public not-found status."""
    repository = AsyncMock(spec=AgentOperationsRepository)
    repository.get_by_id.return_value = None
    response = _client(repository).get(
        "/agent/v1/workspaces/workspace/agents/nonexistent_id_12345678"
    )
    assert response.status_code == 404
    assert response.json() == {"detail": "Agent not found."}
    repository.get_by_id.assert_awaited_once_with("nonexistent_id_12345678")
    repository.create_admin.assert_not_awaited()


def test_duplicate_admin_returns_409_after_initial_success() -> None:
    """Real service/route mapping preserves the first add and duplicate failure."""
    repository = AsyncMock(spec=AgentOperationsRepository)
    repository.get_by_id.return_value = Mock(workspace_id="workspace-1")
    repository.get_workspace_user.return_value = Mock(workspace_id="workspace-1")
    now = datetime.now(UTC)
    repository.create_admin.side_effect = [
        Success(
            Mock(
                id="admin-1",
                agent_id="agent-1",
                workspace_user_id="member-1",
                created_at=now,
            )
        ),
        Failure(DuplicateAdmin(agent_id="agent-1", workspace_user_id="member-1")),
    ]
    with _client(repository) as client:
        url = "/agent/v1/workspaces/workspace/agents/agent-1/admins"
        initial = client.post(url, json={"workspace_user_id": "member-1"})
        duplicate = client.post(url, json={"workspace_user_id": "member-1"})
    assert initial.status_code == 201
    assert initial.json()["workspace_user_id"] == "member-1"
    assert duplicate.status_code == 409
    assert duplicate.json() == {"detail": "Already registered as an administrator."}
    assert repository.create_admin.await_count == 2
    for call in repository.create_admin.await_args_list:
        assert call.kwargs == {"agent_id": "agent-1", "workspace_user_id": "member-1"}
    repository.is_admin.assert_not_awaited()
