"""WorkspaceUser repository tests."""

from azcommon.result import Failure, Success
from sqlalchemy.ext.asyncio import AsyncSession

from azents.repos.user import UserRepository as UserRepo
from azents.repos.user.data import UserCreate
from azents.repos.workspace import WorkspaceRepository
from azents.repos.workspace.data import WorkspaceCreate
from azents.repos.workspace_user.data import WorkspaceUserRole

from . import WorkspaceUserRepository
from .data import (
    NotFound,
    WorkspaceNotFound,
    WorkspaceUserCreate,
    WorkspaceUserUpdate,
)


async def _create_workspace(session: AsyncSession) -> str:
    """Create Workspace for tests and return internal ID."""
    repo = WorkspaceRepository()
    result = await repo.create(
        session, WorkspaceCreate(name="Test workspace", handle="user-test-ws")
    )
    assert isinstance(result, Success)
    workspace_id = await repo.resolve_id(session, "user-test-ws")
    assert workspace_id is not None
    return workspace_id


async def _create_user(
    session: AsyncSession, email: str = "user-test@example.com"
) -> str:
    """Create User for tests and return user_id."""
    repo = UserRepo()
    user = await repo.create(session, UserCreate(email=email))
    return user.id


class TestWorkspaceUserRepository:
    """WorkspaceUserRepository tests."""

    async def test_create(self, rdb_session: AsyncSession) -> None:
        """Create WorkspaceUser."""
        # Given: create Workspace + User
        workspace_id = await _create_workspace(rdb_session)
        created_user_id = await _create_user(rdb_session)
        repo = WorkspaceUserRepository()

        # When: create WorkspaceUser
        result = await repo.create(
            rdb_session,
            WorkspaceUserCreate(
                workspace_id=workspace_id,
                user_id=created_user_id,
                name="Test user",
                role=WorkspaceUserRole.OWNER,
            ),
        )

        # Then: check success
        assert isinstance(result, Success)
        user = result.value
        assert user.workspace_id == workspace_id
        assert user.user_id == created_user_id
        assert user.name == "Test user"
        assert user.role == WorkspaceUserRole.OWNER
        assert user.id
        assert user.created_at
        assert user.updated_at

    async def test_create_workspace_not_found(self, rdb_session: AsyncSession) -> None:
        """Creating WorkspaceUser in nonexistent Workspace returns NotFound."""
        # Given: nonexistent workspace_id
        created_user_id = await _create_user(
            rdb_session, email="ws-notfound@example.com"
        )
        repo = WorkspaceUserRepository()

        # When: create attempt
        result = await repo.create(
            rdb_session,
            WorkspaceUserCreate(
                workspace_id="nonexistent",
                user_id=created_user_id,
                name="user",
                role=WorkspaceUserRole.MEMBER,
            ),
        )

        # Then: WorkspaceNotFound error
        assert isinstance(result, Failure)
        assert isinstance(result.error, WorkspaceNotFound)
        assert result.error.workspace_id == "nonexistent"

    async def test_get(self, rdb_session: AsyncSession) -> None:
        """Fetch WorkspaceUser by ID."""
        # Given: WorkspaceUser create
        workspace_id = await _create_workspace(rdb_session)
        created_user_id = await _create_user(rdb_session, email="get-test@example.com")
        repo = WorkspaceUserRepository()
        create_result = await repo.create(
            rdb_session,
            WorkspaceUserCreate(
                workspace_id=workspace_id,
                user_id=created_user_id,
                name="fetch user",
                role=WorkspaceUserRole.MEMBER,
            ),
        )
        assert isinstance(create_result, Success)
        user_id = create_result.value.id

        # When: fetch by ID
        user = await repo.get(rdb_session, user_id)

        # Then: fetch success
        assert user is not None
        assert user.id == user_id
        assert user.name == "fetch user"

    async def test_get_not_found(self, rdb_session: AsyncSession) -> None:
        """Return None when fetching by nonexistent ID."""
        # Given: nonexistent ID
        repo = WorkspaceUserRepository()

        # When: fetch
        user = await repo.get(rdb_session, "nonexistent")

        # Then: None
        assert user is None

    async def test_list_by_workspace(self, rdb_session: AsyncSession) -> None:
        """Fetch WorkspaceUser list in Workspace."""
        # Given: Workspace multiple user create
        workspace_id = await _create_workspace(rdb_session)
        gu1 = await _create_user(rdb_session, email="list-1@example.com")
        gu2 = await _create_user(rdb_session, email="list-2@example.com")
        repo = WorkspaceUserRepository()
        await repo.create(
            rdb_session,
            WorkspaceUserCreate(
                workspace_id=workspace_id,
                user_id=gu1,
                name="user 1",
                role=WorkspaceUserRole.OWNER,
            ),
        )
        await repo.create(
            rdb_session,
            WorkspaceUserCreate(
                workspace_id=workspace_id,
                user_id=gu2,
                name="user 2",
                role=WorkspaceUserRole.MEMBER,
            ),
        )

        # When: fetch list
        user_list = await repo.list_by_workspace(rdb_session, workspace_id)

        # Then: two users exist
        assert len(user_list.items) == 2

    async def test_update(self, rdb_session: AsyncSession) -> None:
        """WorkspaceUser Update."""
        # Given: WorkspaceUser create
        workspace_id = await _create_workspace(rdb_session)
        created_user_id = await _create_user(
            rdb_session, email="update-test@example.com"
        )
        repo = WorkspaceUserRepository()
        create_result = await repo.create(
            rdb_session,
            WorkspaceUserCreate(
                workspace_id=workspace_id,
                user_id=created_user_id,
                name="Before update",
                role=WorkspaceUserRole.MEMBER,
            ),
        )
        assert isinstance(create_result, Success)
        user_id = create_result.value.id

        # When: name update
        result = await repo.update(
            rdb_session, user_id, WorkspaceUserUpdate(name="After update")
        )

        # Then: update success
        assert isinstance(result, Success)
        assert result.value.name == "After update"

    async def test_update_not_found(self, rdb_session: AsyncSession) -> None:
        """nonexistent WorkspaceUser when updating return NotFound."""
        # Given: nonexistent ID
        repo = WorkspaceUserRepository()

        # When: attempt update
        result = await repo.update(
            rdb_session, "nonexistent", WorkspaceUserUpdate(name="update")
        )

        # Then: NotFound error
        assert isinstance(result, Failure)
        assert isinstance(result.error, NotFound)

    async def test_update_empty(self, rdb_session: AsyncSession) -> None:
        """empty update data when existing data as-is return."""
        # Given: WorkspaceUser create
        workspace_id = await _create_workspace(rdb_session)
        created_user_id = await _create_user(
            rdb_session, email="empty-update@example.com"
        )
        repo = WorkspaceUserRepository()
        create_result = await repo.create(
            rdb_session,
            WorkspaceUserCreate(
                workspace_id=workspace_id,
                user_id=created_user_id,
                name="empty update",
                role=WorkspaceUserRole.MEMBER,
            ),
        )
        assert isinstance(create_result, Success)
        user_id = create_result.value.id

        # When: empty update
        result = await repo.update(rdb_session, user_id, WorkspaceUserUpdate())

        # Then: existing data return
        assert isinstance(result, Success)
        assert result.value.name == "empty update"

    async def test_delete(self, rdb_session: AsyncSession) -> None:
        """WorkspaceUser Delete."""
        # Given: WorkspaceUser create
        workspace_id = await _create_workspace(rdb_session)
        created_user_id = await _create_user(
            rdb_session, email="delete-test@example.com"
        )
        repo = WorkspaceUserRepository()
        create_result = await repo.create(
            rdb_session,
            WorkspaceUserCreate(
                workspace_id=workspace_id,
                user_id=created_user_id,
                name="Delete target",
                role=WorkspaceUserRole.MEMBER,
            ),
        )
        assert isinstance(create_result, Success)
        user_id = create_result.value.id

        # When: delete
        await repo.delete(rdb_session, user_id)

        # Then: None when fetching
        user = await repo.get(rdb_session, user_id)
        assert user is None
