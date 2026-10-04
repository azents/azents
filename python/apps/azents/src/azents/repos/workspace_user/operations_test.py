"""WorkspaceUser completed-operation repository tests."""

import asyncio
import datetime
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
import sqlalchemy as sa
from azcommon.result import Failure, Success
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from azents.core.enums import WorkspaceUserRole
from azents.core.workspace import WorkspaceCreate
from azents.rdb.models.workspace import RDBWorkspace
from azents.rdb.session_capabilities import ReadWriteSession, WriteSession
from azents.repos.owner_lifecycle import OwnerLifecycleRepository
from azents.repos.user import UserRepository
from azents.repos.user.data import UserCreate
from azents.repos.workspace import WorkspaceRepository
from azents.repos.workspace.data import Workspace
from azents.repos.workspace_user import WorkspaceUserRepository
from azents.repos.workspace_user.data import NotFound, WorkspaceUser
from azents.testing.types import require_instance

from .operations import (
    WorkspaceUserOperationRepository,
    WorkspaceUserOutsideWorkspace,
    WorkspaceUserOwnerAlreadyExists,
    WorkspaceUserOwnerLocked,
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


def _repository(
    *,
    user_repository: AsyncMock | None = None,
    workspace_repository: AsyncMock | None = None,
    session: WriteSession | None = None,
) -> WorkspaceUserOperationRepository:
    """Build an operation repository with one deterministic transaction."""
    test_session = session or ReadWriteSession(AsyncMock(spec=AsyncSession))

    @asynccontextmanager
    async def session_manager() -> AsyncGenerator[WriteSession, None]:
        yield test_session

    return WorkspaceUserOperationRepository(
        user_repository=require_instance(
            user_repository or AsyncMock(spec=WorkspaceUserRepository),
            WorkspaceUserRepository,
        ),
        workspace_repository=require_instance(
            workspace_repository or AsyncMock(spec=WorkspaceRepository),
            WorkspaceRepository,
        ),
        owner_lifecycle_repository=require_instance(
            AsyncMock(spec=OwnerLifecycleRepository),
            OwnerLifecycleRepository,
        ),
        session_manager=session_manager,
    )


async def test_create_owner_rejects_existing_owner_under_workspace_lock() -> None:
    """Owner creation checks the current Owner while holding the Workspace lock."""
    user_repository = AsyncMock(spec=WorkspaceUserRepository)
    workspace_repository = AsyncMock(spec=WorkspaceRepository)
    workspace_repository.resolve_id.return_value = "workspace-1"
    workspace_repository.acquire_ownership_mutation.return_value = _workspace()
    user_repository.get_owner_by_workspace.return_value = _workspace_user(
        role=WorkspaceUserRole.OWNER
    )
    repository = _repository(
        user_repository=user_repository,
        workspace_repository=workspace_repository,
    )

    result = await repository.create_by_handle(
        workspace_handle="workspace",
        user_id="user-2",
        name="Second owner",
        role=WorkspaceUserRole.OWNER,
    )

    assert isinstance(result, Failure)
    assert isinstance(result.error, WorkspaceUserOwnerAlreadyExists)
    workspace_repository.acquire_ownership_mutation.assert_awaited_once()
    user_repository.create_with_conflict.assert_not_awaited()


async def test_update_role_rejects_owner_from_conditional_mutation() -> None:
    """A conditional update losing to transfer returns the existing OwnerLocked."""
    users = AsyncMock(spec=WorkspaceUserRepository)
    workspace = AsyncMock(spec=WorkspaceRepository)
    users.update_non_owner_role.return_value = None
    users.get.return_value = _workspace_user(role=WorkspaceUserRole.OWNER)
    repo = _repository(user_repository=users, workspace_repository=workspace)
    result = await repo.update_non_owner_role(
        workspace_user_id="workspace-user-1", role=WorkspaceUserRole.MANAGER
    )
    assert isinstance(result, Failure)
    assert isinstance(result.error, WorkspaceUserOwnerLocked)
    workspace.acquire_ownership_mutation.assert_not_awaited()


async def test_delete_rejects_owner_from_conditional_mutation() -> None:
    """A conditional delete cannot remove a newly transferred Owner."""
    users = AsyncMock(spec=WorkspaceUserRepository)
    workspace = AsyncMock(spec=WorkspaceRepository)
    users.delete_non_owner.return_value = None
    users.get.return_value = _workspace_user(role=WorkspaceUserRole.OWNER)
    repo = _repository(user_repository=users, workspace_repository=workspace)
    result = await repo.delete_non_owner(workspace_user_id="workspace-user-1")
    assert isinstance(result, Failure)
    assert isinstance(result.error, WorkspaceUserOwnerLocked)
    workspace.acquire_ownership_mutation.assert_not_awaited()


async def test_transfer_ownership_rejects_member_from_another_workspace() -> None:
    """Ownership transfer target must belong to the locked Workspace."""
    user_repository = AsyncMock(spec=WorkspaceUserRepository)
    workspace_repository = AsyncMock(spec=WorkspaceRepository)
    workspace_repository.acquire_ownership_mutation.return_value = _workspace()
    user_repository.get.return_value = _workspace_user(workspace_id="workspace-2")
    repository = _repository(
        user_repository=user_repository,
        workspace_repository=workspace_repository,
    )

    result = await repository.transfer_ownership(
        workspace_id="workspace-1",
        new_owner_workspace_user_id="workspace-user-1",
    )

    assert isinstance(result, Failure)
    assert isinstance(result.error, WorkspaceUserOutsideWorkspace)
    user_repository.get_owner_by_workspace.assert_not_awaited()


async def test_transfer_ownership_to_current_owner_is_idempotent() -> None:
    """Selecting the current Owner does not demote and promote the same member."""
    owner = _workspace_user(role=WorkspaceUserRole.OWNER)
    user_repository = AsyncMock(spec=WorkspaceUserRepository)
    workspace_repository = AsyncMock(spec=WorkspaceRepository)
    workspace_repository.acquire_ownership_mutation.return_value = _workspace()
    user_repository.get.return_value = owner
    user_repository.get_owner_by_workspace.return_value = owner
    repository = _repository(
        user_repository=user_repository,
        workspace_repository=workspace_repository,
    )

    result = await repository.transfer_ownership(
        workspace_id="workspace-1",
        new_owner_workspace_user_id=owner.id,
    )

    assert isinstance(result, Success)
    assert result.value.owner.id == owner.id
    assert result.value.changed is False
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
    _raw_session = AsyncMock(spec=AsyncSession)
    session = ReadWriteSession(_raw_session)
    user_repository = AsyncMock(spec=WorkspaceUserRepository)
    workspace_repository = AsyncMock(spec=WorkspaceRepository)
    workspace_repository.acquire_ownership_mutation.return_value = _workspace()
    user_repository.get.return_value = new_owner
    user_repository.get_owner_by_workspace.return_value = current_owner
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
    repository = _repository(
        user_repository=user_repository,
        workspace_repository=workspace_repository,
        session=session,
    )

    result = await repository.transfer_ownership(
        workspace_id="workspace-1",
        new_owner_workspace_user_id=new_owner.id,
    )

    assert isinstance(result, Failure)
    assert isinstance(result.error, NotFound)
    _raw_session.rollback.assert_awaited_once()


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
    async def session_manager() -> AsyncGenerator[WriteSession, None]:
        async with AsyncSession(rdb_engine, expire_on_commit=False) as _raw_session:
            session = ReadWriteSession(_raw_session)
            try:
                yield session
            except Exception:
                await session.write_session.rollback()
                raise
            else:
                await session.write_session.commit()

    try:
        async with AsyncSession(
            rdb_engine, expire_on_commit=False
        ) as _raw_setup_session:
            setup_session = ReadWriteSession(_raw_setup_session)
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
            await setup_session.write_session.commit()

        repository = WorkspaceUserOperationRepository(
            user_repository=WorkspaceUserRepository(),
            workspace_repository=WorkspaceRepository(),
            owner_lifecycle_repository=OwnerLifecycleRepository(),
            session_manager=session_manager,
        )
        results = await asyncio.gather(
            *(
                repository.create_by_handle(
                    workspace_handle=workspace_handle,
                    user_id=user_id,
                    name=f"Owner {index}",
                    role=WorkspaceUserRole.OWNER,
                )
                for index, user_id in enumerate(user_ids)
            )
        )

        successes = [result for result in results if isinstance(result, Success)]
        failures = [result for result in results if isinstance(result, Failure)]
        assert len(successes) == 1
        assert len(failures) == 1
        assert isinstance(failures[0].error, WorkspaceUserOwnerAlreadyExists)
    finally:
        async with AsyncSession(
            rdb_engine, expire_on_commit=False
        ) as _raw_cleanup_session:
            cleanup_session = ReadWriteSession(_raw_cleanup_session)
            if workspace_id is not None:
                await cleanup_session.write_session.execute(
                    sa.delete(RDBWorkspace).where(RDBWorkspace.id == workspace_id)
                )
            for user_id in user_ids:
                await UserRepository().delete(cleanup_session, user_id)
            await cleanup_session.write_session.commit()
