"""External account link security and concurrency tests."""

import asyncio
import dataclasses
import datetime
import hashlib
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import NamedTuple
from uuid import uuid4

import pytest
import sqlalchemy as sa
from azcommon.result import Success
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

import azents.repos.external_account_link as repository_module
from azents.core.enums import WorkspaceUserRole
from azents.core.external_account_link import (
    ExternalAccountLinkAttemptLimitReached,
    ExternalAccountLinkBusy,
    ExternalAccountLinkConflict,
    ExternalAccountLinkInvalidCode,
    ExternalAccountLinkMembershipRequired,
    ExternalAccountLinkUnavailable,
)
from azents.rdb.models.external_account_link import (
    RDBExternalAccountLink,
    RDBExternalAccountLinkCandidate,
)
from azents.rdb.models.session import RDBSession
from azents.rdb.models.user import RDBUser
from azents.rdb.models.workspace_user import RDBWorkspaceUser
from azents.rdb.session import SessionManager
from azents.repos.session import SessionRepository
from azents.repos.session.data import SessionCreate
from azents.repos.user import UserRepository
from azents.repos.user.data import UserCreate
from azents.repos.workspace_user import WorkspaceUserRepository
from azents.repos.workspace_user.data import WorkspaceUserCreate

from . import ExternalAccountLinkRepository
from .repository_test import _cleanup_link_test_rows, _create_fixture, _Fixture


@pytest.fixture(autouse=True)
async def _cleanup_committed_link_security_rows(
    rdb_engine: AsyncEngine,
) -> AsyncGenerator[None]:
    """Remove rows committed by security/concurrency session managers."""
    yield
    await _cleanup_link_test_rows(rdb_engine)


@pytest.mark.asyncio
async def test_origin_candidate_and_invalid_code_limits_are_terminal(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """Enforce five immutable candidates and five own-actor invalid codes."""
    fixture = await _create_fixture(rdb_session_manager)
    repository = ExternalAccountLinkRepository(rdb_session_manager)
    now = datetime.datetime(2026, 9, 12, 12, tzinfo=datetime.UTC)
    origin = await repository.create_origin(actor=fixture.actor, now=now)

    for index in range(5):
        await repository.create_candidate(
            user_id=fixture.user_id,
            auth_session_id=fixture.auth_session_id,
            origin_id=origin.origin_id,
            code_hash=hashlib.sha256(f"candidate-{index}".encode()).hexdigest(),
            plaintext_code=f"candidate-{index}",
            now=now,
        )
    with pytest.raises(ExternalAccountLinkConflict):
        await repository.create_candidate(
            user_id=fixture.user_id,
            auth_session_id=fixture.auth_session_id,
            origin_id=origin.origin_id,
            code_hash=hashlib.sha256(b"candidate-6").hexdigest(),
            plaintext_code="candidate-6",
            now=now,
        )

    for index in range(5):
        with pytest.raises(ExternalAccountLinkInvalidCode) as invalid:
            await repository.verify_candidate_code(
                actor=fixture.actor,
                origin_id=origin.origin_id,
                code_hash=hashlib.sha256(f"wrong-{index}".encode()).hexdigest(),
                now=now,
            )
        assert invalid.value.remaining_attempts == 4 - index
    with pytest.raises(ExternalAccountLinkAttemptLimitReached):
        await repository.verify_candidate_code(
            actor=fixture.actor,
            origin_id=origin.origin_id,
            code_hash=hashlib.sha256(b"wrong-terminal").hexdigest(),
            now=now,
        )


@pytest.mark.asyncio
async def test_active_external_identity_cannot_be_reassigned(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """Return a nondisclosing conflict instead of overwriting another owner."""
    fixture = await _create_fixture(rdb_session_manager)
    repository = ExternalAccountLinkRepository(rdb_session_manager)
    now = datetime.datetime(2026, 9, 12, 12, tzinfo=datetime.UTC)
    first_origin = await repository.create_origin(actor=fixture.actor, now=now)
    first_candidate = await _prove(
        repository,
        fixture=fixture,
        origin_id=first_origin.origin_id,
        code="first-code",
        now=now,
    )
    await repository.confirm_candidate(
        user_id=fixture.user_id,
        auth_session_id=fixture.auth_session_id,
        candidate_id=first_candidate,
        now=now,
    )
    second_user_id, second_session_id = await _add_user(
        rdb_session_manager,
        workspace_id=fixture.workspace_id,
    )
    second_actor = dataclasses.replace(
        fixture.actor,
        provider_interaction_id="second-" + uuid4().hex,
    )
    second_origin = await repository.create_origin(actor=second_actor, now=now)
    second_candidate = await repository.create_candidate(
        user_id=second_user_id,
        auth_session_id=second_session_id,
        origin_id=second_origin.origin_id,
        code_hash=hashlib.sha256(b"second-code").hexdigest(),
        plaintext_code="second-code",
        now=now,
    )
    await repository.verify_candidate_code(
        actor=second_actor,
        origin_id=second_origin.origin_id,
        code_hash=hashlib.sha256(b"second-code").hexdigest(),
        now=now,
    )
    with pytest.raises(ExternalAccountLinkConflict):
        await repository.confirm_candidate(
            user_id=second_user_id,
            auth_session_id=second_session_id,
            candidate_id=second_candidate.id,
            now=now,
        )


@pytest.mark.asyncio
async def test_auth_session_revocation_lock_exhausts_without_link_then_rejects(
    rdb_engine: AsyncEngine,
    latest_db_schema: None,
) -> None:
    """A concurrent auth-session revocation fences final link commit."""
    del latest_db_schema
    manager = _manager(rdb_engine)
    fixture = await _create_fixture(manager)
    repository = ExternalAccountLinkRepository(manager)
    now = datetime.datetime(2026, 9, 12, 12, tzinfo=datetime.UTC)
    origin = await repository.create_origin(actor=fixture.actor, now=now)
    candidate_id = await _prove(
        repository,
        fixture=fixture,
        origin_id=origin.origin_id,
        code="revocation-code",
        now=now,
    )

    async with AsyncSession(rdb_engine, expire_on_commit=False) as revoker:
        await revoker.execute(
            sa.update(RDBSession)
            .where(RDBSession.id == fixture.auth_session_id)
            .values(revoked_at=now)
        )
        with pytest.raises(ExternalAccountLinkBusy):
            await repository.confirm_candidate(
                user_id=fixture.user_id,
                auth_session_id=fixture.auth_session_id,
                candidate_id=candidate_id,
                now=now,
            )
        await revoker.commit()

    with pytest.raises(ExternalAccountLinkUnavailable):
        await repository.confirm_candidate(
            user_id=fixture.user_id,
            auth_session_id=fixture.auth_session_id,
            candidate_id=candidate_id,
            now=now,
        )
    assert await repository.list_links(user_id=fixture.user_id, now=now) == []


@pytest.mark.asyncio
async def test_two_finalizations_create_only_one_active_link(
    rdb_engine: AsyncEngine,
    latest_db_schema: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Concurrent sibling finalizations cannot create two active links."""
    del latest_db_schema
    manager = _manager(rdb_engine)
    fixture = await _create_fixture(manager)
    repository = ExternalAccountLinkRepository(manager)
    now = datetime.datetime(2026, 9, 12, 12, tzinfo=datetime.UTC)
    origin = await repository.create_origin(actor=fixture.actor, now=now)
    candidate_ids = [
        await _prove(
            repository,
            fixture=fixture,
            origin_id=origin.origin_id,
            code=f"candidate-{index}",
            now=now,
        )
        for index in range(2)
    ]
    original_set_lock_timeout = repository_module._set_lock_timeout
    start_barrier = asyncio.Barrier(2)
    synchronized_calls = 0

    async def synchronized_set_lock_timeout(session: AsyncSession) -> None:
        nonlocal synchronized_calls
        await original_set_lock_timeout(session)
        if synchronized_calls < 2:
            synchronized_calls += 1
            await start_barrier.wait()

    monkeypatch.setattr(
        repository_module,
        "_set_lock_timeout",
        synchronized_set_lock_timeout,
    )

    results = await asyncio.gather(
        *(
            repository.confirm_candidate(
                user_id=fixture.user_id,
                auth_session_id=fixture.auth_session_id,
                candidate_id=candidate_id,
                now=now,
            )
            for candidate_id in candidate_ids
        ),
        return_exceptions=True,
    )

    assert sum(not isinstance(result, BaseException) for result in results) == 1
    async with manager() as session:
        active_count = await session.scalar(
            sa.select(sa.func.count())
            .select_from(RDBExternalAccountLink)
            .where(
                RDBExternalAccountLink.workspace_id == fixture.workspace_id,
                RDBExternalAccountLink.revoked_at.is_(None),
            )
        )
    assert active_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("revocation", ["membership", "user"])
async def test_authority_revocation_fences_candidate_finalization(
    rdb_engine: AsyncEngine,
    latest_db_schema: None,
    revocation: str,
) -> None:
    """An authority writer that owns its row prevents a stale final commit."""
    del latest_db_schema
    manager = _manager(rdb_engine)
    fixture = await _create_fixture(manager)
    repository = ExternalAccountLinkRepository(manager)
    now = datetime.datetime(2026, 9, 12, 12, tzinfo=datetime.UTC)
    origin = await repository.create_origin(actor=fixture.actor, now=now)
    candidate_id = await _prove(
        repository,
        fixture=fixture,
        origin_id=origin.origin_id,
        code=f"{revocation}-code",
        now=now,
    )

    async with AsyncSession(rdb_engine, expire_on_commit=False) as revoker:
        if revocation == "membership":
            await revoker.execute(
                sa.delete(RDBWorkspaceUser).where(
                    RDBWorkspaceUser.id == fixture.workspace_user_id
                )
            )
        else:
            await revoker.execute(
                sa.update(RDBUser)
                .where(RDBUser.id == fixture.user_id)
                .values(access_disabled_at=now)
            )
        with pytest.raises(ExternalAccountLinkBusy):
            await repository.confirm_candidate(
                user_id=fixture.user_id,
                auth_session_id=fixture.auth_session_id,
                candidate_id=candidate_id,
                now=now,
            )
        await revoker.commit()

    with pytest.raises(
        ExternalAccountLinkUnavailable
        if revocation == "user"
        else ExternalAccountLinkMembershipRequired
    ):
        await repository.confirm_candidate(
            user_id=fixture.user_id,
            auth_session_id=fixture.auth_session_id,
            candidate_id=candidate_id,
            now=now,
        )
    assert await repository.list_links(user_id=fixture.user_id, now=now) == []


@pytest.mark.asyncio
async def test_implicit_unique_wait_times_out_without_consuming_candidate(
    rdb_engine: AsyncEngine,
    latest_db_schema: None,
) -> None:
    """Bound implicit unique-index waits and leave proof state unchanged."""
    del latest_db_schema
    manager = _manager(rdb_engine)
    fixture = await _create_fixture(manager)
    repository = ExternalAccountLinkRepository(manager)
    now = datetime.datetime(2026, 9, 12, 12, tzinfo=datetime.UTC)
    origin = await repository.create_origin(actor=fixture.actor, now=now)
    candidate_id = await _prove(
        repository,
        fixture=fixture,
        origin_id=origin.origin_id,
        code="unique-wait-code",
        now=now,
    )
    blocker_user_id, _ = await _add_user(
        manager,
        workspace_id=fixture.workspace_id,
    )

    async with AsyncSession(rdb_engine, expire_on_commit=False) as blocker:
        blocker_ready = asyncio.Event()
        blocker.add(
            RDBExternalAccountLink(
                workspace_id=fixture.workspace_id,
                user_id=blocker_user_id,
                provider=fixture.actor.provider,
                identity_scope=fixture.actor.provider_tenant_id,
                provider_user_id=fixture.actor.provider_user_id,
                provider_tenant_display_label="Workspace Team",
                provider_display_label="External User",
                linked_at=now,
                revoked_at=None,
            )
        )
        await blocker.flush()
        blocker_ready.set()
        await blocker_ready.wait()
        with pytest.raises(ExternalAccountLinkBusy):
            await repository.confirm_candidate(
                user_id=fixture.user_id,
                auth_session_id=fixture.auth_session_id,
                candidate_id=candidate_id,
                now=now,
            )
        await blocker.rollback()

    async with manager() as session:
        candidate = await session.get(RDBExternalAccountLinkCandidate, candidate_id)
        assert candidate is not None
        assert candidate.consumed_at is None
        assert candidate.link_id is None
        link_count = await session.scalar(
            sa.select(sa.func.count())
            .select_from(RDBExternalAccountLink)
            .where(RDBExternalAccountLink.workspace_id == fixture.workspace_id)
        )
        assert link_count == 0


@pytest.mark.asyncio
async def test_unlink_row_lock_fences_link_dependent_finalization(
    rdb_engine: AsyncEngine,
    latest_db_schema: None,
) -> None:
    """Do not consume a fresh proof while unlink owns the active link row."""
    del latest_db_schema
    manager = _manager(rdb_engine)
    fixture = await _create_fixture(manager)
    repository = ExternalAccountLinkRepository(manager)
    now = datetime.datetime(2026, 9, 12, 12, tzinfo=datetime.UTC)
    first_origin = await repository.create_origin(actor=fixture.actor, now=now)
    first_candidate_id = await _prove(
        repository,
        fixture=fixture,
        origin_id=first_origin.origin_id,
        code="first-link-code",
        now=now,
    )
    link = await repository.confirm_candidate(
        user_id=fixture.user_id,
        auth_session_id=fixture.auth_session_id,
        candidate_id=first_candidate_id,
        now=now,
    )
    second_actor = dataclasses.replace(
        fixture.actor,
        provider_interaction_id="reproof-" + uuid4().hex,
    )
    second_origin = await repository.create_origin(actor=second_actor, now=now)
    second_fixture = dataclasses.replace(fixture, actor=second_actor)
    second_candidate_id = await _prove(
        repository,
        fixture=second_fixture,
        origin_id=second_origin.origin_id,
        code="second-link-code",
        now=now,
    )

    async with AsyncSession(rdb_engine, expire_on_commit=False) as unlinker:
        await unlinker.execute(
            sa.update(RDBExternalAccountLink)
            .where(RDBExternalAccountLink.id == link.id)
            .values(revoked_at=now)
        )
        with pytest.raises(ExternalAccountLinkBusy):
            await repository.confirm_candidate(
                user_id=fixture.user_id,
                auth_session_id=fixture.auth_session_id,
                candidate_id=second_candidate_id,
                now=now,
            )
        await unlinker.rollback()

    replayed_link = await repository.confirm_candidate(
        user_id=fixture.user_id,
        auth_session_id=fixture.auth_session_id,
        candidate_id=second_candidate_id,
        now=now,
    )
    assert replayed_link.id == link.id


async def _prove(
    repository: ExternalAccountLinkRepository,
    *,
    fixture: _Fixture,
    origin_id: str,
    code: str,
    now: datetime.datetime,
) -> str:
    candidate = await repository.create_candidate(
        user_id=fixture.user_id,
        auth_session_id=fixture.auth_session_id,
        origin_id=origin_id,
        code_hash=hashlib.sha256(code.encode()).hexdigest(),
        plaintext_code=code,
        now=now,
    )
    await repository.verify_candidate_code(
        actor=fixture.actor,
        origin_id=origin_id,
        code_hash=hashlib.sha256(code.encode()).hexdigest(),
        now=now,
    )
    return candidate.id


class _UserFixture(NamedTuple):
    """Structured result returned by `_add_user`."""

    user_id: str
    auth_session_id: str


async def _add_user(
    manager: SessionManager[AsyncSession],
    *,
    workspace_id: str,
) -> _UserFixture:
    suffix = uuid4().hex
    async with manager() as session:
        user = await UserRepository().create(
            session,
            UserCreate(email=f"link-conflict-{suffix}@example.com"),
        )
        membership = await WorkspaceUserRepository().create(
            session,
            WorkspaceUserCreate(
                workspace_id=workspace_id,
                user_id=user.id,
                name="Second Link User",
                role=WorkspaceUserRole.MEMBER,
            ),
        )
        assert isinstance(membership, Success)
        auth_session = await SessionRepository().create(
            session,
            SessionCreate(
                user_id=user.id,
                refresh_token=uuid4().hex + uuid4().hex,
                expires_at=datetime.datetime(2026, 9, 13, tzinfo=datetime.UTC),
                max_expires_at=None,
                user_agent=None,
                ip_address=None,
            ),
        )
    return _UserFixture(user_id=user.id, auth_session_id=auth_session.id)


def _manager(engine: AsyncEngine) -> SessionManager[AsyncSession]:
    @asynccontextmanager
    async def manager() -> AsyncGenerator[AsyncSession, None]:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            try:
                yield session
            except Exception:
                await session.rollback()
                raise
            else:
                await session.commit()

    return manager
