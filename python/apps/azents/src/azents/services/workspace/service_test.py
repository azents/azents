"""Workspace service projections over completed repository operations."""

import pytest
from azcommon.result import Failure, Success
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine

from azents.core.workspace import CreateWithOwnerInput, HandleConflict, NotFound
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import WriteSession
from azents.repos.user import UserRepository
from azents.repos.user.data import UserCreate
from azents.repos.user_email.operations_test import CommittedOperationManager
from azents.repos.workspace import WorkspaceRepository
from azents.repos.workspace.operations import WorkspaceOperationRepository
from azents.repos.workspace.operations_test import ObservedWorkspaceManager
from azents.repos.workspace_user import WorkspaceUserRepository
from azents.services.workspace import WorkspaceService
from azents.services.workspace.data import WorkspaceCreateInput, WorkspaceOutput


async def test_service_projects_only_completed_operations(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    """Every CRUD projection returns after closure without service DB injection."""
    async with rdb_session_manager() as session:
        user = await UserRepository().create(
            session, UserCreate(email="workspace-service-owner@example.com")
        )
        baseline = await WorkspaceRepository().list_all(session)
    manager = ObservedWorkspaceManager(rdb_session_manager)
    service = WorkspaceService(
        repository=WorkspaceOperationRepository(
            manager, WorkspaceRepository(), WorkspaceUserRepository()
        )
    )
    admin = await service.create(
        WorkspaceCreateInput(name="Admin", handle="service-admin")
    )
    assert isinstance(admin, Success)
    assert isinstance(admin.value, WorkspaceOutput)
    owned = await service.create_with_owner(
        CreateWithOwnerInput(
            user_id=user.id,
            workspace_name="Public",
            workspace_handle="service-public",
            owner_name="Owner",
        )
    )
    assert (
        isinstance(owned, Success) and owned.value.workspace_handle == "service-public"
    )
    assert (await service.get_by_handle("service-admin")) == admin.value
    assert await service.get_by_handle("missing-service-workspace") is None
    workspaces = await service.list_all()
    assert len(workspaces.items) == len(baseline.items) + 2
    handles = [workspace.handle for workspace in workspaces.items]
    assert handles.count("service-admin") == 1
    assert handles.count("service-public") == 1
    assert [
        workspace.handle for workspace in (await service.list_by_user(user.id)).items
    ] == ["service-public"]
    assert await service.update_by_handle("service-admin", {}) == admin
    missing = await service.update_by_handle(
        "missing-service-workspace", {"name": "Ignored"}
    )
    assert missing == Failure(NotFound(handle="missing-service-workspace"))
    conflict = await service.create(
        WorkspaceCreateInput(name="Duplicate", handle="service-admin")
    )
    assert conflict == Failure(HandleConflict(handle="service-admin"))
    assert not manager.active
    assert manager.resolved == [True] * 9


async def test_service_preserves_membership_exception_and_atomic_rollback(
    rdb_engine: AsyncEngine,
    latest_db_schema: None,
) -> None:
    """Public owner creation still propagates FK failure without a partial Workspace."""
    del latest_db_schema
    manager = ObservedWorkspaceManager(CommittedOperationManager(rdb_engine))
    service = WorkspaceService(
        repository=WorkspaceOperationRepository(
            manager, WorkspaceRepository(), WorkspaceUserRepository()
        )
    )
    with pytest.raises(IntegrityError):
        await service.create_with_owner(
            CreateWithOwnerInput(
                user_id="0" * 32,
                workspace_name="Rollback",
                workspace_handle="service-owner-failure",
                owner_name="Owner",
            )
        )
    assert not manager.active
    assert manager.resolved == [True]
    assert await service.get_by_handle("service-owner-failure") is None
