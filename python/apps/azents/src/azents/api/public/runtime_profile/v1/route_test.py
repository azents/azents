"""Workspace Runtime Profile recreation Public API route tests."""

import datetime
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from azents.core.auth.deps import WorkspaceMember, get_workspace_member
from azents.core.auth.permissions import Permission, Permissions
from azents.core.enums import WorkspaceUserRole
from azents.core.runtime_profile import (
    RuntimeProfileLifecycle,
    RuntimeRecreationItemStatus,
    RuntimeRecreationOperationStatus,
    RuntimeRecreationTargetKind,
)
from azents.repos.runtime_profile.data import (
    RuntimeRecreationOperation,
    RuntimeRecreationOperationItem,
    WorkspaceRuntimeProfile,
    WorkspaceRuntimeProfileDeletion,
)
from azents.services.runtime_profile_workspace.service import (
    RuntimeProfileWorkspaceService,
    RuntimeProfileWorkspaceUnavailable,
)
from azents.services.runtime_recreation.service import (
    RuntimeRecreationProjection,
    RuntimeRecreationService,
    RuntimeRecreationUnavailable,
)

from . import router


def _create_route_app() -> FastAPI:
    """Create the Runtime Profile route app once for this test module."""
    app = FastAPI()
    app.include_router(router, prefix="/runtime-profile/v1")
    return app


_ROUTE_APP = _create_route_app()


@pytest.fixture(autouse=True)
def _reset_dependency_overrides() -> None:
    """Prevent dependency overrides from leaking between tests."""
    _ROUTE_APP.dependency_overrides.clear()


def _operation() -> RuntimeRecreationOperation:
    """Build one Workspace-scoped recreation operation."""
    now = datetime.datetime(2026, 7, 31, tzinfo=datetime.UTC)
    return RuntimeRecreationOperation(
        id="operation-1",
        target_kind=RuntimeRecreationTargetKind.WORKSPACE_RUNTIME_PROFILE,
        target_id="profile-1",
        target_version="7",
        status=RuntimeRecreationOperationStatus.COMPLETED_WITH_FAILURES,
        concurrency_limit=3,
        actor_user_id=None,
        actor_workspace_user_id="workspace-user-1",
        total_count=4,
        pending_count=0,
        running_count=0,
        succeeded_count=2,
        skipped_count=1,
        failed_count=1,
        created_at=now,
        started_at=now,
        completed_at=now,
    )


def _item() -> RuntimeRecreationOperationItem:
    """Build one bounded recreation failure detail."""
    now = datetime.datetime(2026, 7, 31, tzinfo=datetime.UTC)
    return RuntimeRecreationOperationItem(
        id="item-1",
        operation_id="operation-1",
        runtime_id="runtime-1",
        expected_configuration_sequence=1,
        expected_configuration_digest="a" * 64,
        expected_desired_generation=9,
        status=RuntimeRecreationItemStatus.FAILED,
        attempt=3,
        dispatched_generation=9,
        failure_code="recreation_failed",
        failure_message="Runtime recreation failed.",
        created_at=now,
        updated_at=now,
    )


def _app(
    service: AsyncMock,
    *,
    permissions: set[Permission],
    workspace_service: AsyncMock | None = None,
) -> FastAPI:
    """Create a Public API app with recreation dependencies overridden."""
    app = _ROUTE_APP
    app.dependency_overrides[RuntimeRecreationService] = lambda: service
    if workspace_service is not None:
        app.dependency_overrides[RuntimeProfileWorkspaceService] = lambda: (
            workspace_service
        )
    app.dependency_overrides[get_workspace_member] = lambda: WorkspaceMember(
        user_id="user-1",
        workspace_id="workspace-1",
        workspace_user_id="workspace-user-1",
        role=WorkspaceUserRole.OWNER,
        permissions=permissions,
        session_id="session-1",
    )
    return app


def _client(
    service: AsyncMock,
    *,
    permissions: set[Permission],
    workspace_service: AsyncMock | None = None,
) -> TestClient:
    """Create a Public API client for recreation route tests."""
    return TestClient(
        _app(
            service,
            permissions=permissions,
            workspace_service=workspace_service,
        )
    )


def _deleted_profile() -> WorkspaceRuntimeProfileDeletion:
    return WorkspaceRuntimeProfileDeletion(
        profile_id="profile-1",
        cleared_workspace_default=True,
        cleared_agent_count=2,
        affected_running_runtime_count=1,
        superseded_recreation_operation_count=1,
    )


def test_recreation_routes_require_explicit_read_and_write_permissions() -> None:
    """Workspace membership alone cannot create or inspect recreation operations."""
    service = AsyncMock(spec=RuntimeRecreationService)
    client = _client(service, permissions=set())

    create_response = client.post(
        "/runtime-profile/v1/workspaces/acme/profiles/profile-1/recreation-operations",
        json={"expected_version": 7, "concurrency_limit": 3},
    )
    get_response = client.get(
        "/runtime-profile/v1/workspaces/acme/recreation-operations/operation-1"
    )

    assert create_response.status_code == 403
    assert get_response.status_code == 403
    service.create_workspace_profile_operation.assert_not_awaited()
    service.get_workspace_operation.assert_not_awaited()


def test_delete_profile_requires_explicit_delete_permission() -> None:
    """Runtime Profile write permission does not grant permanent deletion."""
    recreation_service = AsyncMock(spec=RuntimeRecreationService)
    workspace_service = AsyncMock(spec=RuntimeProfileWorkspaceService)

    response = _client(
        recreation_service,
        permissions={Permissions.RUNTIME_PROFILES_WRITE},
        workspace_service=workspace_service,
    ).request(
        "DELETE",
        "/runtime-profile/v1/workspaces/acme/profiles/profile-1",
        json={"expected_version": 7},
    )

    assert response.status_code == 403
    workspace_service.delete_profile.assert_not_awaited()


def test_delete_profile_forwards_exact_workspace_authority_and_actor() -> None:
    """The delete route returns only bounded committed impact evidence."""
    recreation_service = AsyncMock(spec=RuntimeRecreationService)
    workspace_service = AsyncMock(spec=RuntimeProfileWorkspaceService)
    workspace_service.delete_profile.return_value = _deleted_profile()

    response = _client(
        recreation_service,
        permissions={Permissions.RUNTIME_PROFILES_DELETE},
        workspace_service=workspace_service,
    ).request(
        "DELETE",
        "/runtime-profile/v1/workspaces/acme/profiles/profile-1",
        json={"expected_version": 7},
    )

    assert response.status_code == 200
    assert response.json() == {
        "profile_id": "profile-1",
        "cleared_workspace_default": True,
        "cleared_agent_count": 2,
        "affected_running_runtime_count": 1,
        "superseded_recreation_operation_count": 1,
    }
    workspace_service.delete_profile.assert_awaited_once_with(
        "workspace-1",
        "profile-1",
        expected_version=7,
        actor_workspace_user_id="workspace-user-1",
    )


def test_delete_profile_maps_not_found_and_version_conflict() -> None:
    """Delete errors preserve non-disclosure and current optimistic evidence."""
    recreation_service = AsyncMock(spec=RuntimeRecreationService)
    workspace_service = AsyncMock(spec=RuntimeProfileWorkspaceService)
    workspace_service.delete_profile.side_effect = RuntimeProfileWorkspaceUnavailable(
        code="runtime_profile_not_found",
        message="Workspace Runtime Profile was not found.",
    )
    client = _client(
        recreation_service,
        permissions={Permissions.RUNTIME_PROFILES_DELETE},
        workspace_service=workspace_service,
    )

    not_found = client.request(
        "DELETE",
        "/runtime-profile/v1/workspaces/acme/profiles/foreign-profile",
        json={"expected_version": 7},
    )

    assert not_found.status_code == 404
    assert not_found.json()["detail"] == {"code": "runtime_profile_not_found"}

    now = datetime.datetime(2026, 8, 11, tzinfo=datetime.UTC)
    workspace_service.delete_profile.side_effect = RuntimeProfileWorkspaceUnavailable(
        code="runtime_profile_version_conflict",
        message="Workspace Runtime Profile version is stale.",
        current_profile=WorkspaceRuntimeProfile(
            id="profile-1",
            workspace_id="workspace-1",
            provider_id="provider-1",
            infrastructure_profile_id="infrastructure-1",
            display_name="Profile",
            description="Profile",
            lifecycle=RuntimeProfileLifecycle.ACTIVE,
            policy={"schema_version": 1},
            version=8,
            digest="a" * 64,
            created_by_workspace_user_id=None,
            updated_by_workspace_user_id=None,
            created_at=now,
            updated_at=now,
        ),
    )
    conflict = client.request(
        "DELETE",
        "/runtime-profile/v1/workspaces/acme/profiles/profile-1",
        json={"expected_version": 7},
    )

    assert conflict.status_code == 409
    assert conflict.json()["detail"] == {
        "code": "runtime_profile_version_conflict",
        "current_version": 8,
    }


def test_create_recreation_uses_workspace_authority_and_actor() -> None:
    """The route forwards only the authenticated Workspace authority and actor."""
    service = AsyncMock(spec=RuntimeRecreationService)
    service.create_workspace_profile_operation.return_value = _operation()

    response = _client(
        service,
        permissions={Permissions.RUNTIME_PROFILES_WRITE},
    ).post(
        "/runtime-profile/v1/workspaces/acme/profiles/profile-1/recreation-operations",
        json={"expected_version": 7, "concurrency_limit": 3},
    )

    assert response.status_code == 201
    assert response.json()["id"] == "operation-1"
    assert response.json()["items"] == []
    service.create_workspace_profile_operation.assert_awaited_once_with(
        "workspace-1",
        "profile-1",
        expected_version=7,
        concurrency_limit=3,
        actor_workspace_user_id="workspace-user-1",
    )


def test_create_recreation_returns_current_version_on_conflict() -> None:
    """A stale target version returns the current Workspace Profile version."""
    service = AsyncMock(spec=RuntimeRecreationService)
    service.create_workspace_profile_operation.side_effect = (
        RuntimeRecreationUnavailable(
            code="target_version_conflict",
            message="Workspace Runtime Profile version is stale.",
            current_version=8,
        )
    )

    response = _client(
        service,
        permissions={Permissions.RUNTIME_PROFILES_WRITE},
    ).post(
        "/runtime-profile/v1/workspaces/acme/profiles/profile-1/recreation-operations",
        json={"expected_version": 7, "concurrency_limit": 3},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == {
        "code": "target_version_conflict",
        "current_version": 8,
    }


def test_get_recreation_forwards_workspace_scope_and_bounded_paging() -> None:
    """Progress reads preserve Workspace isolation and bounded detail paging."""
    service = AsyncMock(spec=RuntimeRecreationService)
    service.get_workspace_operation.return_value = RuntimeRecreationProjection(
        operation=_operation(),
        items=(_item(),),
    )

    response = _client(
        service,
        permissions={Permissions.RUNTIME_PROFILES_READ},
    ).get(
        "/runtime-profile/v1/workspaces/acme/recreation-operations/operation-1",
        params={"offset": 2, "limit": 3},
    )

    assert response.status_code == 200
    assert response.json()["failed_count"] == 1
    assert response.json()["items"] == [
        {
            "runtime_id": "runtime-1",
            "status": "failed",
            "attempt": 3,
            "dispatched_generation": 9,
            "failure_code": "recreation_failed",
            "failure_message": "Runtime recreation failed.",
            "updated_at": "2026-07-31T00:00:00Z",
        }
    ]
    service.get_workspace_operation.assert_awaited_once_with(
        "workspace-1",
        "operation-1",
        offset=2,
        limit=3,
    )


def test_get_recreation_hides_cross_workspace_operations() -> None:
    """A service-hidden foreign operation remains indistinguishable from absence."""
    service = AsyncMock(spec=RuntimeRecreationService)
    service.get_workspace_operation.side_effect = RuntimeRecreationUnavailable(
        code="operation_not_found",
        message="Runtime recreation operation was not found.",
    )

    response = _client(
        service,
        permissions={Permissions.RUNTIME_PROFILES_READ},
    ).get("/runtime-profile/v1/workspaces/acme/recreation-operations/foreign-operation")

    assert response.status_code == 404
    assert response.json()["detail"] == {"code": "operation_not_found"}
