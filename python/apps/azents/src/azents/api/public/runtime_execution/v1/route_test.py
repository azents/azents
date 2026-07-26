"""Runtime Execution v1 Public API tests."""

from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from azents.app import create_dummy_public_app
from azents.core.auth.deps import WorkspaceMember, get_workspace_member
from azents.core.auth.roles import get_permissions_for_role
from azents.core.enums import WorkspaceUserRole
from azents.core.runtime_execution_policy import (
    SYSTEM_STANDARD_PROFILE_ID,
    digest_runtime_execution_policy,
    empty_runtime_execution_restriction,
)
from azents.repos.runtime_provider_policy.data import RuntimePolicySnapshot
from azents.services.runtime_execution_policy.application_service import (
    RuntimeExecutionPolicyApplicationResult,
    RuntimeExecutionPolicyApplicationService,
    RuntimeExecutionPolicyApplicationUnavailable,
)
from azents.services.runtime_execution_policy.service import (
    RuntimeExecutionPolicyService,
    RuntimeExecutionPolicyUnavailable,
    WorkspaceRuntimeExecutionPolicyView,
)


def _workspace_view(*, version: int) -> WorkspaceRuntimeExecutionPolicyView:
    restriction = empty_runtime_execution_restriction()
    return WorkspaceRuntimeExecutionPolicyView(
        workspace_id="workspace-1",
        version=version,
        restriction=restriction,
        digest=digest_runtime_execution_policy(restriction),
        allowed_profile_ids=frozenset({SYSTEM_STANDARD_PROFILE_ID}),
        updated_at=None,
    )


def _client(
    service: AsyncMock,
    *,
    role: WorkspaceUserRole,
    application_service: AsyncMock | None = None,
) -> TestClient:
    app = create_dummy_public_app()
    app.dependency_overrides[RuntimeExecutionPolicyService] = lambda: service
    if application_service is not None:
        app.dependency_overrides[RuntimeExecutionPolicyApplicationService] = lambda: (
            application_service
        )
    app.dependency_overrides[get_workspace_member] = lambda: WorkspaceMember(
        user_id="user-1",
        workspace_id="workspace-1",
        workspace_user_id="workspace-user-1",
        role=role,
        permissions=get_permissions_for_role(role),
        session_id="session-1",
    )
    return TestClient(app)


def test_member_can_read_implicit_workspace_policy() -> None:
    """Workspace members receive the safe version-zero initial policy."""
    service = AsyncMock(spec=RuntimeExecutionPolicyService)
    service.get_workspace_policy.return_value = _workspace_view(version=0)

    response = _client(service, role=WorkspaceUserRole.MEMBER).get(
        "/runtime-execution/v1/workspaces/example/policy"
    )

    assert response.status_code == 200
    assert response.json()["version"] == 0
    assert response.json()["allowed_profile_ids"] == [SYSTEM_STANDARD_PROFILE_ID]


def test_member_cannot_replace_workspace_policy() -> None:
    """Workspace MEMBER read access never grants mutation authority."""
    service = AsyncMock(spec=RuntimeExecutionPolicyService)
    restriction = empty_runtime_execution_restriction().model_dump(mode="json")

    response = _client(service, role=WorkspaceUserRole.MEMBER).put(
        "/runtime-execution/v1/workspaces/example/policy",
        json={
            "expected_version": 0,
            "restriction": restriction,
            "allowed_profile_ids": [SYSTEM_STANDARD_PROFILE_ID],
        },
    )

    assert response.status_code == 403
    service.replace_workspace.assert_not_awaited()


def test_manager_can_replace_workspace_policy() -> None:
    """Workspace MANAGER receives the dedicated policy write permission."""
    service = AsyncMock(spec=RuntimeExecutionPolicyService)
    service.replace_workspace_for_manager.return_value = _workspace_view(version=1)
    restriction = empty_runtime_execution_restriction().model_dump(mode="json")

    response = _client(service, role=WorkspaceUserRole.MANAGER).put(
        "/runtime-execution/v1/workspaces/example/policy",
        json={
            "expected_version": 0,
            "restriction": restriction,
            "allowed_profile_ids": [SYSTEM_STANDARD_PROFILE_ID],
        },
    )

    assert response.status_code == 200
    assert response.json()["version"] == 1
    service.replace_workspace_for_manager.assert_awaited_once()


def test_agent_policy_maps_service_authorization_denial() -> None:
    """Agent policy routes preserve the Agent admin-or-owner boundary."""
    service = AsyncMock(spec=RuntimeExecutionPolicyService)
    service.get_agent_policy_for_manager.side_effect = (
        RuntimeExecutionPolicyUnavailable("agent_access_denied", "agent-1")
    )

    response = _client(service, role=WorkspaceUserRole.MANAGER).get(
        "/runtime-execution/v1/workspaces/example/agents/agent-1/settings"
    )

    assert response.status_code == 403
    assert response.json()["detail"] == {"code": "agent_access_denied"}


def test_agent_apply_returns_exact_target_snapshot() -> None:
    """Agent Apply exposes only immutable target evidence metadata."""
    service = AsyncMock(spec=RuntimeExecutionPolicyService)
    application_service = AsyncMock(spec=RuntimeExecutionPolicyApplicationService)
    snapshot = cast(
        RuntimePolicySnapshot,
        SimpleNamespace(
            id="snapshot-2",
            target_desired_generation=3,
            execution_target_digest="d" * 64,
        ),
    )
    application_service.apply_agent_for_manager.return_value = (
        RuntimeExecutionPolicyApplicationResult(
            snapshot=snapshot,
            created=True,
        )
    )

    response = _client(
        service,
        role=WorkspaceUserRole.MANAGER,
        application_service=application_service,
    ).post("/runtime-execution/v1/workspaces/example/agents/agent-1/apply")

    assert response.status_code == 200
    assert response.json() == {
        "snapshot_id": "snapshot-2",
        "desired_generation": 3,
        "target_digest": "d" * 64,
        "created": True,
    }
    application_service.apply_agent_for_manager.assert_awaited_once()


def test_agent_apply_maps_agent_management_denial() -> None:
    """Agent Apply preserves the existing Agent owner/admin authorization boundary."""
    service = AsyncMock(spec=RuntimeExecutionPolicyService)
    application_service = AsyncMock(spec=RuntimeExecutionPolicyApplicationService)
    application_service.apply_agent_for_manager.side_effect = (
        RuntimeExecutionPolicyApplicationUnavailable(
            "agent_access_denied",
            "agent-1",
        )
    )

    response = _client(
        service,
        role=WorkspaceUserRole.MANAGER,
        application_service=application_service,
    ).post("/runtime-execution/v1/workspaces/example/agents/agent-1/apply")

    assert response.status_code == 403
    assert response.json()["detail"] == {"code": "agent_access_denied"}
