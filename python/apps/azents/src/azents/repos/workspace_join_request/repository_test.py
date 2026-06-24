"""WorkspaceJoinRequest repository tests."""

from azcommon.result import Failure, Success
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import JoinRequestStatus
from azents.repos.user import UserRepository
from azents.repos.user.data import UserCreate
from azents.repos.workspace import WorkspaceRepository
from azents.repos.workspace.data import WorkspaceCreate

from . import WorkspaceJoinRequestRepository
from .data import NotFound, WorkspaceJoinRequestCreate, WorkspaceJoinRequestUpdate


async def _create_workspace(session: AsyncSession, handle: str = "jr-test-ws") -> str:
    """Create Workspace for tests and return internal ID."""
    repo = WorkspaceRepository()
    result = await repo.create(
        session, WorkspaceCreate(name="Test workspace", handle=handle)
    )
    assert isinstance(result, Success)
    workspace_id = await repo.resolve_id(session, handle)
    assert workspace_id is not None
    return workspace_id


async def _create_user(
    session: AsyncSession, email: str = "jr-test@example.com"
) -> str:
    """Create User for tests and return user_id."""
    repo = UserRepository()
    user = await repo.create(session, UserCreate(email=email))
    return user.id


class TestWorkspaceJoinRequestRepository:
    """WorkspaceJoinRequestRepository tests."""

    async def test_create_or_rerequest_new(self, rdb_session: AsyncSession) -> None:
        """Create new join request."""
        # Given
        workspace_id = await _create_workspace(rdb_session, "jr-create-ws")
        user_id = await _create_user(rdb_session, "jr-create@example.com")
        repo = WorkspaceJoinRequestRepository()

        # When
        jr = await repo.create_or_rerequest(
            rdb_session,
            WorkspaceJoinRequestCreate(
                workspace_id=workspace_id,
                user_id=user_id,
                message="I want to join",
            ),
        )

        # Then
        assert jr.workspace_id == workspace_id
        assert jr.user_id == user_id
        assert jr.message == "I want to join"
        assert jr.status == JoinRequestStatus.PENDING
        assert jr.created_at
        assert jr.updated_at

    async def test_create_or_rerequest_upsert_muted(
        self, rdb_session: AsyncSession
    ) -> None:
        """Update existing muted request to pending."""
        # Given: create join request then mute
        workspace_id = await _create_workspace(rdb_session, "jr-upsert-ws")
        user_id = await _create_user(rdb_session, "jr-upsert@example.com")
        repo = WorkspaceJoinRequestRepository()

        jr = await repo.create_or_rerequest(
            rdb_session,
            WorkspaceJoinRequestCreate(
                workspace_id=workspace_id,
                user_id=user_id,
                message="First request",
            ),
        )
        await repo.update(rdb_session, jr.id, {"status": JoinRequestStatus.MUTED})

        # When: re-request
        updated = await repo.create_or_rerequest(
            rdb_session,
            WorkspaceJoinRequestCreate(
                workspace_id=workspace_id,
                user_id=user_id,
                message="Request again",
            ),
        )

        # Then: same record changes to pending + message update
        assert updated.id == jr.id
        assert updated.status == JoinRequestStatus.PENDING
        assert updated.message == "Request again"

    async def test_get(self, rdb_session: AsyncSession) -> None:
        """Fetch join request by ID."""
        # Given
        workspace_id = await _create_workspace(rdb_session, "jr-get-ws")
        user_id = await _create_user(rdb_session, "jr-get@example.com")
        repo = WorkspaceJoinRequestRepository()
        jr = await repo.create_or_rerequest(
            rdb_session,
            WorkspaceJoinRequestCreate(workspace_id=workspace_id, user_id=user_id),
        )

        # When
        found = await repo.get(rdb_session, jr.id)

        # Then
        assert found is not None
        assert found.id == jr.id

    async def test_get_not_found(self, rdb_session: AsyncSession) -> None:
        """Return None when fetching by nonexistent ID."""
        repo = WorkspaceJoinRequestRepository()
        assert await repo.get(rdb_session, "nonexistent") is None

    async def test_get_by_workspace_and_user(self, rdb_session: AsyncSession) -> None:
        """workspace + user fetch."""
        # Given
        workspace_id = await _create_workspace(rdb_session, "jr-byws-ws")
        user_id = await _create_user(rdb_session, "jr-byws@example.com")
        repo = WorkspaceJoinRequestRepository()
        await repo.create_or_rerequest(
            rdb_session,
            WorkspaceJoinRequestCreate(workspace_id=workspace_id, user_id=user_id),
        )

        # When
        found = await repo.get_by_workspace_and_user(rdb_session, workspace_id, user_id)

        # Then
        assert found is not None
        assert found.workspace_id == workspace_id
        assert found.user_id == user_id

    async def test_list_by_workspace(self, rdb_session: AsyncSession) -> None:
        """Fetch workspace join request list."""
        # Given
        workspace_id = await _create_workspace(rdb_session, "jr-list-ws")
        user1_id = await _create_user(rdb_session, "jr-list1@example.com")
        user2_id = await _create_user(rdb_session, "jr-list2@example.com")
        repo = WorkspaceJoinRequestRepository()
        await repo.create_or_rerequest(
            rdb_session,
            WorkspaceJoinRequestCreate(workspace_id=workspace_id, user_id=user1_id),
        )
        await repo.create_or_rerequest(
            rdb_session,
            WorkspaceJoinRequestCreate(workspace_id=workspace_id, user_id=user2_id),
        )

        # When
        result = await repo.list_by_workspace(rdb_session, workspace_id)

        # Then
        assert result.total == 2
        assert len(result.items) == 2

    async def test_list_by_workspace_with_status_filter(
        self, rdb_session: AsyncSession
    ) -> None:
        """Fetch list filtered by status."""
        # Given
        workspace_id = await _create_workspace(rdb_session, "jr-filter-ws")
        user1_id = await _create_user(rdb_session, "jr-filter1@example.com")
        user2_id = await _create_user(rdb_session, "jr-filter2@example.com")
        repo = WorkspaceJoinRequestRepository()

        await repo.create_or_rerequest(
            rdb_session,
            WorkspaceJoinRequestCreate(workspace_id=workspace_id, user_id=user1_id),
        )
        jr2 = await repo.create_or_rerequest(
            rdb_session,
            WorkspaceJoinRequestCreate(workspace_id=workspace_id, user_id=user2_id),
        )
        await repo.update(rdb_session, jr2.id, {"status": JoinRequestStatus.MUTED})

        # When: pending only fetch
        result = await repo.list_by_workspace(
            rdb_session, workspace_id, status=JoinRequestStatus.PENDING
        )

        # Then
        assert result.total == 1
        assert result.items[0].status == JoinRequestStatus.PENDING

    async def test_update(self, rdb_session: AsyncSession) -> None:
        """join request Update."""
        # Given
        workspace_id = await _create_workspace(rdb_session, "jr-update-ws")
        user_id = await _create_user(rdb_session, "jr-update@example.com")
        repo = WorkspaceJoinRequestRepository()
        jr = await repo.create_or_rerequest(
            rdb_session,
            WorkspaceJoinRequestCreate(workspace_id=workspace_id, user_id=user_id),
        )

        # When
        result = await repo.update(
            rdb_session,
            jr.id,
            WorkspaceJoinRequestUpdate(status=JoinRequestStatus.MUTED),
        )

        # Then
        assert isinstance(result, Success)
        assert result.value.status == JoinRequestStatus.MUTED

    async def test_update_not_found(self, rdb_session: AsyncSession) -> None:
        """nonexistent join request when updating return NotFound."""
        repo = WorkspaceJoinRequestRepository()
        result = await repo.update(
            rdb_session,
            "nonexistent",
            WorkspaceJoinRequestUpdate(status=JoinRequestStatus.MUTED),
        )
        assert isinstance(result, Failure)
        assert isinstance(result.error, NotFound)

    async def test_delete(self, rdb_session: AsyncSession) -> None:
        """join request Delete."""
        # Given
        workspace_id = await _create_workspace(rdb_session, "jr-delete-ws")
        user_id = await _create_user(rdb_session, "jr-delete@example.com")
        repo = WorkspaceJoinRequestRepository()
        jr = await repo.create_or_rerequest(
            rdb_session,
            WorkspaceJoinRequestCreate(workspace_id=workspace_id, user_id=user_id),
        )

        # When
        await repo.delete(rdb_session, jr.id)

        # Then
        assert await repo.get(rdb_session, jr.id) is None
