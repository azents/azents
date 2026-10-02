"""Genuine PostgreSQL shared OAuth atomicity and committed final-reread proofs."""

import asyncio
import dataclasses
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any
from uuid import uuid4

import pytest
import sqlalchemy as sa
from azcommon.result import Failure, Result, Success
from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import event
from sqlalchemy.engine import Connection, ExecutionContext
from sqlalchemy.engine import Result as SQLResult
from sqlalchemy.engine.interfaces import _CoreAnyExecuteParams
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, AsyncSession
from sqlalchemy.orm._typing import OrmExecuteOptionsParameter
from sqlalchemy.orm.session import _BindArguments
from sqlalchemy.sql.base import Executable
from sqlalchemy.sql.dml import Delete, Insert
from sqlalchemy.util import EMPTY_DICT

from azents.core.account_access import ActiveAccountSubjectStatus
from azents.core.auth.permissions import Permissions, has_permission
from azents.core.auth.roles import get_permissions_for_role
from azents.core.config import Config
from azents.core.crypto import CredentialCipher
from azents.core.enums import MCPOAuthConnectionStatus, WorkspaceUserRole
from azents.core.mcp_discovery import OAuthServerMetadata
from azents.core.oauth2 import (
    OAuthTokenResponse,
    create_platform_oauth_state,
    create_toolkit_oauth_state,
)
from azents.core.system_setting import SystemSettingFieldSource
from azents.core.workspace import WorkspaceCreate
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.github_user_installation import RDBGithubUserInstallation
from azents.rdb.models.session import RDBSession
from azents.rdb.models.toolkit import RDBMCPOAuthConnection, RDBToolkitConfig
from azents.rdb.models.user import RDBUser
from azents.rdb.models.user_email import RDBUserEmail
from azents.rdb.models.workspace import RDBWorkspace
from azents.rdb.models.workspace_user import RDBWorkspaceUser
from azents.rdb.session import SessionManager
from azents.repos.account_access import AccountAccessOperationRepository
from azents.repos.github_user_installation import GithubUserInstallationRepository
from azents.repos.mcp_oauth_connection import MCPOAuthConnectionRepository
from azents.repos.mcp_oauth_connection.data import MCPOAuthConnection
from azents.repos.owner_lifecycle import OwnerLifecycleRepository
from azents.repos.session import SessionRepository
from azents.repos.session.data import Session, SessionCreate
from azents.repos.toolkit import ToolkitRepository
from azents.repos.toolkit.data import ToolkitConfig, ToolkitCreate
from azents.repos.toolkit_oauth_data import (
    GithubInstallationRecord,
    ToolkitOAuthDenialReason,
    ToolkitOAuthDenied,
    ToolkitOAuthRequester,
)
from azents.repos.toolkit_oauth_operations import ToolkitOAuthOperationRepository
from azents.repos.toolkit_operations.owned_data import OAuthConnectionWrite
from azents.repos.user import UserRepository
from azents.repos.user.data import User, UserCreate
from azents.repos.workspace import WorkspaceRepository
from azents.repos.workspace.data import Workspace
from azents.repos.workspace_user import WorkspaceUserRepository
from azents.repos.workspace_user.data import WorkspaceUser, WorkspaceUserCreate
from azents.repos.workspace_user.operations import WorkspaceUserOperationRepository
from azents.services.github_platform_system_setting.runtime import (
    PlatformGitHubAppRuntimeService,
    ResolvedPlatformGitHubApp,
)
from azents.services.toolkit_oauth import helpers as oauth_helpers
from azents.services.toolkit_oauth import service as oauth_service_module
from azents.services.toolkit_oauth.data import ToolkitOAuthError
from azents.services.toolkit_oauth.service import ToolkitOAuthService


class OAuthScope:
    """Observe the real infrastructure lifetime; no fake commit/SQL adapter."""

    def __init__(self, manager: SessionManager[AsyncSession]) -> None:
        self.manager = manager
        self.sessions: list[AsyncSession] = []
        self.active: list[AsyncSession] = []
        self.commits = 0
        self.failures = 0
        self.fault: OAuthFault | None = None

    @asynccontextmanager
    async def __call__(self) -> AsyncIterator[AsyncSession]:
        assert not self.active, "Completed OAuth operations must not nest"
        try:
            async with self.manager() as session:
                self.sessions.append(session)
                self.active.append(session)
                connection = await session.connection()
                fault = self.fault
                if fault is not None:
                    event.listen(
                        connection.sync_connection,
                        "after_cursor_execute",
                        fault.after_sql,
                    )
                try:
                    yield session
                finally:
                    if fault is not None:
                        event.remove(
                            connection.sync_connection,
                            "after_cursor_execute",
                            fault.after_sql,
                        )
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


class OAuthFault:
    """Typed post-primitive seams and real installation SQL execution witnesses."""

    def __init__(self, scope: OAuthScope) -> None:
        self.scope = scope
        self.stage: str | None = None
        self.error: RuntimeError | None = None
        self.pause = False
        self.reached = asyncio.Event()
        self.release = asyncio.Event()
        self.trace: list[tuple[str, AsyncSession]] = []
        self.installation_inputs: list[list[dict[str, object]]] = []
        self.sql_trace: list[str] = []
        self.sql_stage: str | None = None
        self.sql_cancel = False

    async def point(self, stage: str, session: AsyncSession) -> None:
        assert self.scope.active == [session]
        assert session.in_transaction()
        self.trace.append((stage, session))
        if stage == self.stage:
            self.reached.set()
            if self.pause:
                await self.release.wait()
            if self.error is not None:
                raise self.error

    def after_sql(
        self,
        connection: Connection,
        cursor: object,
        statement: str,
        parameters: object,
        context: ExecutionContext,
        executemany: bool,
    ) -> None:
        """Fault only after actual installation upsert or prune has executed."""
        del connection, cursor, parameters, context, executemany
        stage: str | None = None
        if statement.lstrip().startswith("INSERT INTO github_user_installations"):
            stage = "installation_write"
        elif statement.lstrip().startswith("DELETE FROM github_user_installations"):
            stage = "installation_prune"
        if stage is None:
            return
        self.sql_trace.append(stage)
        if stage != self.sql_stage:
            return
        if self.sql_cancel:
            return  # The post-execute async barrier owns deterministic cancellation.
        self.reached.set()
        if self.error is not None:
            raise self.error

    def stages(self) -> list[str]:
        return [stage for stage, _ in self.trace]


class OAuthToolkits(ToolkitRepository):
    def __init__(self, cipher: CredentialCipher, fault: OAuthFault) -> None:
        super().__init__(cipher)
        self.fault = fault

    async def get_shared_by_id(
        self, session: AsyncSession, toolkit_id: str
    ) -> ToolkitConfig | None:
        result = await super().get_shared_by_id(session, toolkit_id)
        await self.fault.point("toolkit", session)
        return result


class OAuthConnections(MCPOAuthConnectionRepository):
    def __init__(self, cipher: CredentialCipher, fault: OAuthFault) -> None:
        super().__init__(cipher)
        self.fault = fault

    async def get_by_toolkit_id(
        self, session: AsyncSession, toolkit_id: str
    ) -> MCPOAuthConnection | None:
        result = await super().get_by_toolkit_id(session, toolkit_id)
        await self.fault.point("connection", session)
        return result

    async def upsert_connected(
        self,
        session: AsyncSession,
        *,
        toolkit_id: str,
        issuer: str | None,
        resource: str | None,
        server_url: str,
        authorization_endpoint: str,
        token_endpoint: str,
        registration_endpoint: str | None,
        client_id: str,
        client_secret: str | None,
        token_endpoint_auth_method: str,
        scope: str | None,
        access_token: str | None,
        refresh_token: str | None,
        expires_at: datetime | None,
    ) -> MCPOAuthConnection:
        result = await super().upsert_connected(
            session,
            toolkit_id=toolkit_id,
            issuer=issuer,
            resource=resource,
            server_url=server_url,
            authorization_endpoint=authorization_endpoint,
            token_endpoint=token_endpoint,
            registration_endpoint=registration_endpoint,
            client_id=client_id,
            client_secret=client_secret,
            token_endpoint_auth_method=token_endpoint_auth_method,
            scope=scope,
            access_token=access_token,
            refresh_token=refresh_token,
            expires_at=expires_at,
        )
        await self.fault.point("upsert", session)
        return result

    async def delete_by_toolkit_id(
        self, session: AsyncSession, toolkit_id: str
    ) -> None:
        await super().delete_by_toolkit_id(session, toolkit_id)
        await self.fault.point("delete", session)


class OAuthInstallations(GithubUserInstallationRepository):
    def __init__(self, fault: OAuthFault) -> None:
        self.fault = fault

    async def sync(
        self,
        session: AsyncSession,
        user_id: str,
        platform_app_id: str,
        installations: list[dict[str, object]],
    ) -> None:
        self.fault.installation_inputs.append(installations)
        await super().sync(session, user_id, platform_app_id, installations)
        await self.fault.point("sync", session)


class OAuthUsers(UserRepository):
    def __init__(self, fault: OAuthFault) -> None:
        self.fault = fault

    async def get(self, session: AsyncSession, user_id: str) -> User | None:
        result = await super().get(session, user_id)
        await self.fault.point("user", session)
        return result


class OAuthSessions(SessionRepository):
    def __init__(self, fault: OAuthFault) -> None:
        self.fault = fault

    async def get(self, session: AsyncSession, session_id: str) -> Session | None:
        result = await super().get(session, session_id)
        await self.fault.point("session", session)
        return result


class OAuthWorkspaces(WorkspaceRepository):
    def __init__(self, fault: OAuthFault) -> None:
        self.fault = fault

    async def get_by_id(
        self, session: AsyncSession, workspace_id: str
    ) -> Workspace | None:
        result = await super().get_by_id(session, workspace_id)
        await self.fault.point("workspace", session)
        return result


class OAuthMembers(WorkspaceUserRepository):
    def __init__(self, fault: OAuthFault) -> None:
        self.fault = fault

    async def get_by_workspace_and_user(
        self,
        session: AsyncSession,
        workspace_id: str,
        user_id: str,
    ) -> WorkspaceUser | None:
        result = await super().get_by_workspace_and_user(session, workspace_id, user_id)
        await self.fault.point("membership", session)
        return result


@dataclasses.dataclass(frozen=True)
class OAuthSubject:
    requester: ToolkitOAuthRequester
    other_user_id: str
    other_session_id: str
    foreign_workspace_id: str
    member_id: str
    other_member_id: str
    toolkit_id: str
    handle: str


@dataclasses.dataclass(frozen=True)
class OAuthFixture:
    manager: SessionManager[AsyncSession]
    scope: OAuthScope
    fault: OAuthFault
    repository: ToolkitOAuthOperationRepository
    cipher: CredentialCipher
    subject: OAuthSubject


async def oauth_fixture(manager: SessionManager[AsyncSession]) -> OAuthFixture:
    cipher = CredentialCipher(Fernet.generate_key().decode())
    async with manager() as session:
        users = UserRepository()
        user = await users.create(
            session, UserCreate(email=f"oauth-{uuid4().hex}@example.test")
        )
        other = await users.create(
            session, UserCreate(email=f"oauth-other-{uuid4().hex}@example.test")
        )
        auth = await SessionRepository().create(
            session,
            SessionCreate(
                user_id=user.id,
                refresh_token=uuid4().hex,
                expires_at=datetime.now(UTC) + timedelta(hours=1),
            ),
        )
        foreign_auth = await SessionRepository().create(
            session,
            SessionCreate(
                user_id=other.id,
                refresh_token=uuid4().hex,
                expires_at=datetime.now(UTC) + timedelta(hours=1),
            ),
        )
        handle = f"oauth-{uuid4().hex}"
        workspace = await WorkspaceRepository().create(
            session, WorkspaceCreate(name="OAuth test", handle=handle)
        )
        foreign = await WorkspaceRepository().create(
            session,
            WorkspaceCreate(name="OAuth foreign", handle=f"foreign-{uuid4().hex}"),
        )
        assert isinstance(workspace, Success) and isinstance(foreign, Success)
        workspace_id = await WorkspaceRepository().resolve_id(session, handle)
        foreign_workspace_id = await WorkspaceRepository().resolve_id(
            session, foreign.value.handle
        )
        assert workspace_id is not None and foreign_workspace_id is not None
        member = await WorkspaceUserRepository().create(
            session,
            WorkspaceUserCreate(
                workspace_id=workspace_id,
                user_id=user.id,
                name="Requester",
                role=WorkspaceUserRole.MANAGER,
            ),
        )
        other_member = await WorkspaceUserRepository().create(
            session,
            WorkspaceUserCreate(
                workspace_id=workspace_id,
                user_id=other.id,
                name="Other",
                role=WorkspaceUserRole.MEMBER,
            ),
        )
        assert isinstance(member, Success) and isinstance(other_member, Success)
        toolkit = await ToolkitRepository(cipher).create(
            session,
            ToolkitCreate(
                workspace_id=workspace_id,
                owner_agent_id=None,
                toolkit_type="mcp",
                slug="oauth-test",
                name="OAuth test",
                config={
                    "server_url": "https://provider.example.test/mcp",
                    "auth_type": "oauth2",
                },
                credentials='{"manual_client": "synthetic"}',
                always_expose_tools=False,
            ),
        )
        subject = OAuthSubject(
            requester=ToolkitOAuthRequester(
                user_id=user.id, session_id=auth.id, workspace_id=workspace_id
            ),
            other_user_id=other.id,
            other_session_id=foreign_auth.id,
            foreign_workspace_id=foreign_workspace_id,
            member_id=member.value.id,
            other_member_id=other_member.value.id,
            toolkit_id=toolkit.id,
            handle=handle,
        )
    scope = OAuthScope(manager)
    fault = OAuthFault(scope)
    scope.fault = fault
    repository = ToolkitOAuthOperationRepository(
        session_manager=scope,
        toolkit_repository=OAuthToolkits(cipher, fault),
        connection_repository=OAuthConnections(cipher, fault),
        installation_repository=OAuthInstallations(fault),
        user_repository=OAuthUsers(fault),
        session_repository=OAuthSessions(fault),
        workspace_repository=OAuthWorkspaces(fault),
        workspace_user_repository=OAuthMembers(fault),
    )
    return OAuthFixture(manager, scope, fault, repository, cipher, subject)


def connection_write(*, tokens: bool, label: str) -> OAuthConnectionWrite:
    return OAuthConnectionWrite(
        issuer=f"https://{label}.example.test",
        resource=f"https://{label}.example.test/resource",
        server_url=f"https://{label}.example.test/mcp",
        authorization_endpoint=f"https://{label}.example.test/authorize",
        token_endpoint=f"https://{label}.example.test/token",
        registration_endpoint=f"https://{label}.example.test/register",
        client_id=f"synthetic-client-{label}",
        client_secret=f"synthetic-secret-{label}",
        token_endpoint_auth_method="client_secret_post",
        scope=f"read:{label}",
        access_token=f"synthetic-access-{label}" if tokens else None,
        refresh_token=f"synthetic-refresh-{label}" if tokens else None,
        expires_at=datetime(2027, 1, 1, tzinfo=UTC) if tokens else None,
    )


def installation(
    installation_id: int, *, login: str, avatar: str
) -> GithubInstallationRecord:
    return GithubInstallationRecord(installation_id, login, "Organization", avatar)


async def store(
    fixture: OAuthFixture, connection: OAuthConnectionWrite
) -> Result[None, ToolkitOAuthDenied]:
    return await fixture.repository.store_shared_connection(
        requester=fixture.subject.requester,
        toolkit_id=fixture.subject.toolkit_id,
        connection=connection,
    )


async def connection_row(fixture: OAuthFixture) -> dict[str, object] | None:
    async with fixture.manager() as session:
        result = await session.execute(
            sa.select(*RDBMCPOAuthConnection.__table__.columns).where(
                RDBMCPOAuthConnection.toolkit_id == fixture.subject.toolkit_id
            )
        )
        row = result.mappings().one_or_none()
        return None if row is None else dict(row)


async def installation_rows(fixture: OAuthFixture) -> list[dict[str, object]]:
    async with fixture.manager() as session:
        result = await session.execute(
            sa.select(*RDBGithubUserInstallation.__table__.columns)
            .where(
                RDBGithubUserInstallation.user_id.in_(
                    (fixture.subject.requester.user_id, fixture.subject.other_user_id)
                )
            )
            .order_by(
                RDBGithubUserInstallation.user_id,
                RDBGithubUserInstallation.platform_app_id,
                RDBGithubUserInstallation.installation_id,
            )
        )
        return [dict(row) for row in result.mappings().all()]


async def make_owned(fixture: OAuthFixture) -> None:
    """Defensive predicate setup, not a claim of a public ownership-transfer API."""
    async with fixture.manager() as session:
        agent = RDBAgent(
            workspace_id=fixture.subject.requester.workspace_id,
            name="OAuth owner",
            model_selection={},
            lightweight_model_selection={},
            selectable_model_options=[
                {
                    "label": "default",
                    "candidates": [
                        {
                            "model_selection": {},
                            "settings": {
                                "context_window_tokens": None,
                                "max_output_tokens": None,
                                "builtin_tools": [],
                            },
                        }
                    ],
                    "subagent_enabled": True,
                    "subagent_guidance": None,
                }
            ],
            main_model_label="default",
            lightweight_model_label="default",
        )
        session.add(agent)
        await session.flush()
        await session.execute(
            sa.update(RDBToolkitConfig)
            .where(RDBToolkitConfig.id == fixture.subject.toolkit_id)
            .values(owner_agent_id=agent.id)
        )


async def corrupt_identity(fixture: OAuthFixture, kind: str) -> str:
    if kind == "missing":
        return "0" * 32
    if kind == "owned":
        await make_owned(fixture)
    elif kind == "foreign":
        async with fixture.manager() as session:
            await session.execute(
                sa.update(RDBToolkitConfig)
                .where(RDBToolkitConfig.id == fixture.subject.toolkit_id)
                .values(workspace_id=fixture.subject.foreign_workspace_id)
            )
    return fixture.subject.toolkit_id


async def assert_fault(
    fixture: OAuthFixture,
    *,
    stage: str,
    cancel: bool,
    operation: str,
) -> None:
    fixture.fault.stage = stage
    fixture.fault.pause = cancel
    if not cancel:
        fixture.fault.error = RuntimeError("after genuine OAuth primitive")

    async def action() -> None:
        if operation == "pair":
            await fixture.repository.read_shared_context(
                toolkit_id=fixture.subject.toolkit_id
            )
        elif operation == "saved":
            await fixture.repository.read_shared_toolkit(
                workspace_id=fixture.subject.requester.workspace_id,
                toolkit_id=fixture.subject.toolkit_id,
            )
        elif operation == "optional":
            await fixture.repository.read_optional_shared_toolkit(
                workspace_id=fixture.subject.requester.workspace_id,
                toolkit_id=fixture.subject.toolkit_id,
            )
        elif operation == "store":
            await store(fixture, connection_write(tokens=True, label="replacement"))
        elif operation == "delete":
            await fixture.repository.delete_shared_connection(
                workspace_id=fixture.subject.requester.workspace_id,
                toolkit_id=fixture.subject.toolkit_id,
            )
        else:
            assert operation == "sync"
            await fixture.repository.sync_installations(
                requester=fixture.subject.requester,
                platform_app_id="app-main",
                installations=(installation(2, login="replacement", avatar=""),),
            )

    if cancel:
        task = asyncio.create_task(action())
        try:
            await asyncio.wait_for(fixture.fault.reached.wait(), timeout=10)
            task.cancel("after genuine OAuth primitive")
            with pytest.raises(asyncio.CancelledError):
                await task
        finally:
            fixture.fault.release.set()
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    else:
        with pytest.raises(RuntimeError, match="after genuine OAuth primitive"):
            await action()
    assert fixture.fault.reached.is_set()
    fixture.scope.assert_closed()


class PostSQLOAuthSession(AsyncSession):
    """Await real SQL execution before pausing; retain the vendor execute API."""

    def __init__(self, bind: AsyncEngine | AsyncConnection, fault: OAuthFault) -> None:
        super().__init__(bind, expire_on_commit=False)
        self.fault = fault

    async def execute(
        self,
        statement: Executable,
        params: _CoreAnyExecuteParams | None = None,
        *,
        execution_options: OrmExecuteOptionsParameter = EMPTY_DICT,
        bind_arguments: _BindArguments | None = None,
        **kw: Any,  # noqa: ANN401 - mirror SQLAlchemy's execution extension API.
    ) -> SQLResult[Any]:
        result = await super().execute(
            statement,
            params,
            execution_options=execution_options,
            bind_arguments=bind_arguments,
            **kw,
        )
        stage: str | None = None
        if isinstance(statement, (Insert, Delete)):
            if statement.table.description == RDBGithubUserInstallation.__tablename__:
                stage = (
                    "installation_write"
                    if isinstance(statement, Insert)
                    else "installation_prune"
                )
        if (
            self.fault.sql_cancel
            and stage == self.fault.sql_stage
            and stage is not None
        ):
            assert self.fault.scope.active == [self]
            assert self.in_transaction()
            self.fault.reached.set()
            await self.fault.release.wait()
        return result


class IndependentOAuthManager:
    """Real commits outside savepoints, with pinned distinct invalidation backend."""

    def __init__(
        self, bind: AsyncEngine | AsyncConnection, fault: OAuthFault | None
    ) -> None:
        self.bind = bind
        self.fault = fault
        self.pids: list[int] = []

    @asynccontextmanager
    async def __call__(self) -> AsyncIterator[AsyncSession]:
        session = (
            AsyncSession(self.bind, expire_on_commit=False)
            if self.fault is None
            else PostSQLOAuthSession(self.bind, self.fault)
        )
        async with session:
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


async def cleanup_independent(fixture: OAuthFixture) -> None:
    """Delete only UUID-seeded subjects, never broad table cleanup."""
    subject = fixture.subject
    async with fixture.manager() as session:
        await session.execute(
            sa.delete(RDBAgent).where(
                RDBAgent.workspace_id.in_(
                    (subject.requester.workspace_id, subject.foreign_workspace_id)
                )
            )
        )
        await session.execute(
            sa.delete(RDBWorkspace).where(
                RDBWorkspace.id.in_(
                    (subject.requester.workspace_id, subject.foreign_workspace_id)
                )
            )
        )
        await session.execute(
            sa.delete(RDBUser).where(
                RDBUser.id.in_((subject.requester.user_id, subject.other_user_id))
            )
        )
        await session.execute(
            sa.delete(RDBUserEmail).where(
                RDBUserEmail.user_id.in_(
                    (subject.requester.user_id, subject.other_user_id)
                )
            )
        )


class Invalidation(StrEnum):
    TOOLKIT_DELETE = "toolkit_delete"
    USER_DISABLE = "user_disable_membership_retained"
    USER_DELETE = "user_delete"
    SESSION_DELETE = "session_delete"
    SESSION_REVOKE = "session_revoke"
    SESSION_EXPIRE = "session_expire"
    SESSION_FOREIGN = "session_foreign"
    WORKSPACE_DELETE = "workspace_missing_defensive"
    MEMBERSHIP_REMOVE = "membership_remove"
    MEMBER_DEMOTION = "manager_to_member"
    OWNER_TRANSFER = "owner_to_manager_still_allowed"
    HANDLE_RENAME = "handle_rename_no_rebind"
    CONFIG_REPLACE = "config_credentials_revision_no_new_fence"
    CONNECTION_DELETE = "connection_missing_no_final_existence_fence"
    CONNECTION_REPLACE = "connection_credentials_status_no_new_fence"


async def invalidate(
    fixture: OAuthFixture, session: AsyncSession, mutation: Invalidation
) -> None:
    """Isolated committed SQL facts; defensive deletes are not public API claims."""
    subject = fixture.subject
    if mutation is Invalidation.TOOLKIT_DELETE:
        await session.execute(
            sa.delete(RDBToolkitConfig).where(RDBToolkitConfig.id == subject.toolkit_id)
        )
    elif mutation is Invalidation.USER_DISABLE:
        await session.execute(
            sa.update(RDBUser)
            .where(RDBUser.id == subject.requester.user_id)
            .values(access_disabled_at=datetime.now(UTC))
        )
        assert await session.get(RDBWorkspaceUser, subject.member_id) is not None
    elif mutation is Invalidation.USER_DELETE:
        await session.execute(
            sa.delete(RDBUser).where(RDBUser.id == subject.requester.user_id)
        )
    elif mutation is Invalidation.SESSION_DELETE:
        await session.execute(
            sa.delete(RDBSession).where(RDBSession.id == subject.requester.session_id)
        )
    elif mutation is Invalidation.SESSION_REVOKE:
        await SessionRepository().revoke(session, subject.requester.session_id)
    elif mutation is Invalidation.SESSION_EXPIRE:
        await session.execute(
            sa.update(RDBSession)
            .where(RDBSession.id == subject.requester.session_id)
            .values(expires_at=datetime.now(UTC) - timedelta(hours=1))
        )
    elif mutation is Invalidation.SESSION_FOREIGN:
        await session.execute(
            sa.update(RDBSession)
            .where(RDBSession.id == subject.requester.session_id)
            .values(user_id=subject.other_user_id)
        )
    elif mutation is Invalidation.WORKSPACE_DELETE:
        await session.execute(
            sa.delete(RDBWorkspace).where(
                RDBWorkspace.id == subject.requester.workspace_id
            )
        )
    elif mutation is Invalidation.MEMBERSHIP_REMOVE:
        await WorkspaceUserRepository().delete(session, subject.member_id)
    elif mutation is Invalidation.MEMBER_DEMOTION:
        await session.execute(
            sa.update(RDBWorkspaceUser)
            .where(RDBWorkspaceUser.id == subject.member_id)
            .values(role=WorkspaceUserRole.MEMBER)
        )
    elif mutation is Invalidation.HANDLE_RENAME:
        await session.execute(
            sa.update(RDBWorkspace)
            .where(RDBWorkspace.id == subject.requester.workspace_id)
            .values(handle=f"renamed-{uuid4().hex}")
        )
        await session.execute(
            sa.update(RDBWorkspace)
            .where(RDBWorkspace.id == subject.foreign_workspace_id)
            .values(handle=subject.handle)
        )
    elif mutation is Invalidation.CONFIG_REPLACE:
        result = await ToolkitRepository(fixture.cipher).update_by_id(
            session,
            subject.toolkit_id,
            {
                "config": {
                    "server_url": "https://concurrent.example.test/mcp",
                    "auth_type": "none",
                },
                "credentials": '{"changed": "synthetic"}',
                "enabled": False,
            },
        )
        assert isinstance(result, Success)
    elif mutation is Invalidation.CONNECTION_DELETE:
        await MCPOAuthConnectionRepository(fixture.cipher).delete_by_toolkit_id(
            session, subject.toolkit_id
        )
    elif mutation is Invalidation.CONNECTION_REPLACE:
        # This is the actual full narrow upsert, not a fabricated refresh CAS.
        replacement = connection_write(tokens=True, label="concurrent")
        raw = MCPOAuthConnectionRepository(fixture.cipher)
        await raw.upsert_connected(
            session,
            toolkit_id=subject.toolkit_id,
            issuer=replacement.issuer,
            resource=replacement.resource,
            server_url=replacement.server_url,
            authorization_endpoint=replacement.authorization_endpoint,
            token_endpoint=replacement.token_endpoint,
            registration_endpoint=replacement.registration_endpoint,
            client_id=replacement.client_id,
            client_secret=replacement.client_secret,
            token_endpoint_auth_method=replacement.token_endpoint_auth_method,
            scope=replacement.scope,
            access_token=replacement.access_token,
            refresh_token=replacement.refresh_token,
            expires_at=replacement.expires_at,
        )
        await raw.mark_reconnect_required(session, toolkit_id=subject.toolkit_id)
    else:
        assert mutation is Invalidation.OWNER_TRANSFER
        raise AssertionError(
            "Owner transfer needs its completed operation outside the observer"
        )


def expected_denial(mutation: Invalidation, *, flow: str) -> ToolkitOAuthDenied | None:
    statuses = {
        Invalidation.USER_DISABLE: ActiveAccountSubjectStatus.USER_DISABLED,
        Invalidation.USER_DELETE: ActiveAccountSubjectStatus.USER_MISSING,
        Invalidation.SESSION_DELETE: ActiveAccountSubjectStatus.SESSION_MISSING,
        Invalidation.SESSION_REVOKE: ActiveAccountSubjectStatus.SESSION_REVOKED,
        Invalidation.SESSION_EXPIRE: ActiveAccountSubjectStatus.SESSION_EXPIRED,
        Invalidation.SESSION_FOREIGN: ActiveAccountSubjectStatus.SESSION_FOREIGN,
    }
    if mutation in statuses:
        return ToolkitOAuthDenied(
            ToolkitOAuthDenialReason.INACTIVE_SUBJECT, statuses[mutation]
        )
    reasons = {
        Invalidation.WORKSPACE_DELETE: ToolkitOAuthDenialReason.WORKSPACE_NOT_FOUND,
        Invalidation.MEMBERSHIP_REMOVE: ToolkitOAuthDenialReason.MEMBERSHIP_REQUIRED,
        Invalidation.MEMBER_DEMOTION: (
            ToolkitOAuthDenialReason.WRITE_PERMISSION_REQUIRED
        ),
    }
    if mutation in reasons:
        return ToolkitOAuthDenied(reasons[mutation], None)
    if mutation is Invalidation.TOOLKIT_DELETE and flow != "sync":
        return ToolkitOAuthDenied(ToolkitOAuthDenialReason.TOOLKIT_NOT_FOUND, None)
    return None


@pytest.mark.parametrize("kind", ["shared", "missing", "owned", "foreign"])
async def test_pair_preserves_toolkit_then_connection_even_absent_and_detached(
    rdb_session_manager: SessionManager[AsyncSession],
    kind: str,
) -> None:
    fixture = await oauth_fixture(rdb_session_manager)
    assert await store(
        fixture, connection_write(tokens=True, label="original")
    ) == Success(None)
    key = await corrupt_identity(fixture, kind)
    fixture.fault.trace.clear()
    pair = await fixture.repository.read_shared_context(toolkit_id=key)
    assert fixture.fault.stages() == ["toolkit", "connection"]
    assert fixture.fault.trace[0][1] is fixture.fault.trace[1][1]
    assert dataclasses.is_dataclass(pair) and type(pair).__dataclass_params__.frozen
    if kind in {"missing", "owned"}:
        assert pair.toolkit is None
    else:
        assert pair.toolkit is not None
        assert pair.toolkit.workspace_id == (
            fixture.subject.foreign_workspace_id
            if kind == "foreign"
            else fixture.subject.requester.workspace_id
        ), "Pair read does not move the caller's exact Workspace guard"
        assert pair.toolkit.credentials == '{"manual_client": "synthetic"}'
        assert sa.inspect(pair.toolkit, raiseerr=False) is None
    if kind == "missing":
        assert pair.connection is None
    else:
        assert pair.connection is not None
        assert pair.connection.access_token == "synthetic-access-original"
        assert sa.inspect(pair.connection, raiseerr=False) is None
    fixture.scope.assert_closed()
    async with fixture.manager() as session:
        await session.execute(
            sa.delete(RDBMCPOAuthConnection).where(
                RDBMCPOAuthConnection.toolkit_id == fixture.subject.toolkit_id
            )
        )
    if pair.connection is not None:
        assert pair.connection.access_token == "synthetic-access-original"


@pytest.mark.parametrize("kind", ["shared", "missing", "owned", "foreign"])
async def test_saved_and_optional_snapshot_exact_shared_workspace_and_none_no_scope(
    rdb_session_manager: SessionManager[AsyncSession],
    kind: str,
) -> None:
    fixture = await oauth_fixture(rdb_session_manager)
    key = await corrupt_identity(fixture, kind)
    before = len(fixture.scope.sessions)
    assert (
        await fixture.repository.read_optional_shared_toolkit(
            workspace_id=fixture.subject.requester.workspace_id, toolkit_id=None
        )
        is None
    )
    assert len(fixture.scope.sessions) == before
    saved = await fixture.repository.read_shared_toolkit(
        workspace_id=fixture.subject.requester.workspace_id, toolkit_id=key
    )
    optional = await fixture.repository.read_optional_shared_toolkit(
        workspace_id=fixture.subject.requester.workspace_id, toolkit_id=key
    )
    assert saved == optional
    if kind == "shared":
        assert saved is not None and saved.id == key
        assert saved.owner_agent_id is None
    else:
        assert saved is None
    assert len(fixture.scope.sessions) == before + 2
    fixture.scope.assert_closed()


@pytest.mark.parametrize("column", ["toolkit_credentials", "client_id", "access_token"])
async def test_pair_cipher_failure_propagates_after_real_select_and_closes_scope(
    rdb_session_manager: SessionManager[AsyncSession],
    column: str,
) -> None:
    fixture = await oauth_fixture(rdb_session_manager)
    assert await store(
        fixture, connection_write(tokens=True, label="original")
    ) == Success(None)
    async with fixture.manager() as session:
        if column == "toolkit_credentials":
            await session.execute(
                sa.update(RDBToolkitConfig)
                .where(RDBToolkitConfig.id == fixture.subject.toolkit_id)
                .values(encrypted_credentials="invalid-test-ciphertext")
            )
        elif column == "client_id":
            await session.execute(
                sa.update(RDBMCPOAuthConnection)
                .where(RDBMCPOAuthConnection.toolkit_id == fixture.subject.toolkit_id)
                .values(encrypted_client_id="invalid-test-ciphertext")
            )
        else:
            await session.execute(
                sa.update(RDBMCPOAuthConnection)
                .where(RDBMCPOAuthConnection.toolkit_id == fixture.subject.toolkit_id)
                .values(encrypted_access_token="invalid-test-ciphertext")
            )
    with pytest.raises(InvalidToken):
        await fixture.repository.read_shared_context(
            toolkit_id=fixture.subject.toolkit_id
        )
    assert fixture.scope.failures == 1
    fixture.scope.assert_closed()


@pytest.mark.parametrize(
    "operation,stage",
    [
        ("pair", "toolkit"),
        ("pair", "connection"),
        ("saved", "toolkit"),
        ("optional", "toolkit"),
    ],
)
@pytest.mark.parametrize("cancel", [False, True])
async def test_real_read_fault_and_actual_task_cancel_close_without_mutation(
    rdb_session_manager: SessionManager[AsyncSession],
    operation: str,
    stage: str,
    cancel: bool,
) -> None:
    fixture = await oauth_fixture(rdb_session_manager)
    assert await store(
        fixture, connection_write(tokens=True, label="original")
    ) == Success(None)
    before = await connection_row(fixture)
    await assert_fault(fixture, stage=stage, cancel=cancel, operation=operation)
    assert await connection_row(fixture) == before
    assert fixture.scope.failures == 1


@pytest.mark.parametrize("tokens", [False, True])
async def test_full_upsert_encryption_connected_without_tokens_and_conflict_replacement(
    rdb_session_manager: SessionManager[AsyncSession],
    tokens: bool,
) -> None:
    fixture = await oauth_fixture(rdb_session_manager)
    initial = connection_write(tokens=tokens, label="original")
    assert await store(fixture, initial) == Success(None)
    pair = await fixture.repository.read_shared_context(
        toolkit_id=fixture.subject.toolkit_id
    )
    assert pair.connection is not None
    for field in dataclasses.fields(initial):
        assert (
            pair.connection.model_dump()[field.name]
            == dataclasses.asdict(initial)[field.name]
        )
    assert pair.connection.status is MCPOAuthConnectionStatus.CONNECTED
    row = await connection_row(fixture)
    assert row is not None
    for encrypted, plain in [
        ("encrypted_client_id", initial.client_id),
        ("encrypted_client_secret", initial.client_secret),
        ("encrypted_access_token", initial.access_token),
        ("encrypted_refresh_token", initial.refresh_token),
    ]:
        ciphertext = row[encrypted]
        if plain is None:
            assert ciphertext is None
        else:
            assert isinstance(ciphertext, str) and ciphertext != plain
            assert fixture.cipher.decrypt(ciphertext) == plain
    replacement = dataclasses.replace(
        connection_write(tokens=not tokens, label="replacement"),
        issuer=None,
        registration_endpoint=None,
        client_secret=None,
        token_endpoint_auth_method="none",
        scope=None,
    )
    assert await store(fixture, replacement) == Success(None)
    replaced = await fixture.repository.read_shared_context(
        toolkit_id=fixture.subject.toolkit_id
    )
    assert replaced.connection is not None
    assert replaced.connection.id == pair.connection.id
    assert replaced.connection.created_at == pair.connection.created_at
    for field in dataclasses.fields(replacement):
        assert (
            replaced.connection.model_dump()[field.name]
            == dataclasses.asdict(replacement)[field.name]
        )
    assert pair.connection.server_url == initial.server_url
    fixture.scope.assert_closed()


async def test_connect_retains_tokens_and_exchange_null_refresh_clears_row(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    fixture = await oauth_fixture(rdb_session_manager)
    initial = connection_write(tokens=True, label="original")
    assert await store(fixture, initial) == Success(None)
    captured = await fixture.repository.read_shared_context(
        toolkit_id=fixture.subject.toolkit_id
    )
    assert captured.connection is not None
    connect = dataclasses.replace(
        connection_write(tokens=False, label="connect"),
        access_token=captured.connection.access_token,
        refresh_token=captured.connection.refresh_token,
        expires_at=captured.connection.expires_at,
    )
    assert await store(fixture, connect) == Success(None)
    connected = await fixture.repository.read_shared_context(
        toolkit_id=fixture.subject.toolkit_id
    )
    assert connected.connection is not None
    assert connected.connection.client_id == connect.client_id
    assert connected.connection.access_token == initial.access_token
    assert connected.connection.refresh_token == initial.refresh_token
    exchanged = dataclasses.replace(
        connect, access_token="synthetic-exchanged", refresh_token=None, expires_at=None
    )
    assert await store(fixture, exchanged) == Success(None)
    final = await fixture.repository.read_shared_context(
        toolkit_id=fixture.subject.toolkit_id
    )
    assert final.connection is not None
    assert final.connection.access_token == "synthetic-exchanged"
    assert final.connection.refresh_token is final.connection.expires_at is None
    raw = await connection_row(fixture)
    assert raw is not None and raw["encrypted_refresh_token"] is None
    fixture.scope.assert_closed()


@pytest.mark.parametrize("existing", [False, True])
@pytest.mark.parametrize("cancel", [False, True])
async def test_actual_full_write_error_or_task_cancel_restores_entire_previous_row(
    rdb_session_manager: SessionManager[AsyncSession],
    existing: bool,
    cancel: bool,
) -> None:
    fixture = await oauth_fixture(rdb_session_manager)
    if existing:
        assert await store(
            fixture, connection_write(tokens=True, label="original")
        ) == Success(None)
    before = await connection_row(fixture)
    await assert_fault(fixture, stage="upsert", cancel=cancel, operation="store")
    assert await connection_row(fixture) == before
    fixture.scope.assert_closed()


@pytest.mark.parametrize(
    "stage", ["user", "session", "workspace", "membership", "toolkit"]
)
@pytest.mark.parametrize("cancel", [False, True])
async def test_final_authority_actual_read_fault_or_task_cancel_aborts_before_upsert(
    rdb_session_manager: SessionManager[AsyncSession],
    stage: str,
    cancel: bool,
) -> None:
    fixture = await oauth_fixture(rdb_session_manager)
    await assert_fault(fixture, stage=stage, cancel=cancel, operation="store")
    assert "upsert" not in fixture.fault.stages()
    assert await connection_row(fixture) is None


@pytest.mark.parametrize("kind", ["shared", "missing", "owned", "foreign"])
async def test_atomic_disconnect_guard_delete_and_missing_connection_idempotent(
    rdb_session_manager: SessionManager[AsyncSession],
    kind: str,
) -> None:
    fixture = await oauth_fixture(rdb_session_manager)
    assert await store(
        fixture, connection_write(tokens=True, label="original")
    ) == Success(None)
    key = await corrupt_identity(fixture, kind)
    before = await connection_row(fixture)
    fixture.fault.trace.clear()
    result = await fixture.repository.delete_shared_connection(
        workspace_id=fixture.subject.requester.workspace_id, toolkit_id=key
    )
    if kind == "shared":
        assert result == Success(None)
        assert fixture.fault.stages() == ["toolkit", "delete"]
        assert fixture.fault.trace[0][1] is fixture.fault.trace[1][1]
        assert await connection_row(fixture) is None
        assert await fixture.repository.delete_shared_connection(
            workspace_id=fixture.subject.requester.workspace_id, toolkit_id=key
        ) == Success(None)
    else:
        assert result == Failure(
            ToolkitOAuthDenied(ToolkitOAuthDenialReason.TOOLKIT_NOT_FOUND, None)
        )
        assert fixture.fault.stages() == ["toolkit"]
        assert await connection_row(fixture) == before
    fixture.scope.assert_closed()


@pytest.mark.parametrize("cancel", [False, True])
async def test_disconnect_fault_or_task_cancel_after_real_delete_restores_connection(
    rdb_session_manager: SessionManager[AsyncSession],
    cancel: bool,
) -> None:
    fixture = await oauth_fixture(rdb_session_manager)
    assert await store(
        fixture, connection_write(tokens=True, label="original")
    ) == Success(None)
    before = await connection_row(fixture)
    await assert_fault(fixture, stage="delete", cancel=cancel, operation="delete")
    assert await connection_row(fixture) == before
    assert fixture.fault.stages()[-2:] == ["toolkit", "delete"]


async def test_installation_order_duplicates_avatar_and_user_app_isolation(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    fixture = await oauth_fixture(rdb_session_manager)
    initial = (
        installation(1, login="removed", avatar=""),
        installation(2, login="old", avatar="old-avatar"),
    )
    assert await fixture.repository.sync_installations(
        requester=fixture.subject.requester,
        platform_app_id="app-main",
        installations=initial,
    ) == Success(None)
    before = await installation_rows(fixture)
    async with fixture.manager() as session:
        raw = GithubUserInstallationRepository()
        await raw.sync(
            session,
            fixture.subject.requester.user_id,
            "app-other",
            [{"id": 1, "account": {"login": "other-app", "type": "User"}}],
        )
        await raw.sync(
            session,
            fixture.subject.other_user_id,
            "app-main",
            [{"id": 1, "account": {"login": "other-user", "type": "Organization"}}],
        )
    records = (
        installation(2, login="first", avatar=""),
        installation(3, login="no-avatar", avatar=""),
        installation(2, login="last", avatar="last-avatar"),
    )
    fixture.fault.trace.clear()
    assert await fixture.repository.sync_installations(
        requester=fixture.subject.requester,
        platform_app_id="app-main",
        installations=records,
    ) == Success(None)
    assert fixture.fault.stages() == [
        "user",
        "session",
        "workspace",
        "membership",
        "sync",
    ]
    assert len({id(session) for _, session in fixture.fault.trace}) == 1
    assert fixture.fault.installation_inputs[-1] == [
        {
            "id": r.installation_id,
            "account": {
                "login": r.account_login,
                "type": r.account_type,
                "avatar_url": r.account_avatar_url,
            },
        }
        for r in records
    ]
    rows = await installation_rows(fixture)
    own = [
        r
        for r in rows
        if r["user_id"] == fixture.subject.requester.user_id
        and r["platform_app_id"] == "app-main"
    ]
    assert [r["installation_id"] for r in own] == [2, 3]
    assert own[0]["id"] == before[1]["id"]
    assert (
        own[0]["account_login"] == "last"
        and own[0]["account_avatar_url"] == "last-avatar"
    )
    assert own[1]["account_avatar_url"] == ""
    assert {r["account_login"] for r in rows} == {
        "last",
        "no-avatar",
        "other-app",
        "other-user",
    }
    fixture.scope.assert_closed()


@pytest.mark.parametrize("source", ["empty", "all_invalid"])
async def test_empty_or_decoded_all_invalid_installations_prune_exact_user_app(
    rdb_session_manager: SessionManager[AsyncSession],
    source: str,
) -> None:
    fixture = await oauth_fixture(rdb_session_manager)
    assert await fixture.repository.sync_installations(
        requester=fixture.subject.requester,
        platform_app_id="app-main",
        installations=(installation(1, login="old", avatar=""),),
    ) == Success(None)
    async with fixture.manager() as session:
        await GithubUserInstallationRepository().sync(
            session,
            fixture.subject.requester.user_id,
            "app-other",
            [{"id": 2, "account": {"login": "keep", "type": "User"}}],
        )
    records = (
        ()
        if source == "empty"
        else oauth_helpers.decode_installations(
            [
                {"id": "wrong", "account": {}},
                {"id": 1, "account": None},
                {"id": 2, "account": {"login": None, "type": "User"}},
            ]
        )
    )
    assert records == ()
    assert await fixture.repository.sync_installations(
        requester=fixture.subject.requester,
        platform_app_id="app-main",
        installations=records,
    ) == Success(None)
    rows = await installation_rows(fixture)
    assert len(rows) == 1 and rows[0]["platform_app_id"] == "app-other"
    fixture.scope.assert_closed()


async def test_original_avatar_persistence_projection_distinction_survives_actual_sync(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    fixture = await oauth_fixture(rdb_session_manager)
    raw: list[dict[str, object]] = [
        {"id": 1, "account": {"login": "missing-avatar", "type": "User"}},
        {
            "id": 2,
            "account": {
                "login": "invalid-avatar",
                "type": "Organization",
                "avatar_url": None,
            },
        },
        {
            "id": 3,
            "account": {"login": "valid-avatar", "type": "User", "avatar_url": ""},
        },
    ]
    records = oauth_helpers.decode_installations(raw)
    assert [r.account_avatar_url for r in records] == ["", "", ""]
    assert await fixture.repository.sync_installations(
        requester=fixture.subject.requester,
        platform_app_id="app-main",
        installations=records,
    ) == Success(None)
    assert [r["installation_id"] for r in await installation_rows(fixture)] == [1, 2, 3]
    assert [r.id for r in oauth_helpers.project_installations(raw)] == [3]
    fixture.scope.assert_closed()


@pytest.mark.parametrize("stage", ["installation_write", "installation_prune"])
@pytest.mark.parametrize("cancel", [False, True])
async def test_installation_sql_fault_task_cancel_after_write_prune_restores_batch(
    rdb_engine: AsyncEngine,
    latest_db_schema: None,
    stage: str,
    cancel: bool,
    record_property: Callable[[str, object], None],
) -> None:
    del latest_db_schema
    manager = IndependentOAuthManager(rdb_engine, None)
    fixture = await oauth_fixture(manager)
    manager.fault = fixture.fault
    assert await fixture.repository.sync_installations(
        requester=fixture.subject.requester,
        platform_app_id="app-main",
        installations=(
            installation(1, login="prunable", avatar="old"),
            installation(2, login="overwritable", avatar="old"),
        ),
    ) == Success(None)
    before = await installation_rows(fixture)
    fixture.fault.sql_trace.clear()
    fixture.fault.sql_stage = stage
    fixture.fault.sql_cancel = cancel
    if not cancel:
        fixture.fault.error = RuntimeError("after actual installation SQL")
    task = asyncio.create_task(
        fixture.repository.sync_installations(
            requester=fixture.subject.requester,
            platform_app_id="app-main",
            installations=(
                installation(2, login="changed", avatar="new"),
                installation(3, login="inserted", avatar=""),
            ),
        )
    )
    try:
        if cancel:
            await asyncio.wait_for(fixture.fault.reached.wait(), timeout=10)
            task.cancel("after actual installation execute returned")
        with pytest.raises(asyncio.CancelledError if cancel else RuntimeError):
            await task
        assert fixture.fault.reached.is_set()
        assert stage in fixture.fault.sql_trace
        if stage == "installation_prune":
            assert fixture.fault.sql_trace == [
                "installation_write",
                "installation_write",
                "installation_prune",
            ]
        else:
            assert fixture.fault.sql_trace == ["installation_write"]
        record_property("fault_stage", stage)
        record_property("actual_task_cancel", cancel)
        record_property(
            "sql_witness",
            "real_super_execute_returned" if cancel else "after_actual_cursor_execute",
        )
        assert await installation_rows(fixture) == before
        assert fixture.scope.failures == 1
        fixture.scope.assert_closed()
    finally:
        fixture.fault.release.set()
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        fixture.fault.sql_stage = None
        fixture.fault.sql_cancel = False
        await cleanup_independent(fixture)


@pytest.mark.parametrize("cancel", [False, True])
async def test_installation_post_complete_sync_fault_cancel_rolls_back_upsert_and_prune(
    rdb_session_manager: SessionManager[AsyncSession],
    cancel: bool,
) -> None:
    fixture = await oauth_fixture(rdb_session_manager)
    assert await fixture.repository.sync_installations(
        requester=fixture.subject.requester,
        platform_app_id="app-main",
        installations=(installation(1, login="original", avatar=""),),
    ) == Success(None)
    before = await installation_rows(fixture)
    await assert_fault(fixture, stage="sync", cancel=cancel, operation="sync")
    assert await installation_rows(fixture) == before


async def test_empty_app_id_transparently_raises_without_pruning(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    fixture = await oauth_fixture(rdb_session_manager)
    assert await fixture.repository.sync_installations(
        requester=fixture.subject.requester,
        platform_app_id="app-main",
        installations=(installation(1, login="original", avatar=""),),
    ) == Success(None)
    before = await installation_rows(fixture)
    with pytest.raises(ValueError, match="Platform GitHub App ID is required"):
        await fixture.repository.sync_installations(
            requester=fixture.subject.requester, platform_app_id="", installations=()
        )
    assert await installation_rows(fixture) == before
    fixture.scope.assert_closed()


def synthetic_config() -> Config:
    """Validate explicit test values without Settings/environment/production PG."""
    return Config.model_validate(
        {
            "runtime_env": "local",
            "sentry_dsn": None,
            "rdb": {
                "host": "unused.example.test",
                "port": 5432,
                "user": "unused",
                "password": None,
                "db_name": "unused",
            },
            "auth": {
                "jwt": {"secret_key": "synthetic-only"},
                "refresh_token": {},
                "signup_token": {},
            },
            "system_bootstrap": {"setup_token": None},
            "runtime_provider_bootstrap": {
                "source_key": None,
                "source_path": None,
                "poll_interval_seconds": 10.0,
            },
            "email": None,
            "credential_encryption": {"key": "synthetic-oauth-state-key"},
            "redis": {"url": "redis://unused.example.test"},
            "runtime_transfer_coordinator": {
                "endpoint": None,
                "tls_ca_file": None,
                "allow_insecure": False,
                "credential_lifetime_seconds": 60.0,
            },
            "model_stream_timeout": {
                "connect_timeout_seconds": 10.0,
                "parsed_event_idle_timeout_seconds": 10.0,
                "absolute_attempt_timeout_seconds": 30.0,
                "close_grace_seconds": 1.0,
            },
            "openai_responses_websocket_enabled": False,
            "workspace_s3": {"bucket": "unused"},
            "web_url": "https://web.example.test",
        }
    )


class SyntheticPlatformRuntime(PlatformGitHubAppRuntimeService):
    """A typed external snapshot double; no config source or DB lifetime fake."""

    def __init__(self) -> None:
        """The overridden resolve needs no System Settings collaborator."""

    async def resolve(self) -> ResolvedPlatformGitHubApp:
        return ResolvedPlatformGitHubApp(
            app_id="app-main",
            client_id="synthetic-github-client",
            private_key=None,
            client_secret="synthetic-github-secret",
            app_id_source=SystemSettingFieldSource.ADMIN,
            effective_generation="synthetic-generation",
        )


async def admit_before_http(fixture: OAuthFixture) -> None:
    """Use existing actual admission reads instead of inventing a JWT policy."""
    repository = fixture.repository
    admission = AccountAccessOperationRepository(
        session_manager=fixture.scope,
        user_repository=repository.user_repository,
        session_repository=repository.session_repository,
        workspace_repository=repository.workspace_repository,
        workspace_user_repository=repository.workspace_user_repository,
    )
    requester = fixture.subject.requester
    assert (
        await admission.read_active_subject(
            user_id=requester.user_id, session_id=requester.session_id
        )
        is ActiveAccountSubjectStatus.ACTIVE
    )
    membership = await admission.read_workspace_membership(
        handle=fixture.subject.handle, user_id=requester.user_id
    )
    assert membership.workspace_id == requester.workspace_id
    assert membership.membership is not None
    assert has_permission(
        get_permissions_for_role(membership.membership.role), Permissions.TOOLKITS_WRITE
    )
    fixture.scope.assert_closed()


def install_service_external_gap(
    monkeypatch: pytest.MonkeyPatch,
    fixture: OAuthFixture,
    *,
    flow: str,
    reached: asyncio.Event,
    release: asyncio.Event,
    calls: list[str],
) -> None:
    """Pause an actual service HTTP seam, never an injected repository callback."""

    async def gap() -> None:
        fixture.scope.assert_closed()
        calls.append("paused_external")
        reached.set()
        await release.wait()
        fixture.scope.assert_closed()

    async def metadata(*args: object, **kwargs: object) -> OAuthServerMetadata:
        del args, kwargs
        await gap()
        return OAuthServerMetadata(
            authorization_endpoint="https://new.example.test/authorize",
            token_endpoint="https://new.example.test/token",
            registration_endpoint=None,
            scopes_supported=[],
            issuer="https://new.example.test",
        )

    async def tokens(**kwargs: object) -> OAuthTokenResponse:
        assert kwargs["redirect_uri"] == "https://state.example.test/redirect"
        assert kwargs["code_verifier"] == "synthetic-verifier"
        await gap()
        return OAuthTokenResponse(
            access_token="synthetic-exchanged", refresh_token=None, expires_at=None
        )

    async def github_token(*args: object) -> str:
        del args
        fixture.scope.assert_closed()
        calls.append("github_exchange")
        return "synthetic-temporary-github-token"

    async def github_list(*args: object) -> list[dict[str, object]]:
        del args
        await gap()
        return [
            {
                "id": 2,
                "account": {"login": "stored-default-avatar", "type": "Organization"},
            },
            {
                "id": 3,
                "account": {"login": "projected", "type": "User", "avatar_url": ""},
            },
            {"id": "invalid", "account": None},
        ]

    async def revoke(*args: object) -> None:
        del args
        fixture.scope.assert_closed()
        calls.append("revoke_after_completed_sync")

    if flow == "connect":
        monkeypatch.setattr(oauth_helpers, "discover_required_metadata", metadata)
    elif flow == "exchange":
        monkeypatch.setattr(oauth_helpers, "exchange_and_handle_errors", tokens)
    else:
        assert flow == "sync"
        monkeypatch.setattr(oauth_service_module, "exchange_oauth_code", github_token)
        monkeypatch.setattr(
            oauth_service_module, "list_user_installations", github_list
        )
        monkeypatch.setattr(oauth_service_module, "revoke_oauth_token", revoke)


async def run_actual_service(fixture: OAuthFixture, *, flow: str) -> object:
    config = synthetic_config()
    service = ToolkitOAuthService(
        repository=fixture.repository,
        config=config,
        registry={},
        platform_runtime=SyntheticPlatformRuntime(),
    )
    requester = fixture.subject.requester
    if flow == "connect":
        return await service.connect(
            user_id=requester.user_id,
            session_id=requester.session_id,
            workspace_id=requester.workspace_id,
            handle=fixture.subject.handle,
            toolkit_id=fixture.subject.toolkit_id,
        )
    if flow == "exchange":
        # Shared state intentionally keeps its existing initiating-User/redirect policy.
        state = create_toolkit_oauth_state(
            toolkit_id=fixture.subject.toolkit_id,
            workspace_id=requester.workspace_id,
            user_id=fixture.subject.other_user_id,
            redirect_uri="https://state.example.test/redirect",
            code_verifier="synthetic-verifier",
            secret_key=config.credential_encryption.key,
        )
        return await service.exchange(
            user_id=requester.user_id,
            session_id=requester.session_id,
            workspace_id=requester.workspace_id,
            toolkit_id=fixture.subject.toolkit_id,
            code="synthetic-code",
            state=state,
        )
    assert flow == "sync"
    state = create_platform_oauth_state(
        config.credential_encryption.key, effective_generation="synthetic-generation"
    )
    return await service.platform_installations(
        user_id=requester.user_id,
        session_id=requester.session_id,
        workspace_id=requester.workspace_id,
        code="synthetic-code",
        state=state,
    )


async def direct_finalize(
    fixture: OAuthFixture, *, flow: str
) -> Result[None, ToolkitOAuthDenied]:
    if flow == "sync":
        return await fixture.repository.sync_installations(
            requester=fixture.subject.requester,
            platform_app_id="app-main",
            installations=(installation(9, login="must-not-store", avatar=""),),
        )
    return await store(fixture, connection_write(tokens=True, label="must-not-store"))


@pytest.mark.parametrize("flow", ["connect", "exchange", "sync"])
@pytest.mark.parametrize("mutation", list(Invalidation))
async def test_paused_service_final_write_rechecks_independent_committed_authority(
    rdb_engine: AsyncEngine,
    latest_db_schema: None,
    monkeypatch: pytest.MonkeyPatch,
    flow: str,
    mutation: Invalidation,
    record_property: Callable[[str, object], None],
) -> None:
    """Fresh committed reread evidence, explicitly not serialized-through-commit."""
    del latest_db_schema
    reached, release = asyncio.Event(), asyncio.Event()
    calls: list[str] = []
    task: asyncio.Task[object] | None = None
    async with rdb_engine.connect() as primary_connection:
        primary = IndependentOAuthManager(primary_connection, None)
        fixture = await oauth_fixture(primary)
        async with rdb_engine.connect() as mutator_connection:
            mutator = IndependentOAuthManager(mutator_connection, None)
            try:
                if mutation is Invalidation.OWNER_TRANSFER:
                    async with primary() as session:
                        await session.execute(
                            sa.update(RDBWorkspaceUser)
                            .where(RDBWorkspaceUser.id == fixture.subject.member_id)
                            .values(role=WorkspaceUserRole.OWNER)
                        )
                original = connection_write(tokens=True, label="preflight")
                assert await store(fixture, original) == Success(None)
                assert await fixture.repository.sync_installations(
                    requester=fixture.subject.requester,
                    platform_app_id="app-main",
                    installations=(installation(1, login="preflight", avatar=""),),
                ) == Success(None)
                await admit_before_http(fixture)
                fixture.fault.trace.clear()
                fixture.fault.sql_trace.clear()
                install_service_external_gap(
                    monkeypatch,
                    fixture,
                    flow=flow,
                    reached=reached,
                    release=release,
                    calls=calls,
                )
                task = asyncio.create_task(run_actual_service(fixture, flow=flow))
                await asyncio.wait_for(reached.wait(), timeout=10)
                fixture.scope.assert_closed()
                primary_pid = primary.pids[-1]
                async with mutator() as session:
                    mutation_pid = mutator.pids[-1]
                    assert primary_pid != mutation_pid
                    if mutation is not Invalidation.OWNER_TRANSFER:
                        await invalidate(fixture, session, mutation)
                if mutation is Invalidation.OWNER_TRANSFER:
                    transfer = WorkspaceUserOperationRepository(
                        user_repository=WorkspaceUserRepository(),
                        workspace_repository=WorkspaceRepository(),
                        owner_lifecycle_repository=OwnerLifecycleRepository(),
                        session_manager=mutator,
                    )
                    result = await transfer.transfer_ownership(
                        workspace_id=fixture.subject.requester.workspace_id,
                        new_owner_workspace_user_id=fixture.subject.other_member_id,
                    )
                    assert isinstance(result, Success)
                # These completed independent reads observe the committed invalidation.
                baseline_connection = await connection_row(fixture)
                baseline_installations = await installation_rows(fixture)
                async with primary() as session:
                    if mutation is Invalidation.OWNER_TRANSFER:
                        current = await session.get(
                            RDBWorkspaceUser, fixture.subject.member_id
                        )
                        assert (
                            current is not None
                            and current.role is WorkspaceUserRole.MANAGER
                        )
                    elif mutation is Invalidation.USER_DISABLE:
                        assert (
                            await session.get(
                                RDBWorkspaceUser, fixture.subject.member_id
                            )
                            is not None
                        )
                    elif mutation is Invalidation.HANDLE_RENAME:
                        rebound = await WorkspaceRepository().resolve_id(
                            session, fixture.subject.handle
                        )
                        assert rebound == fixture.subject.foreign_workspace_id
                record_property("preflight_backend_pid", primary_pid)
                record_property("invalidation_backend_pid", mutation_pid)
                record_property(
                    "authority_witness", "independent_commit_before_external_release"
                )
                record_property("flow", flow)
                record_property("mutation", mutation.value)
                fixture.fault.trace.clear()
                fixture.fault.sql_trace.clear()
                release.set()
                denial = expected_denial(mutation, flow=flow)
                if denial is not None:
                    with pytest.raises(ToolkitOAuthError) as error:
                        await asyncio.wait_for(task, timeout=10)
                    assert error.value.reason.value == denial.reason.value
                    details = {
                        ToolkitOAuthDenialReason.INACTIVE_SUBJECT: "Not authenticated",
                        ToolkitOAuthDenialReason.WORKSPACE_NOT_FOUND: (
                            "Workspace not found."
                        ),
                        ToolkitOAuthDenialReason.MEMBERSHIP_REQUIRED: (
                            "Not a member of this workspace."
                        ),
                        ToolkitOAuthDenialReason.WRITE_PERMISSION_REQUIRED: (
                            "Toolkit write permission required."
                        ),
                        ToolkitOAuthDenialReason.TOOLKIT_NOT_FOUND: (
                            "Toolkit config not found."
                        ),
                    }
                    assert error.value.detail == details[denial.reason]
                    record_property("denial_reason", denial.reason.value)
                    record_property(
                        "subject_status",
                        denial.subject_status.value if denial.subject_status else "",
                    )
                    assert (
                        "upsert" not in fixture.fault.stages()
                        and "sync" not in fixture.fault.stages()
                    )
                    assert fixture.fault.sql_trace == []
                    assert await connection_row(fixture) == baseline_connection
                    assert await installation_rows(fixture) == baseline_installations
                    assert await direct_finalize(fixture, flow=flow) == Failure(denial)
                    assert "revoke_after_completed_sync" not in calls
                else:
                    output = await asyncio.wait_for(task, timeout=10)
                    record_property("denial_reason", "allowed")
                    if flow == "sync":
                        assert isinstance(output, tuple) and len(output) == 1
                        assert calls[-1] == "revoke_after_completed_sync"
                        rows = await installation_rows(fixture)
                        assert [row["installation_id"] for row in rows] == [2, 3]
                        assert await connection_row(fixture) == baseline_connection
                    else:
                        final = await fixture.repository.read_shared_context(
                            toolkit_id=fixture.subject.toolkit_id
                        )
                        assert final.connection is not None
                        assert (
                            final.connection.status
                            is MCPOAuthConnectionStatus.CONNECTED
                        )
                        assert final.connection.client_id == original.client_id
                        if flow == "connect":
                            assert isinstance(output, str) and output.startswith(
                                "https://new.example.test/authorize?"
                            )
                            assert (
                                final.connection.access_token == original.access_token
                            )
                            assert (
                                final.connection.refresh_token == original.refresh_token
                            )
                        else:
                            assert output is None
                            assert (
                                final.connection.access_token == "synthetic-exchanged"
                            )
                            assert final.connection.refresh_token is None
                fixture.scope.assert_closed()
            finally:
                release.set()
                if task is not None:
                    if not task.done():
                        task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
                await cleanup_independent(fixture)


@pytest.mark.parametrize("kind", ["missing", "owned", "foreign"])
async def test_final_shared_write_rejects_exact_toolkit_eligibility_without_upsert(
    rdb_session_manager: SessionManager[AsyncSession],
    kind: str,
) -> None:
    fixture = await oauth_fixture(rdb_session_manager)
    key = await corrupt_identity(fixture, kind)
    fixture.fault.trace.clear()
    result = await fixture.repository.store_shared_connection(
        requester=fixture.subject.requester,
        toolkit_id=key,
        connection=connection_write(tokens=True, label="must-not-store"),
    )
    assert result == Failure(
        ToolkitOAuthDenied(ToolkitOAuthDenialReason.TOOLKIT_NOT_FOUND, None)
    )
    assert fixture.fault.stages() == [
        "user",
        "session",
        "workspace",
        "membership",
        "toolkit",
    ]
    assert "upsert" not in fixture.fault.stages()
    assert await connection_row(fixture) is None
    fixture.scope.assert_closed()


@pytest.mark.parametrize("flow", ["connect", "exchange", "sync"])
@pytest.mark.parametrize(
    "first_invalid", ["user", "session", "workspace", "membership", "permission"]
)
async def test_invalid_facts_keep_auth_workspace_member_permission_toolkit_order(
    rdb_session_manager: SessionManager[AsyncSession],
    flow: str,
    first_invalid: str,
) -> None:
    fixture = await oauth_fixture(rdb_session_manager)
    mutations = {
        "user": Invalidation.USER_DISABLE,
        "session": Invalidation.SESSION_FOREIGN,
        "workspace": Invalidation.WORKSPACE_DELETE,
        "membership": Invalidation.MEMBERSHIP_REMOVE,
        "permission": Invalidation.MEMBER_DEMOTION,
    }
    async with fixture.manager() as session:
        await invalidate(fixture, session, mutations[first_invalid])
        if first_invalid in {"user", "session"}:
            await session.execute(
                sa.delete(RDBWorkspace).where(
                    RDBWorkspace.id == fixture.subject.requester.workspace_id
                )
            )
        else:
            await session.execute(
                sa.delete(RDBToolkitConfig).where(
                    RDBToolkitConfig.id == fixture.subject.toolkit_id
                )
            )
    fixture.fault.trace.clear()
    expected = expected_denial(mutations[first_invalid], flow=flow)
    assert expected is not None
    assert await direct_finalize(fixture, flow=flow) == Failure(expected)
    prefixes = {
        "user": ["user"],
        "session": ["user", "session"],
        "workspace": ["user", "session", "workspace"],
        "membership": ["user", "session", "workspace", "membership"],
        "permission": ["user", "session", "workspace", "membership"],
    }
    assert fixture.fault.stages() == prefixes[first_invalid]
    assert len({id(session) for _, session in fixture.fault.trace}) == 1
    assert await connection_row(fixture) is None
    assert await installation_rows(fixture) == []
    fixture.scope.assert_closed()
