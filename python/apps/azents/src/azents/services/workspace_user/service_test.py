"""WorkspaceUser service tests."""

import asyncio
import datetime
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
import sqlalchemy as sa
from azcommon.result import Failure, Success
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from azents.core.enums import WorkspaceUserRole
from azents.rdb.models.workspace import RDBWorkspace
from azents.repos.owner_lifecycle import OwnerLifecycleRepository
from azents.repos.user import UserRepository
from azents.repos.user.data import UserCreate
from azents.repos.workspace import WorkspaceRepository
from azents.repos.workspace.data import Workspace, WorkspaceCreate
from azents.repos.workspace_user import WorkspaceUserRepository
from azents.repos.workspace_user.data import NotFound, WorkspaceUser
from azents.services.runtime_terminal.invalidation import (
    NoopRuntimeTerminalInvalidationPublisher,
)
from azents.testing.types import require_instance

from . import WorkspaceUserService
from .data import (
    CannotModifyOwner,
    InvalidRole,
    NotMemberOfWorkspace,
    OwnerAlreadyExists,
    WorkspaceUserCreateInput,
)


def _now() -> datetime.datetime:
    """Return one stable aware timestamp for domain fixtures."""
    return datetime.datetime(2026, 9, 16, tzinfo=datetime.UTC)


def _workspace() -> Workspace:
    """Build a Workspace fixture."""
    return Workspace(
        name="Workspace",
        handle="workspace",
        default_runtime_profile_id=None,
        default_runtime_profile_version=1,
        created_at=_now(),
        updated_at=_now(),
    )


def _workspace_user(
    *,
    workspace_user_id: str = "workspace-user-1",
    workspace_id: str = "workspace-1",
    user_id: str = "user-1",
    role: WorkspaceUserRole = WorkspaceUserRole.MEMBER,
) -> WorkspaceUser:
    """Build a WorkspaceUser fixture."""
    return WorkspaceUser(
        id=workspace_user_id,
        workspace_id=workspace_id,
        user_id=user_id,
        name="Member",
        role=role,
        created_at=_now(),
        updated_at=_now(),
    )


def _service(
    *,
    user_repository: AsyncMock | None = None,
    workspace_repository: AsyncMock | None = None,
    session: AsyncMock | None = None,
) -> WorkspaceUserService:
    """Build a service with deterministic test dependencies."""
    test_session = session or AsyncMock(spec=AsyncSession)

    @asynccontextmanager
    async def session_manager() -> AsyncGenerator[AsyncSession, None]:
        yield test_session

    return WorkspaceUserService(
        user_repository=require_instance(
            user_repository or AsyncMock(spec=WorkspaceUserRepository),
            WorkspaceUserRepository,
        ),
        workspace_repository=require_instance(
            workspace_repository or AsyncMock(spec=WorkspaceRepository),
            WorkspaceRepository,
        ),
        owner_lifecycle_repository=require_instance(
            MagicMock(spec=OwnerLifecycleRepository),
            OwnerLifecycleRepository,
        ),
        session_manager=session_manager,
        terminal_invalidation_publisher=NoopRuntimeTerminalInvalidationPublisher(),
    )


async def test_create_owner_rejects_existing_owner_under_workspace_lock() -> None:
    """Owner creation checks the current Owner while holding the Workspace lock."""
    user_repository = AsyncMock(spec=WorkspaceUserRepository)
    workspace_repository = AsyncMock(spec=WorkspaceRepository)
    workspace_repository.resolve_id.return_value = "workspace-1"
    workspace_repository.get_by_id_for_update.return_value = _workspace()
    user_repository.get_owner_by_workspace.return_value = _workspace_user(
        role=WorkspaceUserRole.OWNER
    )
    service = _service(
        user_repository=user_repository,
        workspace_repository=workspace_repository,
    )

    result = await service.create(
        WorkspaceUserCreateInput(
            workspace_handle="workspace",
            user_id="user-2",
            name="Second owner",
            role=WorkspaceUserRole.OWNER,
        )
    )

    assert isinstance(result, Failure)
    assert isinstance(result.error, OwnerAlreadyExists)
    workspace_repository.get_by_id_for_update.assert_awaited_once()
    user_repository.create_with_conflict.assert_not_awaited()


async def test_update_role_admin_rejects_owner_assignment_before_database_work() -> (
    None
):
    """Admin role updates must use ownership transfer for Owner assignment."""
    service = _service()

    result = await service.update_role_admin(
        "workspace-user-1", WorkspaceUserRole.OWNER
    )

    assert isinstance(result, Failure)
    assert isinstance(result.error, InvalidRole)


async def test_update_role_admin_rechecks_owner_after_workspace_lock() -> None:
    """A concurrent transfer cannot be overwritten by an Admin role update."""
    user_repository = AsyncMock(spec=WorkspaceUserRepository)
    workspace_repository = AsyncMock(spec=WorkspaceRepository)
    user_repository.get.side_effect = [
        _workspace_user(role=WorkspaceUserRole.MEMBER),
        _workspace_user(role=WorkspaceUserRole.OWNER),
    ]
    workspace_repository.get_by_id_for_update.return_value = _workspace()
    service = _service(
        user_repository=user_repository,
        workspace_repository=workspace_repository,
    )

    result = await service.update_role_admin(
        "workspace-user-1", WorkspaceUserRole.MANAGER
    )

    assert isinstance(result, Failure)
    assert isinstance(result.error, CannotModifyOwner)
    workspace_repository.get_by_id_for_update.assert_awaited_once()
    user_repository.update_role.assert_not_awaited()


async def test_delete_force_rechecks_owner_after_workspace_lock() -> None:
    """A concurrent transfer cannot make Admin deletion remove the new Owner."""
    user_repository = AsyncMock(spec=WorkspaceUserRepository)
    workspace_repository = AsyncMock(spec=WorkspaceRepository)
    user_repository.get.side_effect = [
        _workspace_user(role=WorkspaceUserRole.MEMBER),
        _workspace_user(role=WorkspaceUserRole.OWNER),
    ]
    workspace_repository.get_by_id_for_update.return_value = _workspace()
    service = _service(
        user_repository=user_repository,
        workspace_repository=workspace_repository,
    )

    result = await service.delete_force("workspace-user-1")

    assert isinstance(result, Failure)
    assert isinstance(result.error, CannotModifyOwner)
    workspace_repository.get_by_id_for_update.assert_awaited_once()
    user_repository.delete.assert_not_awaited()


async def test_transfer_ownership_rejects_member_from_another_workspace() -> None:
    """Ownership transfer target must belong to the locked Workspace."""
    user_repository = AsyncMock(spec=WorkspaceUserRepository)
    workspace_repository = AsyncMock(spec=WorkspaceRepository)
    workspace_repository.get_by_id_for_update.return_value = _workspace()
    user_repository.get_for_update.return_value = _workspace_user(
        workspace_id="workspace-2"
    )
    service = _service(
        user_repository=user_repository,
        workspace_repository=workspace_repository,
    )

    result = await service.transfer_ownership("workspace-1", "workspace-user-1")

    assert isinstance(result, Failure)
    assert isinstance(result.error, NotMemberOfWorkspace)
    user_repository.get_owner_by_workspace_for_update.assert_not_awaited()
    user_repository.update_role.assert_not_awaited()


async def test_transfer_ownership_to_current_owner_is_idempotent() -> None:
    """Selecting the current Owner does not demote and promote the same member."""
    owner = _workspace_user(role=WorkspaceUserRole.OWNER)
    user_repository = AsyncMock(spec=WorkspaceUserRepository)
    workspace_repository = AsyncMock(spec=WorkspaceRepository)
    workspace_repository.get_by_id_for_update.return_value = _workspace()
    user_repository.get_for_update.return_value = owner
    user_repository.get_owner_by_workspace_for_update.return_value = owner
    service = _service(
        user_repository=user_repository,
        workspace_repository=workspace_repository,
    )

    result = await service.transfer_ownership("workspace-1", owner.id)

    assert isinstance(result, Success)
    assert result.value.id == owner.id
    user_repository.update_role.assert_not_awaited()


async def test_transfer_ownership_rolls_back_when_promotion_fails() -> None:
    """A failed promotion cannot commit the previous Owner demotion."""
    current_owner = _workspace_user(
        workspace_user_id="workspace-user-owner",
        user_id="user-owner",
        role=WorkspaceUserRole.OWNER,
    )
    new_owner = _workspace_user(
        workspace_user_id="workspace-user-new-owner",
        user_id="user-new-owner",
        role=WorkspaceUserRole.MANAGER,
    )
    session = AsyncMock(spec=AsyncSession)
    user_repository = AsyncMock(spec=WorkspaceUserRepository)
    workspace_repository = AsyncMock(spec=WorkspaceRepository)
    workspace_repository.get_by_id_for_update.return_value = _workspace()
    user_repository.get_for_update.return_value = new_owner
    user_repository.get_owner_by_workspace_for_update.return_value = current_owner
    user_repository.update_role.side_effect = [
        Success(
            _workspace_user(
                workspace_user_id=current_owner.id,
                user_id=current_owner.user_id,
                role=WorkspaceUserRole.MANAGER,
            )
        ),
        Failure(NotFound(workspace_user_id=new_owner.id)),
    ]
    service = _service(
        user_repository=user_repository,
        workspace_repository=workspace_repository,
        session=session,
    )

    result = await service.transfer_ownership("workspace-1", new_owner.id)

    assert isinstance(result, Failure)
    assert isinstance(result.error, NotFound)
    session.rollback.assert_awaited_once()


@pytest.mark.parametrize("attempt", range(3))
async def test_concurrent_owner_creation_keeps_single_owner(
    attempt: int,
    rdb_engine: AsyncEngine,
    latest_db_schema: None,
) -> None:
    """Workspace locking serializes concurrent initial Owner creation."""
    del latest_db_schema, attempt
    suffix = uuid4().hex[:8]
    workspace_handle = f"owner-race-{suffix}"
    workspace_id: str | None = None
    user_ids: list[str] = []

    @asynccontextmanager
    async def session_manager() -> AsyncGenerator[AsyncSession, None]:
        async with AsyncSession(rdb_engine, expire_on_commit=False) as session:
            try:
                yield session
            except Exception:
                await session.rollback()
                raise
            else:
                await session.commit()

    try:
        async with AsyncSession(rdb_engine, expire_on_commit=False) as setup_session:
            workspace_result = await WorkspaceRepository().create(
                setup_session,
                WorkspaceCreate(name="Owner race", handle=workspace_handle),
            )
            assert isinstance(workspace_result, Success)
            workspace_id = await WorkspaceRepository().resolve_id(
                setup_session, workspace_handle
            )
            assert workspace_id is not None
            for index in range(2):
                user = await UserRepository().create(
                    setup_session,
                    UserCreate(email=f"owner-race-{suffix}-{index}@example.com"),
                )
                user_ids.append(user.id)
            await setup_session.commit()

        service = WorkspaceUserService(
            user_repository=WorkspaceUserRepository(),
            workspace_repository=WorkspaceRepository(),
            owner_lifecycle_repository=OwnerLifecycleRepository(),
            session_manager=session_manager,
            terminal_invalidation_publisher=(
                NoopRuntimeTerminalInvalidationPublisher()
            ),
        )
        results = await asyncio.gather(
            *(
                service.create(
                    WorkspaceUserCreateInput(
                        workspace_handle=workspace_handle,
                        user_id=user_id,
                        name=f"Owner {index}",
                        role=WorkspaceUserRole.OWNER,
                    )
                )
                for index, user_id in enumerate(user_ids)
            )
        )

        successes = [result for result in results if isinstance(result, Success)]
        failures = [result for result in results if isinstance(result, Failure)]
        assert len(successes) == 1
        assert len(failures) == 1
        assert isinstance(failures[0].error, OwnerAlreadyExists)

        async with AsyncSession(rdb_engine, expire_on_commit=False) as verify_session:
            members = await WorkspaceUserRepository().list_by_workspace(
                verify_session, workspace_id
            )
        owners = [
            member for member in members.items if member.role == WorkspaceUserRole.OWNER
        ]
        assert len(owners) == 1
    finally:
        async with AsyncSession(rdb_engine, expire_on_commit=False) as cleanup_session:
            if workspace_id is not None:
                await cleanup_session.execute(
                    sa.delete(RDBWorkspace).where(RDBWorkspace.id == workspace_id)
                )
            for user_id in user_ids:
                await UserRepository().delete(cleanup_session, user_id)
            await cleanup_session.commit()
