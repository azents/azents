"""WorkspaceUser repository tests."""

import asyncio
from contextlib import suppress
from uuid import uuid4

import pytest
import sqlalchemy as sa
from azcommon.result import Failure, Success
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from azents.core.enums import WorkspaceUserRole
from azents.core.workspace import WorkspaceCreate
from azents.rdb.models.workspace import RDBWorkspace
from azents.rdb.models.workspace_user import RDBWorkspaceUser
from azents.rdb.session_capabilities import (
    ReadOnlySession,
    ReadWriteSession,
    WriteSession,
)
from azents.repos.user import UserRepository as UserRepo
from azents.repos.user.data import UserCreate
from azents.repos.workspace import WorkspaceRepository

from . import WorkspaceUserRepository
from .data import (
    NotFound,
    UserNotFound,
    WorkspaceNotFound,
    WorkspaceUserAlreadyExists,
    WorkspaceUserCreate,
    WorkspaceUserUpdate,
)


async def _create_workspace(session: WriteSession) -> str:
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
    session: WriteSession, email: str = "user-test@example.com"
) -> str:
    """Create User for tests and return user_id."""
    repo = UserRepo()
    user = await repo.create(session, UserCreate(email=email))
    return user.id


async def _cleanup_committed_membership_fixture(
    session: WriteSession,
    *,
    workspace_id: str | None,
    user_id: str | None,
) -> None:
    """Remove the committed fixture used by the membership lock test."""
    if workspace_id is not None:
        await session.write_session.execute(
            sa.delete(RDBWorkspace).where(RDBWorkspace.id == workspace_id)
        )
    if user_id is not None:
        await UserRepo().delete(session, user_id)


class TestWorkspaceUserRepository:
    """WorkspaceUserRepository tests."""

    async def test_read_tolerates_uncommitted_delete_without_waiting(
        self,
        rdb_engine: AsyncEngine,
        latest_db_schema: None,
    ) -> None:
        """An ordinary read tolerates lag without waiting for a held writer."""
        del latest_db_schema
        suffix = uuid4().hex[:8]
        repo = WorkspaceUserRepository()
        workspace_id: str | None = None
        user_id: str | None = None

        try:
            async with AsyncSession(
                rdb_engine,
                expire_on_commit=False,
            ) as _raw_setup_session:
                setup_session = ReadWriteSession(_raw_setup_session)
                workspace = await WorkspaceRepository().create(
                    setup_session,
                    WorkspaceCreate(
                        name="Membership lock test",
                        handle=f"membership-lock-{suffix}",
                    ),
                )
                assert isinstance(workspace, Success)
                workspace_id = await WorkspaceRepository().resolve_id(
                    setup_session,
                    f"membership-lock-{suffix}",
                )
                assert workspace_id is not None
                user_id = await _create_user(
                    setup_session,
                    email=f"membership-lock-{suffix}@example.com",
                )
                membership = await repo.create(
                    setup_session,
                    WorkspaceUserCreate(
                        workspace_id=workspace_id,
                        user_id=user_id,
                        name="Membership lock user",
                        role=WorkspaceUserRole.MEMBER,
                    ),
                )
                assert isinstance(membership, Success)
                await setup_session.write_session.commit()

            async with AsyncSession(
                rdb_engine,
                expire_on_commit=False,
            ) as _raw_delete_session:
                delete_session = ReadWriteSession(_raw_delete_session)
                await repo.delete(delete_session, membership.value.id)
                delete_pid = await delete_session.read_session.scalar(
                    sa.text("SELECT pg_backend_pid()")
                )
                assert isinstance(delete_pid, int)
                async with AsyncSession(
                    rdb_engine.execution_options(postgresql_readonly=True),
                    expire_on_commit=False,
                ) as _raw_admission_session:
                    admission_session = ReadWriteSession(_raw_admission_session)
                    admission_pid = await admission_session.read_session.scalar(
                        sa.text("SELECT pg_backend_pid()")
                    )
                    assert isinstance(admission_pid, int)
                    assert delete_pid != admission_pid

                    reader = ReadOnlySession(admission_session.read_session)
                    admitted = await asyncio.wait_for(
                        repo.get_by_workspace_and_user(
                            reader,
                            workspace_id=workspace_id,
                            user_id=user_id,
                        ),
                        timeout=5,
                    )
                    # A deletion not yet committed may lag in the reader's MVCC view.
                    assert admitted is not None
                    await admission_session.write_session.rollback()
                    await delete_session.write_session.commit()
                    after_commit = await repo.get_by_workspace_and_user(
                        reader,
                        workspace_id=workspace_id,
                        user_id=user_id,
                    )
                    assert after_commit is None
                    await admission_session.write_session.rollback()
        finally:
            async with AsyncSession(
                rdb_engine,
                expire_on_commit=False,
            ) as _raw_cleanup_session:
                cleanup_session = ReadWriteSession(_raw_cleanup_session)
                await _cleanup_committed_membership_fixture(
                    cleanup_session,
                    workspace_id=workspace_id,
                    user_id=user_id,
                )
                await cleanup_session.write_session.commit()

    async def test_create(self, rdb_session: WriteSession) -> None:
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

    async def test_create_duplicate_membership_returns_conflict(
        self, rdb_session: WriteSession
    ) -> None:
        """Duplicate Workspace membership maps the exact unique constraint."""
        workspace_id = await _create_workspace(rdb_session)
        created_user_id = await _create_user(
            rdb_session, email="duplicate-membership@example.com"
        )
        repo = WorkspaceUserRepository()
        create = WorkspaceUserCreate(
            workspace_id=workspace_id,
            user_id=created_user_id,
            name="Duplicate user",
            role=WorkspaceUserRole.MEMBER,
        )
        first = await repo.create(rdb_session, create)
        assert isinstance(first, Success)

        result = await repo.create_with_conflict(rdb_session, create)

        assert isinstance(result, Failure)
        assert isinstance(result.error, WorkspaceUserAlreadyExists)
        assert result.error.workspace_id == workspace_id
        assert result.error.user_id == created_user_id

    async def test_create_with_conflict_user_not_found(
        self, rdb_session: WriteSession
    ) -> None:
        """Admin creation maps a missing global User before deferred FK commit."""
        workspace_id = await _create_workspace(rdb_session)
        repo = WorkspaceUserRepository()

        result = await repo.create_with_conflict(
            rdb_session,
            WorkspaceUserCreate(
                workspace_id=workspace_id,
                user_id="missing-user",
                name="Missing user",
                role=WorkspaceUserRole.MEMBER,
            ),
        )

        assert isinstance(result, Failure)
        assert isinstance(result.error, UserNotFound)
        assert result.error.user_id == "missing-user"

    async def test_create_workspace_not_found(self, rdb_session: WriteSession) -> None:
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

    async def test_get(self, rdb_session: WriteSession) -> None:
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

    async def test_get_not_found(self, rdb_session: WriteSession) -> None:
        """Return None when fetching by nonexistent ID."""
        # Given: nonexistent ID
        repo = WorkspaceUserRepository()

        # When: fetch
        user = await repo.get(rdb_session, "nonexistent")

        # Then: None
        assert user is None

    async def test_list_by_workspace(self, rdb_session: WriteSession) -> None:
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

    async def test_update(self, rdb_session: WriteSession) -> None:
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

    async def test_update_not_found(self, rdb_session: WriteSession) -> None:
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

    async def test_update_empty(self, rdb_session: WriteSession) -> None:
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

    async def test_delete(self, rdb_session: WriteSession) -> None:
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


@pytest.mark.parametrize("operation", ["update", "delete"])
async def test_non_owner_write_loses_to_committed_owner_transfer(
    rdb_engine: AsyncEngine,
    latest_db_schema: None,
    operation: str,
) -> None:
    """Actual SQL predicates reject an obsolete writer after its row wait."""
    del latest_db_schema
    suffix = uuid4().hex[:8]
    repo = WorkspaceUserRepository()
    workspace_id: str | None = None
    user_id: str | None = None
    task: asyncio.Task[object] | None = None
    try:
        async with AsyncSession(rdb_engine, expire_on_commit=False) as raw:
            setup = ReadWriteSession(raw)
            workspace_id = await _create_workspace(setup)
            user_id = await _create_user(
                setup, email=f"owner-race-{suffix}@example.com"
            )
            result = await repo.create(
                setup,
                WorkspaceUserCreate(
                    workspace_id=workspace_id,
                    user_id=user_id,
                    name="Race member",
                    role=WorkspaceUserRole.MEMBER,
                ),
            )
            assert isinstance(result, Success)
            membership_id = result.value.id
            await raw.commit()
        async with (
            AsyncSession(rdb_engine) as owner_raw,
            AsyncSession(rdb_engine) as writer_raw,
        ):
            writer = ReadWriteSession(writer_raw)
            # Simulate the obsolete ordinary description before promotion.
            stale = await repo.get(writer, membership_id)
            assert stale is not None and stale.role is WorkspaceUserRole.MEMBER
            await owner_raw.execute(
                sa.update(RDBWorkspaceUser)
                .where(RDBWorkspaceUser.id == membership_id)
                .values(role=WorkspaceUserRole.OWNER)
            )
            owner_pid = await owner_raw.scalar(sa.text("SELECT pg_backend_pid()"))
            writer_pid = await writer_raw.scalar(sa.text("SELECT pg_backend_pid()"))
            assert isinstance(owner_pid, int) and isinstance(writer_pid, int)

            async def obsolete_mutation() -> object:
                if operation == "update":
                    return await repo.update_non_owner_role(
                        writer, membership_id, WorkspaceUserRole.MANAGER
                    )
                return await repo.delete_non_owner(writer, membership_id)

            task = asyncio.create_task(obsolete_mutation())
            async with asyncio.timeout(5), AsyncSession(rdb_engine) as observer:
                while True:
                    blockers = await observer.scalar(
                        sa.text("SELECT pg_blocking_pids(:pid)"), {"pid": writer_pid}
                    )
                    if owner_pid in blockers:
                        break
                    assert not task.done()
            await owner_raw.commit()
            assert await asyncio.wait_for(task, timeout=5) is None
            await writer_raw.commit()
        async with AsyncSession(rdb_engine) as raw:
            current = await repo.get(ReadOnlySession(raw), membership_id)
            assert current is not None and current.role is WorkspaceUserRole.OWNER
    finally:
        if task is not None and not task.done():
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        async with AsyncSession(rdb_engine) as raw:
            await _cleanup_committed_membership_fixture(
                ReadWriteSession(raw),
                workspace_id=workspace_id,
                user_id=user_id,
            )
            await raw.commit()
