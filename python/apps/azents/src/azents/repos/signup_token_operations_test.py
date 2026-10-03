"""Genuine PostgreSQL Signup atomicity, rollback and natural contention proofs."""

import asyncio
import dataclasses
import hashlib
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
import sqlalchemy as sa
from azcommon.result import Failure, Result, Success
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, AsyncSession

import azents.repos.signup_token_operations as operations_module
from azents.core.enums import SignupTokenDeliveryMethod
from azents.core.signup_token_operations import (
    InvalidSignupToken,
    SignupTokenEmailAlreadyRegistered,
    SignupTokenEmailMismatch,
    SignupTokenRedeemCommand,
    SignupTokenRedeemFacts,
)
from azents.rdb.models.password_login import RDBPasswordLogin
from azents.rdb.models.session import RDBSession
from azents.rdb.models.signup_token import RDBSignupToken, RDBSignupTokenRedemption
from azents.rdb.models.user import RDBUser
from azents.rdb.models.user_email import RDBUserEmail
from azents.rdb.session import SessionManager
from azents.repos.password_login import PasswordLoginRepository
from azents.repos.password_login.data import (
    AlreadyExists,
    PasswordLogin,
    PasswordLoginCreate,
)
from azents.repos.session import SessionRepository
from azents.repos.session.data import Session, SessionCreate
from azents.repos.signup_token import SignupTokenRepository
from azents.repos.signup_token.data import (
    SignupToken,
    SignupTokenCreate,
    SignupTokenList,
    SignupTokenRedemption,
    SignupTokenRedemptionCreate,
    SignupTokenUnavailable,
)
from azents.repos.signup_token_operations import SignupTokenOperationRepository
from azents.repos.user import UserRepository
from azents.repos.user.data import User, UserCreate
from azents.repos.user_email import UserEmailRepository
from azents.repos.user_email.data import UserEmail

NOW = datetime(2026, 10, 3, 12, tzinfo=UTC)


class SignupScope:
    """Observe actual infrastructure close/rollback, never replace SQL execution."""

    def __init__(
        self, manager: SessionManager[AsyncSession], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self.manager = manager
        self.active: list[AsyncSession] = []
        self.sessions: list[AsyncSession] = []
        self.closed: list[AsyncSession] = []
        self.rollbacks: list[AsyncSession] = []
        self.commits = 0
        self.failures = 0
        original_close, original_rollback = AsyncSession.close, AsyncSession.rollback

        async def close(session: AsyncSession) -> None:
            await original_close(session)
            self.closed.append(session)

        async def rollback(session: AsyncSession) -> None:
            await original_rollback(session)
            self.rollbacks.append(session)

        monkeypatch.setattr(AsyncSession, "close", close)
        monkeypatch.setattr(AsyncSession, "rollback", rollback)

    @asynccontextmanager
    async def __call__(self) -> AsyncIterator[AsyncSession]:
        assert not self.active, "Completed Signup groups cannot nest"
        try:
            async with self.manager() as session:
                self.sessions.append(session)
                self.active.append(session)
                try:
                    yield session
                finally:
                    self.active.remove(session)
        except asyncio.CancelledError:
            self.failures += 1
            raise
        except Exception:
            self.failures += 1
            raise
        else:
            self.commits += 1

    def assert_closed(self) -> None:
        assert not self.active
        assert all(not session.in_transaction() for session in self.sessions)
        assert all(session in self.closed for session in self.sessions)


@dataclasses.dataclass(frozen=True)
class SignupCall:
    stage: str
    session: AsyncSession


class SignupFault:
    """Explicit barriers/errors follow the awaited real narrow SQL primitive."""

    def __init__(self, scope: SignupScope) -> None:
        self.scope = scope
        self.stage: str | None = None
        self.pause = False
        self.error: RuntimeError | None = None
        self.reached = asyncio.Event()
        self.release = asyncio.Event()
        self.trace: list[SignupCall] = []
        self.clocks: list[datetime] = []

    async def point(self, stage: str, session: AsyncSession) -> None:
        assert self.scope.active == [session]
        assert session.in_transaction()
        self.trace.append(SignupCall(stage, session))
        if self.stage == stage:
            self.reached.set()
            if self.pause:
                await self.release.wait()
            if self.error is not None:
                raise self.error

    def stages(self) -> list[str]:
        return [call.stage for call in self.trace]


class SignupTokens(SignupTokenRepository):
    def __init__(self, fault: SignupFault) -> None:
        self.fault = fault

    async def create(
        self, session: AsyncSession, create: SignupTokenCreate
    ) -> SignupToken:
        result = await super().create(session, create)
        await self.fault.point("token_create", session)
        return result

    async def list_all(
        self, session: AsyncSession, *, offset: int = 0, limit: int = 50
    ) -> SignupTokenList:
        result = await super().list_all(session, offset=offset, limit=limit)
        await self.fault.point("token_list", session)
        return result

    async def get_by_token_hash(
        self, session: AsyncSession, token_hash: str
    ) -> SignupToken | None:
        result = await super().get_by_token_hash(session, token_hash)
        await self.fault.point("token_get", session)
        return result

    async def get_available_by_token_hash(
        self, session: AsyncSession, token_hash: str, *, now: datetime
    ) -> Result[SignupToken, SignupTokenUnavailable]:
        result = await super().get_available_by_token_hash(session, token_hash, now=now)
        self.fault.clocks.append(now)
        await self.fault.point("available", session)
        return result

    async def claim_for_redemption(
        self, session: AsyncSession, token_hash: str, *, now: datetime
    ) -> Result[SignupToken, SignupTokenUnavailable]:
        result = await super().claim_for_redemption(session, token_hash, now=now)
        self.fault.clocks.append(now)
        await self.fault.point("claim", session)
        return result

    async def create_redemption(
        self, session: AsyncSession, create: SignupTokenRedemptionCreate
    ) -> SignupTokenRedemption:
        result = await super().create_redemption(session, create)
        await self.fault.point("audit", session)
        return result

    async def revoke(
        self, session: AsyncSession, token_id: str, *, revoked_at: datetime
    ) -> bool:
        result = await super().revoke(session, token_id, revoked_at=revoked_at)
        self.fault.clocks.append(revoked_at)
        await self.fault.point("revoke", session)
        return result


class SignupUsers(UserRepository):
    def __init__(self, fault: SignupFault) -> None:
        self.fault = fault

    async def create_with_verified_primary_email(
        self, session: AsyncSession, create: UserCreate, *, verified_at: datetime
    ) -> User:
        result = await super().create_with_verified_primary_email(
            session, create, verified_at=verified_at
        )
        await self.fault.point("user_create", session)
        return result


class SignupEmails(UserEmailRepository):
    def __init__(self, fault: SignupFault) -> None:
        self.fault = fault

    async def get_by_email(self, session: AsyncSession, email: str) -> UserEmail | None:
        result = await super().get_by_email(session, email)
        await self.fault.point("email_lookup", session)
        return result


class SignupPasswords(PasswordLoginRepository):
    def __init__(self, fault: SignupFault) -> None:
        self.fault = fault

    async def create(
        self, session: AsyncSession, create: PasswordLoginCreate
    ) -> Result[PasswordLogin, AlreadyExists]:
        result = await super().create(session, create)
        await self.fault.point("password_create", session)
        return result


class SignupSessions(SessionRepository):
    def __init__(self, fault: SignupFault) -> None:
        self.fault = fault

    async def create(self, session: AsyncSession, create: SessionCreate) -> Session:
        result = await super().create(session, create)
        await self.fault.point("session_create", session)
        return result


class ActualRollbackPasswords(PasswordLoginRepository):
    """Exercise the actual duplicate primitive and its rollback, not fake Failure."""

    def __init__(self, fault: SignupFault) -> None:
        self.fault = fault

    async def create(
        self, session: AsyncSession, create: PasswordLoginCreate
    ) -> Result[PasswordLogin, AlreadyExists]:
        first = await super().create(session, create)
        assert isinstance(first, Success)
        second = await super().create(session, create)
        assert isinstance(second, Failure)
        assert session in self.fault.scope.rollbacks
        assert not session.in_transaction()
        self.fault.trace.append(SignupCall("password_real_rollback", session))
        return second


@dataclasses.dataclass(frozen=True)
class SignupFixture:
    repository: SignupTokenOperationRepository
    scope: SignupScope
    fault: SignupFault
    manager: SessionManager[AsyncSession]
    email: str
    token_hash: str


def signup_fixture(
    manager: SessionManager[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> SignupFixture:
    scope = SignupScope(manager, monkeypatch)
    fault = SignupFault(scope)
    repository = SignupTokenOperationRepository(
        session_manager=scope,
        signup_token_repository=SignupTokens(fault),
        user_repository=SignupUsers(fault),
        user_email_repository=SignupEmails(fault),
        password_login_repository=SignupPasswords(fault),
        session_repository=SignupSessions(fault),
    )
    return SignupFixture(
        repository,
        scope,
        fault,
        manager,
        f"signup-{uuid4().hex}@example.test",
        hashlib.sha256(uuid4().hex.encode()).hexdigest(),
    )


def prepared(
    fixture: SignupFixture, *, label: str, max_expiry: bool
) -> SignupTokenRedeemCommand:
    return SignupTokenRedeemCommand(
        token_hash=fixture.token_hash,
        now=NOW,
        email=fixture.email,
        password_hash=f"synthetic-prepared-hash-{label}",
        refresh_token=f"synthetic-refresh-{uuid4().hex}",
        expires_at=NOW + timedelta(days=30),
        max_expires_at=NOW + timedelta(days=60) if max_expiry else None,
        user_agent=f"synthetic-agent-{label}",
        ip_address="192.0.2.17",
    )


async def seed_token(
    fixture: SignupFixture, *, token_hash: str, max_uses: int
) -> SignupToken:
    async with fixture.manager() as session:
        return await SignupTokenRepository().create(
            session,
            SignupTokenCreate(
                token_hash=token_hash,
                email=fixture.email,
                created_by_user_id=None,
                delivery_method=SignupTokenDeliveryMethod.MANUAL,
                expires_at=NOW + timedelta(hours=1),
                max_uses=max_uses,
            ),
        )


async def footprint(fixture: SignupFixture) -> dict[str, list[dict[str, object]]]:
    """Only this UUID-email/token subject; compare complete committed SQL rows."""
    async with fixture.manager() as session:
        user_ids = sa.select(RDBUserEmail.user_id).where(
            RDBUserEmail.email == fixture.email
        )
        token_ids = sa.select(RDBSignupToken.id).where(
            RDBSignupToken.email == fixture.email
        )
        statements = {
            "tokens": sa.select(*RDBSignupToken.__table__.columns)
            .where(RDBSignupToken.email == fixture.email)
            .order_by(RDBSignupToken.id),
            "users": sa.select(*RDBUser.__table__.columns).where(
                RDBUser.id.in_(user_ids)
            ),
            "emails": sa.select(*RDBUserEmail.__table__.columns).where(
                RDBUserEmail.email == fixture.email
            ),
            "passwords": sa.select(*RDBPasswordLogin.__table__.columns).where(
                RDBPasswordLogin.user_id.in_(user_ids)
            ),
            "sessions": sa.select(*RDBSession.__table__.columns)
            .where(RDBSession.user_id.in_(user_ids))
            .order_by(RDBSession.id),
            "audits": sa.select(*RDBSignupTokenRedemption.__table__.columns).where(
                RDBSignupTokenRedemption.signup_token_id.in_(token_ids)
            ),
        }
        rows: dict[str, list[dict[str, object]]] = {}
        for name, statement in statements.items():
            result = await session.execute(statement)
            rows[name] = [dict(row) for row in result.mappings()]
        return rows


async def cleanup_signup(fixture: SignupFixture) -> None:
    async with fixture.manager() as session:
        user_ids = sa.select(RDBUserEmail.user_id).where(
            RDBUserEmail.email == fixture.email
        )
        await session.execute(
            sa.delete(RDBSignupToken).where(RDBSignupToken.email == fixture.email)
        )
        await session.execute(sa.delete(RDBUser).where(RDBUser.id.in_(user_ids)))
        await session.execute(
            sa.delete(RDBUserEmail).where(RDBUserEmail.email == fixture.email)
        )


@pytest.fixture
async def signup_pg(
    rdb_session_manager: SessionManager[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> SignupFixture:
    return signup_fixture(rdb_session_manager, monkeypatch)


@pytest.mark.parametrize(
    "method", [SignupTokenDeliveryMethod.MANUAL, SignupTokenDeliveryMethod.EMAIL]
)
async def test_create_detached_and_exact_lookup_complete_one_group(
    signup_pg: SignupFixture, method: SignupTokenDeliveryMethod
) -> None:
    fixture = signup_pg
    token = await fixture.repository.create(
        create=SignupTokenCreate(
            token_hash=fixture.token_hash,
            email=fixture.email,
            created_by_user_id=None,
            delivery_method=method,
            expires_at=NOW + timedelta(hours=3),
            max_uses=3,
        )
    )
    assert token.token_hash == fixture.token_hash and token.email == fixture.email
    assert token.max_uses == 3 and token.used_count == 0 and token.revoked_at is None
    assert token.delivery_method is method and token.created_by_user_id is None
    assert sa.inspect(token, raiseerr=False) is None
    assert fixture.fault.stages() == ["token_create"]
    fixture.scope.assert_closed()
    assert (
        await fixture.repository.get_by_token_hash(token_hash=fixture.token_hash)
        == token
    )
    assert await fixture.repository.get_by_token_hash(token_hash="unknown") is None
    assert fixture.scope.commits == 3
    fixture.scope.assert_closed()


async def test_count_page_order_total_and_detachment_share_one_scope(
    signup_pg: SignupFixture,
) -> None:
    fixture = signup_pg
    ids: list[str] = []
    async with fixture.manager() as session:
        for index in range(3):
            token = await SignupTokenRepository().create(
                session,
                SignupTokenCreate(
                    token_hash=hashlib.sha256(
                        f"{fixture.token_hash}-{index}".encode()
                    ).hexdigest(),
                    email=fixture.email,
                    created_by_user_id=None,
                    delivery_method=SignupTokenDeliveryMethod.MANUAL,
                    expires_at=NOW + timedelta(days=1),
                    max_uses=1,
                ),
            )
            await session.execute(
                sa.update(RDBSignupToken)
                .where(RDBSignupToken.id == token.id)
                .values(created_at=NOW + timedelta(minutes=index))
            )
            ids.append(token.id)
    page = await fixture.repository.list_all(offset=1, limit=1)
    assert page.total == 3 and [token.id for token in page.items] == [ids[1]]
    assert fixture.fault.stages() == ["token_list"] and len(fixture.scope.sessions) == 1
    fixture.scope.assert_closed()
    full = await fixture.repository.list_all(offset=0, limit=50)
    assert [token.id for token in full.items] == ids[::-1]
    assert sa.inspect(full, raiseerr=False) is None
    empty = await fixture.repository.list_all(offset=3, limit=50)
    assert empty.total == 3 and empty.items == []
    fixture.scope.assert_closed()


async def test_revoke_repeated_existing_absent_and_clock_inside_scope(
    signup_pg: SignupFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = signup_pg
    token = await seed_token(fixture, token_hash=fixture.token_hash, max_uses=1)
    clocks = iter((NOW, NOW + timedelta(seconds=1), NOW + timedelta(seconds=2)))

    def clock() -> datetime:
        assert len(fixture.scope.active) == 1
        return next(clocks)

    monkeypatch.setattr(operations_module, "tznow", clock)
    assert await fixture.repository.revoke(token_id=token.id)
    assert await fixture.repository.revoke(token_id=token.id)
    assert not await fixture.repository.revoke(token_id="0" * 32)
    rows = await footprint(fixture)
    assert rows["tokens"][0]["revoked_at"] == NOW + timedelta(seconds=1)
    assert fixture.fault.clocks == [
        NOW,
        NOW + timedelta(seconds=1),
        NOW + timedelta(seconds=2),
    ]
    fixture.scope.assert_closed()


@pytest.mark.parametrize("max_expiry", [False, True])
async def test_redemption_atomic_order_exact_complete_rows_frozen_ids(
    signup_pg: SignupFixture, max_expiry: bool
) -> None:
    fixture = signup_pg
    token = await seed_token(fixture, token_hash=fixture.token_hash, max_uses=2)
    command = prepared(fixture, label="success", max_expiry=max_expiry)
    result = await fixture.repository.redeem(command=command)
    assert isinstance(result, Success)
    facts = result.value
    assert {field.name for field in dataclasses.fields(command)} == {
        "token_hash",
        "now",
        "email",
        "password_hash",
        "refresh_token",
        "expires_at",
        "max_expires_at",
        "user_agent",
        "ip_address",
    }
    assert (
        type(command).__dataclass_params__.frozen
        and type(facts).__dataclass_params__.frozen
    )
    assert {field.name for field in dataclasses.fields(facts)} == {
        "user_id",
        "session_id",
    }
    assert sa.inspect(facts, raiseerr=False) is None
    assert fixture.fault.stages() == [
        "available",
        "email_lookup",
        "claim",
        "user_create",
        "password_create",
        "session_create",
        "audit",
    ]
    assert len({id(call.session) for call in fixture.fault.trace}) == 1
    assert fixture.fault.clocks == [command.now, command.now]
    fixture.scope.assert_closed()
    rows = await footprint(fixture)
    assert {name: len(values) for name, values in rows.items()} == {
        "tokens": 1,
        "users": 1,
        "emails": 1,
        "passwords": 1,
        "sessions": 1,
        "audits": 1,
    }
    assert rows["tokens"][0]["used_count"] == 1
    assert rows["users"][0]["id"] == facts.user_id
    assert rows["users"][0]["primary_email_id"] == rows["emails"][0]["id"]
    assert rows["emails"][0]["verified_at"] == command.now
    assert rows["passwords"][0]["password_hash"] == command.password_hash
    session = rows["sessions"][0]
    assert session["id"] == facts.session_id and session["user_id"] == facts.user_id
    assert session["refresh_token"] == command.refresh_token
    assert (
        session["expires_at"] == command.expires_at
        and session["max_expires_at"] == command.max_expires_at
    )
    assert (
        session["user_agent"] == command.user_agent
        and session["ip_address"] == command.ip_address
    )
    audit = rows["audits"][0]
    assert audit["signup_token_id"] == token.id and audit["user_id"] == facts.user_id
    assert audit["email"] == command.email and audit["redeemed_at"] == command.now
    assert (
        audit["ip_address"] == command.ip_address
        and audit["user_agent"] == command.user_agent
    )


@pytest.mark.parametrize(
    "invalid",
    [
        "missing",
        "revoked",
        "expiry_equal",
        "expiry_past",
        "exhausted",
        "mismatch",
        "registered",
        "registered_disabled",
    ],
)
async def test_redemption_precondition_order_and_no_consumption(
    signup_pg: SignupFixture, invalid: str
) -> None:
    fixture = signup_pg
    token = await seed_token(fixture, token_hash=fixture.token_hash, max_uses=1)
    command = prepared(fixture, label=invalid, max_expiry=False)
    async with fixture.manager() as session:
        if invalid == "revoked":
            await session.execute(
                sa.update(RDBSignupToken)
                .where(RDBSignupToken.id == token.id)
                .values(revoked_at=NOW)
            )
        elif invalid in {"expiry_equal", "expiry_past"}:
            await session.execute(
                sa.update(RDBSignupToken)
                .where(RDBSignupToken.id == token.id)
                .values(
                    expires_at=NOW
                    if invalid == "expiry_equal"
                    else NOW - timedelta(microseconds=1)
                )
            )
        elif invalid == "exhausted":
            await session.execute(
                sa.update(RDBSignupToken)
                .where(RDBSignupToken.id == token.id)
                .values(used_count=1)
            )
        elif invalid in {"registered", "registered_disabled"}:
            user = await UserRepository().create(
                session, UserCreate(email=fixture.email)
            )
            if invalid == "registered_disabled":
                await UserRepository().disable_access(session, user.id, disabled_at=NOW)
    if invalid == "missing":
        command = dataclasses.replace(command, token_hash="missing")
    elif invalid == "mismatch":
        command = dataclasses.replace(command, email="different@example.test")
    before = await footprint(fixture)
    result = await fixture.repository.redeem(command=command)
    if invalid == "mismatch":
        assert result == Failure(SignupTokenEmailMismatch())
        assert fixture.fault.stages() == ["available"]
    elif invalid in {"registered", "registered_disabled"}:
        assert result == Failure(SignupTokenEmailAlreadyRegistered(email=command.email))
        assert fixture.fault.stages() == ["available", "email_lookup"]
    else:
        assert result == Failure(InvalidSignupToken())
        assert fixture.fault.stages() == ["available"]
    assert await footprint(fixture) == before
    fixture.scope.assert_closed()


@pytest.mark.parametrize(
    "stage",
    [
        "available",
        "email_lookup",
        "claim",
        "user_create",
        "password_create",
        "session_create",
        "audit",
    ],
)
@pytest.mark.parametrize("cancel", [False, True])
async def test_actual_selected_sql_fault_cancel_rolls_back_entire_redemption(
    signup_pg: SignupFixture,
    stage: str,
    cancel: bool,
    record_property: Callable[[str, object], None],
) -> None:
    fixture = signup_pg
    await seed_token(fixture, token_hash=fixture.token_hash, max_uses=1)
    before = await footprint(fixture)
    fixture.fault.stage, fixture.fault.pause = stage, cancel
    if not cancel:
        fixture.fault.error = RuntimeError("after actual Signup SQL primitive")
    task = asyncio.create_task(
        fixture.repository.redeem(
            command=prepared(fixture, label=stage, max_expiry=False)
        )
    )
    try:
        if cancel:
            await asyncio.wait_for(fixture.fault.reached.wait(), timeout=10)
            task.cancel("after awaited Signup SQL before group commit")
        with pytest.raises(asyncio.CancelledError if cancel else RuntimeError):
            await task
        assert fixture.fault.reached.is_set()
        assert fixture.scope.commits == 0 and fixture.scope.failures == 1
        fixture.scope.assert_closed()
        assert await footprint(fixture) == before
        record_property("sql_stage", stage)
        record_property("actual_task_cancel", cancel)
        record_property("sql_witness", "real_narrow_await_then_explicit_barrier")
    finally:
        fixture.fault.release.set()
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def test_actual_password_failure_rolls_back_then_returns_without_queries(
    signup_pg: SignupFixture,
) -> None:
    fixture = signup_pg
    await seed_token(fixture, token_hash=fixture.token_hash, max_uses=1)
    before = await footprint(fixture)
    repository = dataclasses.replace(
        fixture.repository,
        password_login_repository=ActualRollbackPasswords(fixture.fault),
    )
    result = await repository.redeem(
        command=prepared(fixture, label="actual-rollback", max_expiry=False)
    )
    assert result == Failure(SignupTokenEmailAlreadyRegistered(email=fixture.email))
    assert fixture.fault.stages() == [
        "available",
        "email_lookup",
        "claim",
        "user_create",
        "password_real_rollback",
    ]
    assert (
        "session_create" not in fixture.fault.stages()
        and "audit" not in fixture.fault.stages()
    )
    fixture.scope.assert_closed()
    assert await footprint(fixture) == before


@pytest.mark.parametrize(
    "operation,stage",
    [
        ("create", "token_create"),
        ("list", "token_list"),
        ("get", "token_get"),
        ("revoke", "revoke"),
    ],
)
@pytest.mark.parametrize("cancel", [False, True])
async def test_other_completed_groups_actual_fault_cancel_close_and_preserve_state(
    signup_pg: SignupFixture, operation: str, stage: str, cancel: bool
) -> None:
    fixture = signup_pg
    token = await seed_token(fixture, token_hash=fixture.token_hash, max_uses=1)
    before = await footprint(fixture)
    fixture.fault.stage, fixture.fault.pause = stage, cancel
    if not cancel:
        fixture.fault.error = RuntimeError("actual selected Signup group failed")

    async def action() -> None:
        if operation == "create":
            await fixture.repository.create(
                create=SignupTokenCreate(
                    token_hash=hashlib.sha256(uuid4().hex.encode()).hexdigest(),
                    email=fixture.email,
                    created_by_user_id=None,
                    delivery_method=SignupTokenDeliveryMethod.EMAIL,
                    expires_at=NOW + timedelta(hours=1),
                    max_uses=1,
                )
            )
        elif operation == "list":
            await fixture.repository.list_all(offset=0, limit=50)
        elif operation == "get":
            await fixture.repository.get_by_token_hash(token_hash=fixture.token_hash)
        else:
            await fixture.repository.revoke(token_id=token.id)

    task = asyncio.create_task(action())
    try:
        if cancel:
            await asyncio.wait_for(fixture.fault.reached.wait(), timeout=10)
            task.cancel("after real Signup group SQL")
        with pytest.raises(asyncio.CancelledError if cancel else RuntimeError):
            await task
        fixture.scope.assert_closed()
        assert await footprint(fixture) == before
    finally:
        fixture.fault.release.set()
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)


class IndependentSignupManager:
    """Real commits on pinned PostgreSQL connections, not fixture savepoints."""

    def __init__(self, connection: AsyncConnection) -> None:
        self.connection = connection
        self.pids: list[int] = []

    @asynccontextmanager
    async def __call__(self) -> AsyncIterator[AsyncSession]:
        async with AsyncSession(self.connection, expire_on_commit=False) as session:
            try:
                pid = await session.scalar(sa.text("SELECT pg_backend_pid()"))
                assert isinstance(pid, int)
                self.pids.append(pid)
                yield session
            except asyncio.CancelledError:
                await session.rollback()
                raise
            except Exception:
                await session.rollback()
                raise
            else:
                await session.commit()


async def test_standalone_password_primitive_rollback_preserves_committed_token(
    rdb_engine: AsyncEngine,
    latest_db_schema: None,
    monkeypatch: pytest.MonkeyPatch,
    record_property: Callable[[str, object], None],
) -> None:
    del latest_db_schema
    async with (
        rdb_engine.connect() as writer_connection,
        rdb_engine.connect() as observer_connection,
    ):
        writer = IndependentSignupManager(writer_connection)
        observer = IndependentSignupManager(observer_connection)
        fixture = signup_fixture(writer, monkeypatch)
        try:
            await seed_token(fixture, token_hash=fixture.token_hash, max_uses=1)
            before = await footprint(dataclasses.replace(fixture, manager=observer))
            repository = dataclasses.replace(
                fixture.repository,
                password_login_repository=ActualRollbackPasswords(fixture.fault),
            )
            result = await repository.redeem(
                command=prepared(fixture, label="standalone-rollback", max_expiry=False)
            )
            assert result == Failure(
                SignupTokenEmailAlreadyRegistered(email=fixture.email)
            )
            assert fixture.fault.stages()[-1] == "password_real_rollback"
            assert "session_create" not in fixture.fault.stages()
            assert "audit" not in fixture.fault.stages()
            fixture.scope.assert_closed()
            assert (
                await footprint(dataclasses.replace(fixture, manager=observer))
                == before
            )
            assert writer.pids[-1] != observer.pids[-1]
            record_property("writer_backend_pid", writer.pids[-1])
            record_property("observer_backend_pid", observer.pids[-1])
            record_property(
                "rollback_witness",
                "actual_primitive_rollback_preserves_prior_independent_commit",
            )
        finally:
            await cleanup_signup(fixture)


async def wait_signup_blocked(engine: AsyncEngine, *, holder: int, waiter: int) -> None:
    assert holder != waiter
    async with asyncio.timeout(10):
        async with AsyncSession(engine) as observer:
            while True:
                blockers = await observer.scalar(
                    sa.text("SELECT pg_blocking_pids(:pid)"), {"pid": waiter}
                )
                if isinstance(blockers, list) and holder in blockers:
                    return


@pytest.mark.parametrize("outcome", ["commit", "error", "cancel"])
async def test_independent_conditional_claim_rechecks_after_real_commit_or_rollback(
    rdb_engine: AsyncEngine,
    latest_db_schema: None,
    monkeypatch: pytest.MonkeyPatch,
    outcome: str,
    record_property: Callable[[str, object], None],
) -> None:
    del latest_db_schema
    tasks: list[
        asyncio.Task[
            Result[
                SignupTokenRedeemFacts,
                InvalidSignupToken
                | SignupTokenEmailMismatch
                | SignupTokenEmailAlreadyRegistered,
            ]
        ]
    ] = []
    async with (
        rdb_engine.connect() as holder_connection,
        rdb_engine.connect() as waiter_connection,
    ):
        holder_manager, waiter_manager = (
            IndependentSignupManager(holder_connection),
            IndependentSignupManager(waiter_connection),
        )
        holder = signup_fixture(holder_manager, monkeypatch)
        waiter = signup_fixture(waiter_manager, monkeypatch)
        waiter = dataclasses.replace(
            waiter, email=holder.email, token_hash=holder.token_hash
        )
        try:
            await seed_token(holder, token_hash=holder.token_hash, max_uses=1)
            holder.fault.stage, holder.fault.pause = "audit", True
            if outcome == "error":
                holder.fault.error = RuntimeError("holder post-SQL error")
            first = asyncio.create_task(
                holder.repository.redeem(
                    command=prepared(holder, label="first", max_expiry=False)
                )
            )
            tasks.append(first)
            await asyncio.wait_for(holder.fault.reached.wait(), timeout=10)
            holder_pid = holder_manager.pids[-1]
            waiter.fault.stage, waiter.fault.pause = "email_lookup", True
            second = asyncio.create_task(
                waiter.repository.redeem(
                    command=prepared(waiter, label="second", max_expiry=False)
                )
            )
            tasks.append(second)
            await asyncio.wait_for(waiter.fault.reached.wait(), timeout=10)
            waiter_pid = waiter_manager.pids[-1]
            waiter.fault.release.set()
            await wait_signup_blocked(rdb_engine, holder=holder_pid, waiter=waiter_pid)
            assert not second.done()
            if outcome == "cancel":
                first.cancel("holder after actual audit before commit")
                with pytest.raises(asyncio.CancelledError):
                    await first
            else:
                holder.fault.release.set()
                if outcome == "error":
                    with pytest.raises(RuntimeError, match="holder post-SQL error"):
                        await first
                else:
                    assert isinstance(await first, Success)
            second_result = await asyncio.wait_for(second, timeout=10)
            if outcome == "commit":
                assert second_result == Failure(InvalidSignupToken())
                assert waiter.fault.stages() == ["available", "email_lookup", "claim"]
            else:
                assert isinstance(second_result, Success)
                assert holder.scope.failures == 1
            rows = await footprint(holder)
            assert {name: len(values) for name, values in rows.items()} == {
                "tokens": 1,
                "users": 1,
                "emails": 1,
                "passwords": 1,
                "sessions": 1,
                "audits": 1,
            }
            assert rows["tokens"][0]["used_count"] == 1
            holder.scope.assert_closed()
            waiter.scope.assert_closed()
            record_property("holder_backend_pid", holder_pid)
            record_property("waiter_backend_pid", waiter_pid)
            record_property("contention_witness", "pg_blocking_pids")
            record_property("holder_outcome", outcome)
        finally:
            holder.fault.release.set()
            waiter.fault.release.set()
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            await cleanup_signup(holder)


async def test_independent_email_uniqueness_error_rolls_back_other_token_whole_group(
    rdb_engine: AsyncEngine,
    latest_db_schema: None,
    monkeypatch: pytest.MonkeyPatch,
    record_property: Callable[[str, object], None],
) -> None:
    del latest_db_schema
    tasks: list[
        asyncio.Task[
            Result[
                SignupTokenRedeemFacts,
                InvalidSignupToken
                | SignupTokenEmailMismatch
                | SignupTokenEmailAlreadyRegistered,
            ]
        ]
    ] = []
    async with (
        rdb_engine.connect() as first_connection,
        rdb_engine.connect() as second_connection,
    ):
        first_manager, second_manager = (
            IndependentSignupManager(first_connection),
            IndependentSignupManager(second_connection),
        )
        first_fixture = signup_fixture(first_manager, monkeypatch)
        second_fixture = signup_fixture(second_manager, monkeypatch)
        second_fixture = dataclasses.replace(second_fixture, email=first_fixture.email)
        try:
            await seed_token(
                first_fixture, token_hash=first_fixture.token_hash, max_uses=1
            )
            await seed_token(
                second_fixture, token_hash=second_fixture.token_hash, max_uses=1
            )
            first_fixture.fault.stage, first_fixture.fault.pause = "audit", True
            first = asyncio.create_task(
                first_fixture.repository.redeem(
                    command=prepared(
                        first_fixture, label="unique-first", max_expiry=False
                    )
                )
            )
            tasks.append(first)
            await asyncio.wait_for(first_fixture.fault.reached.wait(), timeout=10)
            first_pid = first_manager.pids[-1]
            second_fixture.fault.stage, second_fixture.fault.pause = "claim", True
            second = asyncio.create_task(
                second_fixture.repository.redeem(
                    command=prepared(
                        second_fixture, label="unique-second", max_expiry=False
                    )
                )
            )
            tasks.append(second)
            await asyncio.wait_for(second_fixture.fault.reached.wait(), timeout=10)
            second_pid = second_manager.pids[-1]
            second_fixture.fault.release.set()
            await wait_signup_blocked(rdb_engine, holder=first_pid, waiter=second_pid)
            first_fixture.fault.release.set()
            assert isinstance(await asyncio.wait_for(first, timeout=10), Success)
            with pytest.raises(IntegrityError) as error:
                await asyncio.wait_for(second, timeout=10)
            assert "uq_user_emails_email" in str(error.value)
            rows = await footprint(first_fixture)
            assert [
                row["used_count"]
                for row in rows["tokens"]
                if row["token_hash"] == second_fixture.token_hash
            ] == [0]
            assert (
                len(rows["users"])
                == len(rows["emails"])
                == len(rows["passwords"])
                == len(rows["sessions"])
                == len(rows["audits"])
                == 1
            )
            assert second_fixture.scope.failures == 1
            first_fixture.scope.assert_closed()
            second_fixture.scope.assert_closed()
            record_property("holder_backend_pid", first_pid)
            record_property("waiter_backend_pid", second_pid)
            record_property(
                "contention_witness",
                "pg_blocking_pids_existing_email_unique_constraint",
            )
        finally:
            first_fixture.fault.release.set()
            second_fixture.fault.release.set()
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            await cleanup_signup(first_fixture)
