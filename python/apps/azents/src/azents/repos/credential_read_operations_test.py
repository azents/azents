"""Real PostgreSQL ordered Credential facts and completed read lifetimes."""

import asyncio
import dataclasses
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from uuid import uuid4

import pytest
import sqlalchemy as sa
from azcommon.result import Success
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, AsyncSession

from azents.core.credential_read import (
    CredentialReadFact,
    CredentialReadKind,
    CredentialReadSnapshot,
)
from azents.core.user_email import UserEmailCreate
from azents.rdb.models.password_login import RDBPasswordLogin
from azents.rdb.models.user import RDBUser
from azents.rdb.models.user_email import RDBUserEmail
from azents.rdb.session import SessionManager
from azents.repos.credential_read_operations import CredentialReadOperationRepository
from azents.repos.password_login import PasswordLoginRepository
from azents.repos.password_login.data import PasswordLoginCreate
from azents.repos.user import UserRepository
from azents.repos.user.data import User, UserCreate
from azents.repos.user_email import UserEmailRepository
from azents.repos.user_email.data import UserEmail

PASSWORD = CredentialReadKind.PASSWORD
EMAIL = CredentialReadKind.EMAIL


@dataclasses.dataclass(frozen=True)
class CredentialQueryCall:
    stage: str
    occurrence: int
    argument: str
    session: AsyncSession


class CredentialReadScope:
    """Observe actual infrastructure close/commit/rollback, not a fake SQL scope."""

    def __init__(
        self, manager: SessionManager[AsyncSession], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self.manager = manager
        self.sessions: list[AsyncSession] = []
        self.active: list[AsyncSession] = []
        self.closed_sessions: list[AsyncSession] = []
        self.commits = 0
        self.failures = 0
        original_close = AsyncSession.close

        async def close(session: AsyncSession) -> None:
            await original_close(session)
            self.closed_sessions.append(session)

        monkeypatch.setattr(AsyncSession, "close", close)

    @asynccontextmanager
    async def __call__(self) -> AsyncIterator[AsyncSession]:
        assert not self.active, "Read groups must not nest completed operations"
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
        assert all(session in self.closed_sessions for session in self.sessions)


class CredentialReadFault:
    """Pause/error only after an awaited real narrow read returns."""

    def __init__(self, scope: CredentialReadScope) -> None:
        self.scope = scope
        self.trace: list[CredentialQueryCall] = []
        self.stage: str | None = None
        self.occurrence = 1
        self.error: RuntimeError | None = None
        self.pause = False
        self.reached = asyncio.Event()
        self.release = asyncio.Event()

    async def point(self, stage: str, argument: str, session: AsyncSession) -> None:
        assert self.scope.active == [session]
        assert session.in_transaction()
        occurrence = sum(call.stage == stage for call in self.trace) + 1
        self.trace.append(CredentialQueryCall(stage, occurrence, argument, session))
        if stage == self.stage and occurrence == self.occurrence:
            self.reached.set()
            if self.pause:
                await self.release.wait()
            if self.error is not None:
                raise self.error

    def stages(self) -> list[str]:
        return [call.stage for call in self.trace]


class CredentialUsers(UserRepository):
    def __init__(self, fault: CredentialReadFault) -> None:
        self.fault = fault

    async def get(self, session: AsyncSession, user_id: str) -> User | None:
        result = await super().get(session, user_id)
        await self.fault.point("user_get", user_id, session)
        return result

    async def get_by_email(self, session: AsyncSession, email: str) -> User | None:
        result = await super().get_by_email(session, email)
        await self.fault.point("user_by_email", email, session)
        return result


class CredentialEmails(UserEmailRepository):
    def __init__(self, fault: CredentialReadFault) -> None:
        self.fault = fault

    async def list_by_user(
        self, session: AsyncSession, user_id: str
    ) -> list[UserEmail]:
        result = await super().list_by_user(session, user_id)
        await self.fault.point("email_list", user_id, session)
        return result

    async def get_by_email(self, session: AsyncSession, email: str) -> UserEmail | None:
        result = await super().get_by_email(session, email)
        await self.fault.point("email_by_email", email, session)
        return result


class CredentialPasswords(PasswordLoginRepository):
    def __init__(self, fault: CredentialReadFault) -> None:
        self.fault = fault

    async def exists_for_user(self, session: AsyncSession, user_id: str) -> bool:
        result = await super().exists_for_user(session, user_id)
        await self.fault.point("password_exists", user_id, session)
        return result


@dataclasses.dataclass(frozen=True)
class CredentialReadFixture:
    repository: CredentialReadOperationRepository
    scope: CredentialReadScope
    fault: CredentialReadFault
    manager: SessionManager[AsyncSession]


def credential_read_fixture(
    manager: SessionManager[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> CredentialReadFixture:
    scope = CredentialReadScope(manager, monkeypatch)
    fault = CredentialReadFault(scope)
    return CredentialReadFixture(
        CredentialReadOperationRepository(
            session_manager=scope,
            user_repository=CredentialUsers(fault),
            user_email_repository=CredentialEmails(fault),
            password_login_repository=CredentialPasswords(fault),
        ),
        scope,
        fault,
        manager,
    )


@dataclasses.dataclass(frozen=True)
class CredentialReadSubject:
    user_id: str
    primary_email: str
    secondary_email: str


async def seed_credential_subject(
    manager: SessionManager[AsyncSession],
    *,
    password: bool,
    primary_verified: bool,
    secondary_verified: bool,
    disabled: bool,
) -> CredentialReadSubject:
    """Only synthetic hashes/data; no crypto, issuance or deletion authority test."""
    async with manager() as session:
        email = f"credential-{uuid4().hex}@example.test"
        user = await UserRepository().create(session, UserCreate(email=email))
        secondary = f"secondary-{uuid4().hex}@example.test"
        created = await UserEmailRepository().create(
            session, UserEmailCreate(user_id=user.id, email=secondary)
        )
        assert isinstance(created, Success)
        if primary_verified:
            await session.execute(
                sa.update(RDBUserEmail)
                .where(RDBUserEmail.email == email)
                .values(verified_at=datetime.now(UTC))
            )
        if secondary_verified:
            await session.execute(
                sa.update(RDBUserEmail)
                .where(RDBUserEmail.email == secondary)
                .values(verified_at=datetime.now(UTC))
            )
        if disabled:
            await UserRepository().disable_access(
                session, user.id, disabled_at=datetime.now(UTC)
            )
        if password:
            result = await PasswordLoginRepository().create(
                session,
                PasswordLoginCreate(
                    user_id=user.id, password_hash="synthetic-not-a-bcrypt-hash"
                ),
            )
            assert isinstance(result, Success)
        return CredentialReadSubject(user.id, email, secondary)


async def credential_rows(
    fixture: CredentialReadFixture, user_id: str
) -> dict[str, list[dict[str, object]]]:
    """Compare complete persisted rows without exposing a live ORM result."""
    async with fixture.manager() as session:
        users = await session.execute(
            sa.select(*RDBUser.__table__.columns).where(RDBUser.id == user_id)
        )
        emails = await session.execute(
            sa.select(*RDBUserEmail.__table__.columns)
            .where(RDBUserEmail.user_id == user_id)
            .order_by(RDBUserEmail.email)
        )
        passwords = await session.execute(
            sa.select(*RDBPasswordLogin.__table__.columns).where(
                RDBPasswordLogin.user_id == user_id
            )
        )
        return {
            "user": [dict(row) for row in users.mappings()],
            "emails": [dict(row) for row in emails.mappings()],
            "password": [dict(row) for row in passwords.mappings()],
        }


@pytest.fixture
async def credential_reads(
    rdb_session_manager: SessionManager[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> CredentialReadFixture:
    return credential_read_fixture(rdb_session_manager, monkeypatch)


@pytest.mark.parametrize("password", [False, True])
@pytest.mark.parametrize("verified", ["none", "primary", "secondary"])
@pytest.mark.parametrize("disabled", [False, True])
async def test_user_facts_preserve_any_verified_secondary_and_disabled_read_behavior(
    credential_reads: CredentialReadFixture,
    password: bool,
    verified: str,
    disabled: bool,
) -> None:
    fixture = credential_reads
    subject = await seed_credential_subject(
        fixture.manager,
        password=password,
        primary_verified=verified == "primary",
        secondary_verified=verified == "secondary",
        disabled=disabled,
    )
    before = await credential_rows(fixture, subject.user_id)
    result = await fixture.repository.read_user_snapshot(
        user_id=subject.user_id, kinds=(PASSWORD, EMAIL)
    )
    assert result == CredentialReadSnapshot(
        (
            CredentialReadFact(PASSWORD, password),
            CredentialReadFact(EMAIL, verified != "none"),
        )
    )
    assert fixture.fault.stages() == [
        "user_get",
        "password_exists",
        "user_get",
        "email_list",
    ]
    assert len({id(call.session) for call in fixture.fault.trace}) == 1
    assert fixture.scope.commits == 1
    fixture.scope.assert_closed()
    assert await credential_rows(fixture, subject.user_id) == before


@pytest.mark.parametrize(
    "kinds",
    [
        (),
        (PASSWORD,),
        (EMAIL,),
        (PASSWORD, EMAIL),
        (EMAIL, PASSWORD),
        (EMAIL, EMAIL, PASSWORD, PASSWORD, EMAIL),
    ],
)
@pytest.mark.parametrize("flow", ["user", "login"])
async def test_order_duplicate_reverse_empty_kinds_use_one_original_group(
    credential_reads: CredentialReadFixture,
    kinds: tuple[CredentialReadKind, ...],
    flow: str,
) -> None:
    fixture = credential_reads
    subject = await seed_credential_subject(
        fixture.manager,
        password=True,
        primary_verified=True,
        secondary_verified=False,
        disabled=False,
    )
    if flow == "user":
        snapshot = await fixture.repository.read_user_snapshot(
            user_id=subject.user_id, kinds=kinds
        )
        stages = ["user_get"]
        for kind in kinds:
            stages.extend(
                ["password_exists"] if kind is PASSWORD else ["user_get", "email_list"]
            )
    else:
        snapshot = await fixture.repository.read_login_snapshot(
            email=subject.primary_email, kinds=kinds
        )
        stages = []
        for kind in kinds:
            stages.extend(
                ["user_by_email", "password_exists"]
                if kind is PASSWORD
                else ["email_by_email"]
            )
    assert snapshot == CredentialReadSnapshot(
        tuple(CredentialReadFact(kind, True) for kind in kinds)
    )
    assert fixture.fault.stages() == stages
    assert len(fixture.scope.sessions) == 1 and fixture.scope.commits == 1
    assert all(
        call.session is fixture.scope.sessions[0] for call in fixture.fault.trace
    )
    fixture.scope.assert_closed()


@pytest.mark.parametrize("kinds", [(), (PASSWORD, EMAIL), (EMAIL, PASSWORD, EMAIL)])
async def test_initial_user_absence_none_skips_all_selected_provider_queries(
    credential_reads: CredentialReadFixture,
    kinds: tuple[CredentialReadKind, ...],
) -> None:
    fixture = credential_reads
    assert (
        await fixture.repository.read_user_snapshot(user_id="0" * 32, kinds=kinds)
        is None
    )
    assert fixture.fault.stages() == ["user_get"]
    assert fixture.scope.commits == 1
    fixture.scope.assert_closed()


@pytest.mark.parametrize(
    "lookup", ["primary", "secondary", "unknown", "different_case"]
)
@pytest.mark.parametrize("password", [False, True])
@pytest.mark.parametrize("disabled", [False, True])
async def test_login_uses_any_linked_email_password_and_exact_verified_address(
    credential_reads: CredentialReadFixture,
    lookup: str,
    password: bool,
    disabled: bool,
) -> None:
    fixture = credential_reads
    subject = await seed_credential_subject(
        fixture.manager,
        password=password,
        primary_verified=False,
        secondary_verified=True,
        disabled=disabled,
    )
    address = {
        "primary": subject.primary_email,
        "secondary": subject.secondary_email,
        "unknown": "unknown@example.test",
        "different_case": subject.secondary_email.upper(),
    }[lookup]
    result = await fixture.repository.read_login_snapshot(
        email=address, kinds=(PASSWORD, EMAIL)
    )
    known = lookup in {"primary", "secondary"}
    assert result == CredentialReadSnapshot(
        (
            CredentialReadFact(PASSWORD, password and known),
            CredentialReadFact(EMAIL, lookup == "secondary"),
        )
    )
    stages = (
        ["user_by_email"] + (["password_exists"] if known else []) + ["email_by_email"]
    )
    assert fixture.fault.stages() == stages
    assert (
        fixture.fault.trace[0].argument == fixture.fault.trace[-1].argument == address
    )
    fixture.scope.assert_closed()


async def test_real_zero_linked_email_list_keeps_unconfigured_email_fact(
    credential_reads: CredentialReadFixture,
) -> None:
    fixture = credential_reads
    subject = await seed_credential_subject(
        fixture.manager,
        password=False,
        primary_verified=True,
        secondary_verified=True,
        disabled=False,
    )
    async with fixture.manager() as session:
        other = await UserRepository().create(
            session, UserCreate(email=f"other-{uuid4().hex}@example.test")
        )
        # Defensive FK-valid fixture: User.get still joins its primary row by ID,
        # while that email row no longer belongs to this User's linked-email list.
        await session.execute(
            sa.update(RDBUserEmail)
            .where(RDBUserEmail.user_id == subject.user_id)
            .values(user_id=other.id)
        )
        assert await UserEmailRepository().list_by_user(session, subject.user_id) == []
    result = await fixture.repository.read_user_snapshot(
        user_id=subject.user_id, kinds=(EMAIL,)
    )
    assert result == CredentialReadSnapshot((CredentialReadFact(EMAIL, False),))
    assert fixture.fault.stages() == ["user_get", "user_get", "email_list"]
    fixture.scope.assert_closed()


async def test_required_frozen_detached_facts_hold_no_hash_or_orm_after_scope(
    credential_reads: CredentialReadFixture,
) -> None:
    fixture = credential_reads
    subject = await seed_credential_subject(
        fixture.manager,
        password=True,
        primary_verified=False,
        secondary_verified=True,
        disabled=False,
    )
    snapshot = await fixture.repository.read_user_snapshot(
        user_id=subject.user_id, kinds=(PASSWORD, EMAIL)
    )
    assert snapshot is not None
    assert type(snapshot).__dataclass_params__.frozen
    assert {field.name for field in dataclasses.fields(snapshot)} == {"facts"}
    assert isinstance(snapshot.facts, tuple)
    for fact in snapshot.facts:
        assert type(fact).__dataclass_params__.frozen
        assert {field.name for field in dataclasses.fields(fact)} == {
            "kind",
            "configured",
        }
        assert (
            isinstance(fact.kind, CredentialReadKind) and type(fact.configured) is bool
        )
        assert sa.inspect(fact, raiseerr=False) is None
    assert sa.inspect(snapshot, raiseerr=False) is None
    fixture.scope.assert_closed()
    async with fixture.manager() as session:
        await session.execute(
            sa.update(RDBUserEmail)
            .where(RDBUserEmail.user_id == subject.user_id)
            .values(verified_at=None)
        )
    assert snapshot.facts[-1].configured is True
    after = await fixture.repository.read_user_snapshot(
        user_id=subject.user_id, kinds=(EMAIL,)
    )
    assert after == CredentialReadSnapshot((CredentialReadFact(EMAIL, False),))
    fixture.scope.assert_closed()


READ_FAULTS = [
    ("user", "user_get", 1),
    ("user", "password_exists", 1),
    ("user", "user_get", 2),
    ("user", "email_list", 1),
    ("login", "user_by_email", 1),
    ("login", "password_exists", 1),
    ("login", "email_by_email", 1),
]


@pytest.mark.parametrize("flow,stage,occurrence", READ_FAULTS)
@pytest.mark.parametrize("cancel", [False, True])
async def test_actual_read_error_task_cancel_after_each_sql_rolls_back_and_closes(
    credential_reads: CredentialReadFixture,
    flow: str,
    stage: str,
    occurrence: int,
    cancel: bool,
    record_property: Callable[[str, object], None],
) -> None:
    fixture = credential_reads
    subject = await seed_credential_subject(
        fixture.manager,
        password=True,
        primary_verified=False,
        secondary_verified=True,
        disabled=False,
    )
    before = await credential_rows(fixture, subject.user_id)
    fixture.fault.stage = stage
    fixture.fault.occurrence = occurrence
    fixture.fault.pause = cancel
    if not cancel:
        fixture.fault.error = RuntimeError("after actual credential SQL read")

    async def read() -> None:
        if flow == "user":
            await fixture.repository.read_user_snapshot(
                user_id=subject.user_id, kinds=(PASSWORD, EMAIL)
            )
        else:
            await fixture.repository.read_login_snapshot(
                email=subject.primary_email, kinds=(PASSWORD, EMAIL)
            )

    task = asyncio.create_task(read())
    try:
        if cancel:
            await asyncio.wait_for(fixture.fault.reached.wait(), timeout=10)
            task.cancel("after real query returned before read completion")
        with pytest.raises(asyncio.CancelledError if cancel else RuntimeError):
            await task
        assert fixture.fault.reached.is_set()
        assert fixture.scope.commits == 0 and fixture.scope.failures == 1
        assert fixture.fault.trace[-1].stage == stage
        assert fixture.fault.trace[-1].occurrence == occurrence
        fixture.scope.assert_closed()
        assert await credential_rows(fixture, subject.user_id) == before
        record_property("flow", flow)
        record_property("read_stage", stage)
        record_property("read_occurrence", occurrence)
        record_property(
            "read_witness",
            "await_real_query_then_explicit_barrier"
            if cancel
            else "after_await_real_query",
        )
        record_property("actual_task_cancel", cancel)
    finally:
        fixture.fault.release.set()
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)


class StandaloneCredentialManager:
    """Pin a real connection for an isolated committed late-absence witness."""

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


@pytest.mark.parametrize("change", ["delete", "disable"])
async def test_late_user_change_preserves_plain_read_rules(
    rdb_engine: AsyncEngine,
    latest_db_schema: None,
    change: str,
    monkeypatch: pytest.MonkeyPatch,
    record_property: Callable[[str, object], None],
) -> None:
    del latest_db_schema
    async with rdb_engine.connect() as reader_connection:
        manager = StandaloneCredentialManager(reader_connection)
        fixture = credential_read_fixture(manager, monkeypatch)
        subject = await seed_credential_subject(
            manager,
            password=True,
            primary_verified=False,
            secondary_verified=True,
            disabled=False,
        )
        fixture.fault.stage = "user_get"
        fixture.fault.occurrence = 1
        fixture.fault.pause = True
        task = asyncio.create_task(
            fixture.repository.read_user_snapshot(
                user_id=subject.user_id, kinds=(PASSWORD, EMAIL, EMAIL)
            )
        )
        try:
            await asyncio.wait_for(fixture.fault.reached.wait(), timeout=10)
            reader_pid = manager.pids[-1]
            async with rdb_engine.connect() as writer_connection:
                writer = StandaloneCredentialManager(writer_connection)
                async with writer() as session:
                    writer_pid = writer.pids[-1]
                    assert reader_pid != writer_pid
                    if change == "delete":
                        await session.execute(
                            sa.delete(RDBUser).where(RDBUser.id == subject.user_id)
                        )
                    else:
                        await UserRepository().disable_access(
                            session, subject.user_id, disabled_at=datetime.now(UTC)
                        )
                async with writer() as session:
                    current = await session.get(RDBUser, subject.user_id)
                    if change == "delete":
                        assert current is None
                    else:
                        assert (
                            current is not None
                            and current.access_disabled_at is not None
                        )
            fixture.fault.release.set()
            snapshot = await asyncio.wait_for(task, timeout=10)
            assert snapshot == CredentialReadSnapshot(
                tuple(
                    CredentialReadFact(kind, change == "disable")
                    for kind in (PASSWORD, EMAIL, EMAIL)
                )
            )
            if change == "delete":
                assert fixture.fault.stages() == [
                    "user_get",
                    "password_exists",
                    "user_get",
                    "user_get",
                ]
                assert "email_list" not in fixture.fault.stages()
            else:
                assert fixture.fault.stages() == [
                    "user_get",
                    "password_exists",
                    "user_get",
                    "email_list",
                    "user_get",
                    "email_list",
                ]
            fixture.scope.assert_closed()
            record_property("reader_backend_pid", reader_pid)
            record_property("writer_backend_pid", writer_pid)
            record_property("committed_change", change)
            record_property(
                "read_witness",
                "independent_commit_between_plain_reads_no_serialization_claim",
            )
        finally:
            fixture.fault.release.set()
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            async with manager() as session:
                await session.execute(
                    sa.delete(RDBUser).where(RDBUser.id == subject.user_id)
                )
                await session.execute(
                    sa.delete(RDBUserEmail).where(
                        RDBUserEmail.user_id == subject.user_id
                    )
                )
