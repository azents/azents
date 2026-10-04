"""Session repository tests."""

import asyncio
import datetime
from contextlib import suppress
from uuid import uuid4

import sqlalchemy as sa
from azcommon.datetime import tznow
from azcommon.result import Failure, Success
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from azents.rdb.models.session import RDBSession
from azents.rdb.models.user import RDBUser
from azents.rdb.session_capabilities import ReadWriteSession, WriteSession
from azents.repos.user import UserRepository
from azents.repos.user.data import UserCreate

from . import SessionRepository
from .data import NotFound, SessionCreate, TokenMatch


async def _create_user(
    session: WriteSession,
    email: str = "session@example.com",
) -> str:
    """Create User for tests and return user_id."""
    user_repo = UserRepository()
    user = await user_repo.create(
        session,
        UserCreate(email=email),
    )
    return user.id


class TestSessionRepository:
    """SessionRepository tests."""

    async def test_create(self, rdb_session: WriteSession) -> None:
        """Create Session."""
        # Given: create User
        user_id = await _create_user(rdb_session, email="sess-create@example.com")
        repo = SessionRepository()
        now = tznow()
        expires_at = now + datetime.timedelta(hours=1)

        # When: create Session
        sess = await repo.create(
            rdb_session,
            SessionCreate(
                user_id=user_id,
                refresh_token="refresh-token-create",
                expires_at=expires_at,
                user_agent="test-agent",
                ip_address="127.0.0.1",
            ),
        )

        # Then: check success
        assert sess.id
        assert sess.user_id == user_id
        assert sess.refresh_token == "refresh-token-create"
        assert sess.user_agent == "test-agent"
        assert sess.ip_address == "127.0.0.1"
        assert sess.revoked_at is None
        assert sess.prev_refresh_token is None
        assert sess.created_at
        assert sess.updated_at

    async def test_create_for_active_user_rejects_disabled_user(
        self,
        rdb_session: WriteSession,
    ) -> None:
        """Conditional Session creation rejects a disabled User."""
        user_id = await _create_user(
            rdb_session,
            email="sess-create-disabled@example.com",
        )
        await UserRepository().disable_access(
            rdb_session,
            user_id,
            disabled_at=tznow(),
        )
        repo = SessionRepository()

        result = await repo.create_for_active_user(
            rdb_session,
            SessionCreate(
                user_id=user_id,
                refresh_token="disabled-create-token",
                expires_at=tznow() + datetime.timedelta(hours=1),
            ),
        )

        assert isinstance(result, Failure)
        assert isinstance(result.error, NotFound)

    async def test_get(self, rdb_session: WriteSession) -> None:
        """Fetch Session by ID."""
        # Given: create Session
        user_id = await _create_user(rdb_session, email="sess-get@example.com")
        repo = SessionRepository()
        sess = await repo.create(
            rdb_session,
            SessionCreate(
                user_id=user_id,
                refresh_token="refresh-token-get",
                expires_at=tznow() + datetime.timedelta(hours=1),
            ),
        )

        # When: fetch by ID
        found = await repo.get(rdb_session, sess.id)

        # Then: fetch success
        assert found is not None
        assert found.id == sess.id
        assert found.refresh_token == "refresh-token-get"

    async def test_get_not_found(self, rdb_session: WriteSession) -> None:
        """Return None when fetching by nonexistent ID."""
        # Given: nonexistent ID
        repo = SessionRepository()

        # When: fetch
        found = await repo.get(rdb_session, "nonexistent")

        # Then: None
        assert found is None

    async def test_get_by_refresh_token_current(
        self, rdb_session: WriteSession
    ) -> None:
        """Fetching by current refresh token returns CURRENT match."""
        # Given: create Session
        user_id = await _create_user(rdb_session, email="sess-rt-cur@example.com")
        repo = SessionRepository()
        sess = await repo.create(
            rdb_session,
            SessionCreate(
                user_id=user_id,
                refresh_token="current-token",
                expires_at=tznow() + datetime.timedelta(hours=1),
            ),
        )

        # When: fetch by current token
        result = await repo.get_by_refresh_token(rdb_session, "current-token")

        # Then: CURRENT match
        assert result is not None
        found_session, match = result
        assert found_session.id == sess.id
        assert match == TokenMatch.CURRENT

    async def test_get_by_refresh_token_previous(
        self, rdb_session: WriteSession
    ) -> None:
        """Fetching by previous refresh token returns PREVIOUS match."""
        # Given: create Session then rotate token
        user_id = await _create_user(rdb_session, email="sess-rt-prev@example.com")
        repo = SessionRepository()
        sess = await repo.create(
            rdb_session,
            SessionCreate(
                user_id=user_id,
                refresh_token="old-token",
                expires_at=tznow() + datetime.timedelta(hours=1),
            ),
        )

        # Token rotation
        await repo.rotate_refresh_token(
            rdb_session,
            sess.id,
            current_refresh_token="old-token",
            new_refresh_token="new-token",
            new_expires_at=tznow() + datetime.timedelta(hours=2),
        )

        # When: fetch by previous token
        result = await repo.get_by_refresh_token(rdb_session, "old-token")

        # Then: PREVIOUS match
        assert result is not None
        found_session, match = result
        assert found_session.id == sess.id
        assert match == TokenMatch.PREVIOUS

    async def test_get_by_refresh_token_not_found(
        self, rdb_session: WriteSession
    ) -> None:
        """Return None when fetching by nonexistent token."""
        # Given: nonexistent token
        repo = SessionRepository()

        # When: fetch
        result = await repo.get_by_refresh_token(rdb_session, "nonexistent-token")

        # Then: None
        assert result is None

    async def test_revoke(self, rdb_session: WriteSession) -> None:
        """Revoke Session."""
        # Given: create Session
        user_id = await _create_user(rdb_session, email="sess-revoke@example.com")
        repo = SessionRepository()
        sess = await repo.create(
            rdb_session,
            SessionCreate(
                user_id=user_id,
                refresh_token="revoke-token",
                expires_at=tznow() + datetime.timedelta(hours=1),
            ),
        )

        # When: revoke
        result = await repo.revoke(rdb_session, sess.id)

        # Then: revocation success
        assert isinstance(result, Success)
        assert result.value.revoked_at is not None
        assert result.value.is_revoked

    async def test_revoke_not_found(self, rdb_session: WriteSession) -> None:
        """Return NotFound when revoking nonexistent Session."""
        # Given: nonexistent ID
        repo = SessionRepository()

        # When: attempt revocation
        result = await repo.revoke(rdb_session, "nonexistent")

        # Then: NotFound error
        assert isinstance(result, Failure)
        assert isinstance(result.error, NotFound)

    async def test_revoke_all_by_user(self, rdb_session: WriteSession) -> None:
        """Revoke all Sessions for User."""
        # Given: create multiple Sessions for same User
        user_id = await _create_user(rdb_session, email="sess-revall@example.com")
        repo = SessionRepository()
        sess1 = await repo.create(
            rdb_session,
            SessionCreate(
                user_id=user_id,
                refresh_token="revall-token-1",
                expires_at=tznow() + datetime.timedelta(hours=1),
            ),
        )
        await repo.create(
            rdb_session,
            SessionCreate(
                user_id=user_id,
                refresh_token="revall-token-2",
                expires_at=tznow() + datetime.timedelta(hours=1),
            ),
        )
        await repo.create(
            rdb_session,
            SessionCreate(
                user_id=user_id,
                refresh_token="revall-token-3",
                expires_at=tznow() + datetime.timedelta(hours=1),
            ),
        )

        # When: revoke all except one
        count = await repo.revoke_all_by_user(
            rdb_session, user_id, except_session_id=sess1.id
        )

        # Then: two revoked
        assert count == 2
        # Excluded session is active
        remaining = await repo.get(rdb_session, sess1.id)
        assert remaining is not None
        assert remaining.revoked_at is None

    async def test_revoke_all_by_user_no_except(
        self, rdb_session: WriteSession
    ) -> None:
        """Revoke all Sessions without except_session_id."""
        # Given: create multiple Sessions
        user_id = await _create_user(rdb_session, email="sess-revall2@example.com")
        repo = SessionRepository()
        await repo.create(
            rdb_session,
            SessionCreate(
                user_id=user_id,
                refresh_token="revall2-token-1",
                expires_at=tznow() + datetime.timedelta(hours=1),
            ),
        )
        await repo.create(
            rdb_session,
            SessionCreate(
                user_id=user_id,
                refresh_token="revall2-token-2",
                expires_at=tznow() + datetime.timedelta(hours=1),
            ),
        )

        # When: revoke all
        count = await repo.revoke_all_by_user(rdb_session, user_id)

        # Then: two revoked
        assert count == 2

    async def test_rotate_refresh_token(self, rdb_session: WriteSession) -> None:
        """Refresh token rotation."""
        # Given: create Session
        user_id = await _create_user(rdb_session, email="sess-rotate@example.com")
        repo = SessionRepository()
        sess = await repo.create(
            rdb_session,
            SessionCreate(
                user_id=user_id,
                refresh_token="rotate-old",
                expires_at=tznow() + datetime.timedelta(hours=1),
            ),
        )

        # When: rotate token
        new_expires = tznow() + datetime.timedelta(hours=2)
        result = await repo.rotate_refresh_token(
            rdb_session,
            sess.id,
            current_refresh_token="rotate-old",
            new_refresh_token="rotate-new",
            new_expires_at=new_expires,
        )

        # Then: token replacement success
        assert isinstance(result, Success)
        rotated = result.value
        assert rotated.refresh_token == "rotate-new"
        assert rotated.prev_refresh_token == "rotate-old"

    async def test_rotate_refresh_token_not_found(
        self, rdb_session: WriteSession
    ) -> None:
        """Return NotFound when rotating token of nonexistent Session."""
        # Given: nonexistent ID
        repo = SessionRepository()

        # When: attempt rotation
        result = await repo.rotate_refresh_token(
            rdb_session,
            "nonexistent",
            current_refresh_token="any",
            new_refresh_token="any-new",
            new_expires_at=tznow() + datetime.timedelta(hours=1),
        )

        # Then: NotFound error
        assert isinstance(result, Failure)
        assert isinstance(result.error, NotFound)

    async def test_rotate_refresh_token_max_expires_at(
        self, rdb_session: WriteSession
    ) -> None:
        """Token rotation expiration time is limited by max_expires_at."""
        # Given: create Session with max_expires_at set
        user_id = await _create_user(rdb_session, email="sess-maxexp@example.com")
        repo = SessionRepository()
        max_exp = tznow() + datetime.timedelta(hours=1)
        sess = await repo.create(
            rdb_session,
            SessionCreate(
                user_id=user_id,
                refresh_token="maxexp-old",
                expires_at=tznow() + datetime.timedelta(minutes=30),
                max_expires_at=max_exp,
            ),
        )

        # When: rotate to expiration time beyond max_expires_at
        far_future = tznow() + datetime.timedelta(days=30)
        result = await repo.rotate_refresh_token(
            rdb_session,
            sess.id,
            current_refresh_token="maxexp-old",
            new_refresh_token="maxexp-new",
            new_expires_at=far_future,
        )

        # Then: expires_at is limited to max_expires_at
        assert isinstance(result, Success)
        assert result.value.expires_at <= max_exp

    async def test_update_last_used(self, rdb_session: WriteSession) -> None:
        """Update Session last used time."""
        # Given: create Session
        user_id = await _create_user(rdb_session, email="sess-lastused@example.com")
        repo = SessionRepository()
        sess = await repo.create(
            rdb_session,
            SessionCreate(
                user_id=user_id,
                refresh_token="lastused-token",
                expires_at=tznow() + datetime.timedelta(hours=1),
            ),
        )
        original_last_used = sess.last_used_at

        # When: update last used time
        result = await repo.update_last_used(rdb_session, sess.id)

        # Then: update success
        assert isinstance(result, Success)
        assert result.value.last_used_at >= original_last_used

    async def test_update_last_used_not_found(self, rdb_session: WriteSession) -> None:
        """Return NotFound when updating last used time of nonexistent Session."""
        # Given: nonexistent ID
        repo = SessionRepository()

        # When: attempt update
        result = await repo.update_last_used(rdb_session, "nonexistent")

        # Then: NotFound error
        assert isinstance(result, Failure)
        assert isinstance(result.error, NotFound)

    async def test_delete(self, rdb_session: WriteSession) -> None:
        """Delete Session."""
        # Given: create Session
        user_id = await _create_user(rdb_session, email="sess-del@example.com")
        repo = SessionRepository()
        sess = await repo.create(
            rdb_session,
            SessionCreate(
                user_id=user_id,
                refresh_token="delete-token",
                expires_at=tznow() + datetime.timedelta(hours=1),
            ),
        )

        # When: delete
        await repo.delete(rdb_session, sess.id)

        # Then: None when fetching
        found = await repo.get(rdb_session, sess.id)
        assert found is None


async def test_actual_session_issuance_loses_to_user_disable_and_revocation(
    rdb_engine: AsyncEngine,
    latest_db_schema: None,
) -> None:
    """A stale login cannot insert a valid Session after the revocation sweep."""
    del latest_db_schema
    suffix = uuid4().hex[:8]
    user_id: str | None = None
    task: asyncio.Task[object] | None = None
    try:
        async with AsyncSession(rdb_engine) as raw:
            user = await UserRepository().create(
                ReadWriteSession(raw),
                UserCreate(email=f"issuance-race-{suffix}@example.com"),
            )
            user_id = user.id
            await raw.commit()
        async with (
            AsyncSession(rdb_engine) as disabler,
            AsyncSession(rdb_engine) as issuer,
        ):
            await disabler.execute(
                sa.update(RDBUser)
                .where(RDBUser.id == user_id)
                .values(access_disabled_at=tznow())
            )
            await SessionRepository().revoke_all_by_user(
                ReadWriteSession(disabler), user_id
            )
            holder_pid = await disabler.scalar(sa.text("SELECT pg_backend_pid()"))
            issuer_pid = await issuer.scalar(sa.text("SELECT pg_backend_pid()"))
            assert isinstance(holder_pid, int) and isinstance(issuer_pid, int)
            now = tznow()

            async def issue() -> object:
                return await SessionRepository().create_for_active_user(
                    ReadWriteSession(issuer),
                    SessionCreate(
                        user_id=user_id,
                        refresh_token=f"token-{suffix}",
                        expires_at=now + datetime.timedelta(hours=1),
                        max_expires_at=now + datetime.timedelta(days=1),
                    ),
                )

            task = asyncio.create_task(issue())
            async with asyncio.timeout(5), AsyncSession(rdb_engine) as observer:
                while True:
                    blockers = await observer.scalar(
                        sa.text("SELECT pg_blocking_pids(:pid)"), {"pid": issuer_pid}
                    )
                    if holder_pid in blockers:
                        break
                    assert not task.done()
            await disabler.commit()
            outcome = await asyncio.wait_for(task, timeout=5)
            assert isinstance(outcome, Failure)
            await issuer.commit()
        async with AsyncSession(rdb_engine) as raw:
            count = await raw.scalar(
                sa.select(sa.func.count())
                .select_from(RDBSession)
                .where(RDBSession.user_id == user_id, RDBSession.revoked_at.is_(None))
            )
            assert count == 0
    finally:
        if task is not None and not task.done():
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        if user_id is not None:
            async with AsyncSession(rdb_engine) as raw:
                await raw.execute(sa.delete(RDBUser).where(RDBUser.id == user_id))
                await raw.commit()
