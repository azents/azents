"""Completed Workspace operation atomicity, projection and rollback tests."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from azcommon.result import Failure, Result, Success
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.workspace import (
    CreateWithOwnerInput,
    HandleConflict,
    NotFound,
    WorkspaceCreate,
)
from azents.rdb.session import SessionManager
from azents.repos.user import UserRepository
from azents.repos.user.data import UserCreate
from azents.repos.workspace import WorkspaceRepository
from azents.repos.workspace.data import Workspace
from azents.repos.workspace.operations import WorkspaceOperationRepository
from azents.repos.workspace_user import WorkspaceUserRepository
from azents.repos.workspace_user.data import (
    WorkspaceNotFound,
    WorkspaceUser,
    WorkspaceUserCreate,
    WorkspaceUserList,
    WorkspaceUserRole,
)


class ObservedWorkspaceManager:
    """Observe real session resolution before detached results leave operations."""

    def __init__(self, manager: SessionManager[AsyncSession]) -> None:
        self.manager = manager
        self.active = False
        self.sessions: list[AsyncSession] = []
        self.resolved: list[bool] = []

    @asynccontextmanager
    async def __call__(self) -> AsyncIterator[AsyncSession]:
        """Record closure on success and after rollback."""
        self.active = True
        current: AsyncSession | None = None
        try:
            async with self.manager() as session:
                current = session
                self.sessions.append(session)
                yield session
        finally:
            self.active = False
            if current is not None:
                self.resolved.append(not current.in_transaction())


class _FailingMembershipRepository(WorkspaceUserRepository):
    """Raise after the ordinary membership insert to prove aggregate rollback."""

    async def create(
        self, session: AsyncSession, create: WorkspaceUserCreate
    ) -> Result[WorkspaceUser, WorkspaceNotFound]:
        """Execute ordinary creation, then fail without Admin conflict handling."""
        result = await super().create(session, create)
        assert isinstance(result, Success)
        raise ValueError("membership insertion failed")


class _MissingIdRepository(WorkspaceRepository):
    """Violate the just-created internal-ID invariant deterministically."""

    async def resolve_id(self, session: AsyncSession, handle: str) -> str | None:
        """Return no ID after creation to retain the assertion contract."""
        del session, handle
        return None


async def _user(manager: SessionManager[AsyncSession], name: str) -> str:
    """Create a real User for ownership foreign keys."""
    async with manager() as session:
        return (
            await UserRepository().create(
                session, UserCreate(email=f"{name}@example.com")
            )
        ).id


def _owner(user_id: str, handle: str) -> CreateWithOwnerInput:
    """Build a public owner-create request with unchanged input fields."""
    return CreateWithOwnerInput(
        user_id=user_id,
        workspace_name="Owned workspace",
        workspace_handle=handle,
        owner_name="Initial owner",
    )


async def test_admin_create_is_workspace_only_and_public_create_has_owner(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """Both paths resolve before return while only public create adds membership."""
    user_id = await _user(rdb_session_manager, "workspace-operation-owner")
    manager = ObservedWorkspaceManager(rdb_session_manager)
    repository = WorkspaceOperationRepository(
        manager, WorkspaceRepository(), WorkspaceUserRepository()
    )
    admin = await repository.create(
        WorkspaceCreate(name="Admin workspace", handle="admin-operation")
    )
    assert isinstance(admin, Success)
    owned = await repository.create_with_owner(_owner(user_id, "public-operation"))
    assert isinstance(owned, Success)
    assert owned.value.workspace_handle == "public-operation"
    assert not manager.active
    assert manager.resolved == [True, True]
    async with rdb_session_manager() as session:
        admin_id = await WorkspaceRepository().resolve_id(session, "admin-operation")
        public_id = await WorkspaceRepository().resolve_id(session, "public-operation")
        assert admin_id is not None and public_id is not None
        assert (
            await WorkspaceUserRepository().get_by_workspace_and_user(
                session, workspace_id=admin_id, user_id=user_id
            )
            is None
        )
        membership = await WorkspaceUserRepository().get_by_workspace_and_user(
            session, workspace_id=public_id, user_id=user_id
        )
        assert membership is not None
        assert membership.name == "Initial owner"
        assert membership.role is WorkspaceUserRole.OWNER


async def test_membership_exception_rolls_back_both_workspace_and_owner(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """An actual insert followed by failure leaves neither aggregate row behind."""
    user_id = await _user(rdb_session_manager, "workspace-operation-rollback")
    manager = ObservedWorkspaceManager(rdb_session_manager)
    repository = WorkspaceOperationRepository(
        manager, WorkspaceRepository(), _FailingMembershipRepository()
    )
    with pytest.raises(ValueError, match="membership insertion failed"):
        await repository.create_with_owner(_owner(user_id, "owner-rollback"))
    assert not manager.active
    assert manager.resolved == [True]
    async with rdb_session_manager() as session:
        assert await WorkspaceRepository().resolve_id(session, "owner-rollback") is None
        assert (
            await WorkspaceUserRepository().list_by_user(session, user_id)
        ).items == []


async def test_resolve_id_invariant_failure_rolls_back_workspace(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """A missing just-created ID retains the existing assertion failure."""
    memberships = AsyncMock(spec=WorkspaceUserRepository)
    repository = WorkspaceOperationRepository(
        rdb_session_manager, _MissingIdRepository(), memberships
    )
    with pytest.raises(AssertionError):
        await repository.create_with_owner(_owner("0" * 32, "missing-created-id"))
    memberships.create.assert_not_awaited()
    async with rdb_session_manager() as session:
        assert (
            await WorkspaceRepository().resolve_id(session, "missing-created-id")
            is None
        )


async def test_create_and_update_conflicts_preserve_typed_errors_and_rollback(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """Conflicting handle mutations cannot persist partial names or ownership."""
    async with rdb_session_manager() as session:
        baseline = await WorkspaceRepository().list_all(session)
    manager = ObservedWorkspaceManager(rdb_session_manager)
    repository = WorkspaceOperationRepository(
        manager, WorkspaceRepository(), WorkspaceUserRepository()
    )
    await repository.create(WorkspaceCreate(name="First", handle="workspace-first"))
    await repository.create(WorkspaceCreate(name="Second", handle="workspace-second"))
    duplicate = await repository.create(
        WorkspaceCreate(name="Duplicate", handle="workspace-first")
    )
    assert duplicate == Failure(HandleConflict(handle="workspace-first"))
    owner_duplicate = await repository.create_with_owner(
        _owner("0" * 32, "workspace-first")
    )
    assert owner_duplicate == duplicate
    update = await repository.update_by_handle(
        "workspace-second", {"name": "Must rollback", "handle": "workspace-first"}
    )
    assert update == Failure(HandleConflict(handle="workspace-first"))
    second = await repository.get_by_handle("workspace-second")
    assert second is not None and second.name == "Second"
    workspaces = await repository.list_all()
    assert len(workspaces.items) == len(baseline.items) + 2
    handles = [workspace.handle for workspace in workspaces.items]
    assert handles.count("workspace-first") == 1
    assert handles.count("workspace-second") == 1
    assert not manager.active
    assert all(manager.resolved)


async def test_update_omission_and_missing_results_are_unchanged(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """Empty and partial updates preserve untouched fields and missing semantics."""
    repository = WorkspaceOperationRepository(
        rdb_session_manager, WorkspaceRepository(), WorkspaceUserRepository()
    )
    created = await repository.create(
        WorkspaceCreate(name="Original", handle="workspace-omission")
    )
    assert isinstance(created, Success)
    unchanged = await repository.update_by_handle("workspace-omission", {})
    assert unchanged == created
    renamed = await repository.update_by_handle(
        "workspace-omission", {"handle": "workspace-renamed"}
    )
    assert isinstance(renamed, Success)
    assert renamed.value.name == "Original"
    assert renamed.value.default_runtime_profile_id is None
    assert (
        renamed.value.default_runtime_profile_version
        == created.value.default_runtime_profile_version
    )
    assert await repository.get_by_handle("workspace-omission") is None
    assert await repository.update_by_handle("missing-workspace", {}) == Failure(
        NotFound(handle="missing-workspace")
    )


async def test_user_list_keeps_membership_order_and_omits_missing_projections(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """Membership read and all referenced projections share one completed lifetime."""
    now = datetime.now(UTC)
    memberships = AsyncMock(spec=WorkspaceUserRepository)
    memberships.list_by_user.return_value = WorkspaceUserList(
        items=[
            WorkspaceUser(
                id=f"member-{id}",
                workspace_id=id,
                user_id="user-1",
                name="Member",
                role=WorkspaceUserRole.MEMBER,
                created_at=now,
                updated_at=now,
            )
            for id in ["second", "missing", "first"]
        ]
    )
    workspaces = AsyncMock(spec=WorkspaceRepository)
    workspaces.get_by_id.side_effect = [
        Workspace(
            name="Second",
            handle="second",
            default_runtime_profile_id=None,
            default_runtime_profile_version=1,
            created_at=now,
            updated_at=now,
        ),
        None,
        Workspace(
            name="First",
            handle="first",
            default_runtime_profile_id=None,
            default_runtime_profile_version=1,
            created_at=now,
            updated_at=now,
        ),
    ]
    manager = ObservedWorkspaceManager(rdb_session_manager)
    repository = WorkspaceOperationRepository(manager, workspaces, memberships)
    result = await repository.list_by_user("user-1")
    assert [workspace.handle for workspace in result.items] == ["second", "first"]
    assert len(manager.sessions) == 1
    memberships.list_by_user.assert_awaited_once_with(manager.sessions[0], "user-1")
    assert [call.args for call in workspaces.get_by_id.await_args_list] == [
        (manager.sessions[0], id) for id in ["second", "missing", "first"]
    ]
    assert not manager.active
    assert manager.resolved == [True]
