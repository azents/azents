"""Workspace repository tests."""

from azcommon.result import Failure, Success
from sqlalchemy.ext.asyncio import AsyncSession

from . import WorkspaceRepository
from .data import HandleConflict, NotFound, WorkspaceCreate, WorkspaceUpdate


class TestWorkspaceRepository:
    """WorkspaceRepository tests."""

    async def test_create(self, rdb_session: AsyncSession) -> None:
        """Create Workspace."""
        # Given: prepare create data
        repo = WorkspaceRepository()
        create = WorkspaceCreate(name="Test workspace", handle="test-ws")

        # When: create
        result = await repo.create(rdb_session, create)

        # Then: check success
        assert isinstance(result, Success)
        workspace = result.value
        assert workspace.name == "Test workspace"
        assert workspace.handle == "test-ws"
        assert workspace.created_at
        assert workspace.updated_at

    async def test_create_duplicate_handle(self, rdb_session: AsyncSession) -> None:
        """duplicate handle Workspace when creating HandleConflict return."""
        # Given: same handle Workspace already exist
        repo = WorkspaceRepository()
        create = WorkspaceCreate(name="workspace 1", handle="duplicate-handle")
        await repo.create(rdb_session, create)

        # When: create again with same handle
        result = await repo.create(
            rdb_session,
            WorkspaceCreate(name="workspace 2", handle="duplicate-handle"),
        )

        # Then: HandleConflict error
        assert isinstance(result, Failure)
        assert isinstance(result.error, HandleConflict)
        assert result.error.handle == "duplicate-handle"

    async def test_get_by_handle(self, rdb_session: AsyncSession) -> None:
        """handle Workspace fetch."""
        # Given: Workspace create
        repo = WorkspaceRepository()
        create_result = await repo.create(
            rdb_session, WorkspaceCreate(name="handle fetch", handle="by-handle-test")
        )
        assert isinstance(create_result, Success)

        # When: handle fetch
        workspace = await repo.get_by_handle(rdb_session, "by-handle-test")

        # Then: fetch success
        assert workspace is not None
        assert workspace.handle == "by-handle-test"
        assert workspace.name == "handle fetch"

    async def test_get_by_handle_not_found(self, rdb_session: AsyncSession) -> None:
        """nonexistent handle fetch when None return."""
        # Given: nonexistent handle
        repo = WorkspaceRepository()

        # When: fetch
        workspace = await repo.get_by_handle(rdb_session, "nonexistent-handle")

        # Then: None
        assert workspace is None

    async def test_list_all(self, rdb_session: AsyncSession) -> None:
        """Fetch all Workspace list."""
        # Given: multiple Workspace create
        repo = WorkspaceRepository()
        await repo.create(
            rdb_session, WorkspaceCreate(name="list 1", handle="list-test-1")
        )
        await repo.create(
            rdb_session, WorkspaceCreate(name="list 2", handle="list-test-2")
        )

        # When: fetch full list
        workspace_list = await repo.list_all(rdb_session)

        # Then: two or more exist
        assert len(workspace_list.items) >= 2

    async def test_update_by_handle(self, rdb_session: AsyncSession) -> None:
        """Workspace Update."""
        # Given: Workspace create
        repo = WorkspaceRepository()
        create_result = await repo.create(
            rdb_session, WorkspaceCreate(name="Before update", handle="update-test")
        )
        assert isinstance(create_result, Success)

        # When: name update
        update = WorkspaceUpdate(name="After update")
        result = await repo.update_by_handle(rdb_session, "update-test", update)

        # Then: update success
        assert isinstance(result, Success)
        assert result.value.name == "After update"
        assert result.value.handle == "update-test"

    async def test_update_by_handle_not_found(self, rdb_session: AsyncSession) -> None:
        """nonexistent Workspace when updating return NotFound."""
        # Given: nonexistent handle
        repo = WorkspaceRepository()

        # When: attempt update
        update = WorkspaceUpdate(name="update")
        result = await repo.update_by_handle(rdb_session, "nonexistent", update)

        # Then: NotFound error
        assert isinstance(result, Failure)
        assert isinstance(result.error, NotFound)

    async def test_update_by_handle_empty(self, rdb_session: AsyncSession) -> None:
        """empty update data when existing data as-is return."""
        # Given: Workspace create
        repo = WorkspaceRepository()
        create_result = await repo.create(
            rdb_session, WorkspaceCreate(name="empty update", handle="empty-update")
        )
        assert isinstance(create_result, Success)

        # When: empty update
        result = await repo.update_by_handle(
            rdb_session, "empty-update", WorkspaceUpdate()
        )

        # Then: existing data return
        assert isinstance(result, Success)
        assert result.value.name == "empty update"

    async def test_update_by_handle_duplicate_handle(
        self, rdb_session: AsyncSession
    ) -> None:
        """when updating duplicate handle HandleConflict return."""
        # Given: two Workspace create
        repo = WorkspaceRepository()
        await repo.create(
            rdb_session, WorkspaceCreate(name="existing", handle="existing-handle")
        )
        create_result = await repo.create(
            rdb_session,
            WorkspaceCreate(name="Update target", handle="to-update-handle"),
        )
        assert isinstance(create_result, Success)

        # When: attempt update to existing handle
        result = await repo.update_by_handle(
            rdb_session,
            "to-update-handle",
            WorkspaceUpdate(handle="existing-handle"),
        )

        # Then: HandleConflict error
        assert isinstance(result, Failure)
        assert isinstance(result.error, HandleConflict)

    async def test_resolve_id(self, rdb_session: AsyncSession) -> None:
        """Fetch internal ID by handle"""
        # Given: Workspace create
        repo = WorkspaceRepository()
        await repo.create(
            rdb_session, WorkspaceCreate(name="ID fetch", handle="resolve-id-test")
        )

        # When: call resolve_id
        workspace_id = await repo.resolve_id(rdb_session, "resolve-id-test")

        # Then: return internal ID
        assert workspace_id is not None
        assert len(workspace_id) == 32  # UUID7 hex

    async def test_resolve_id_not_found(self, rdb_session: AsyncSession) -> None:
        """nonexistent handle resolve_id when None return."""
        # Given: nonexistent handle
        repo = WorkspaceRepository()

        # When: call resolve_id
        workspace_id = await repo.resolve_id(rdb_session, "nonexistent")

        # Then: None
        assert workspace_id is None

    async def test_delete_by_handle(self, rdb_session: AsyncSession) -> None:
        """handle Workspace Delete."""
        # Given: Workspace create
        repo = WorkspaceRepository()
        create_result = await repo.create(
            rdb_session, WorkspaceCreate(name="Delete target", handle="delete-test")
        )
        assert isinstance(create_result, Success)

        # When: delete
        await repo.delete_by_handle(rdb_session, "delete-test")

        # Then: None when fetching
        workspace = await repo.get_by_handle(rdb_session, "delete-test")
        assert workspace is None
