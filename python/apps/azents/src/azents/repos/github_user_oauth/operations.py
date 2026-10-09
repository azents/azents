"""Completed database-only GitHub user setup and transient token capture."""

import datetime
import secrets
from dataclasses import dataclass
from typing import Annotated

import sqlalchemy as sa
from fastapi import Depends

from azents.core.account_access import ActiveAccountSubjectStatus
from azents.core.auth.permissions import Permissions, has_permission
from azents.core.auth.roles import get_permissions_for_role
from azents.core.crypto import CredentialCipher
from azents.core.deps import get_credential_cipher
from azents.core.enums import AgentLifecycleStatus, WorkspaceUserRole
from azents.core.github_user_oauth import (
    GitHubUserAttempt,
    GitHubUserAttemptStatus,
    GitHubUserCandidate,
    GitHubUserConfirmResult,
    GitHubUserConnectionStatus,
    GitHubUserContext,
    GitHubUserErrorCode,
    GitHubUserOAuthError,
    GitHubUserRegistration,
    GitHubUserRequester,
    GitHubUserRevocation,
    GitHubUserStartResult,
)
from azents.core.system_setting import SystemSettingSection
from azents.core.system_setting_payload import SystemSettingPayloadResolver
from azents.rdb.deps import get_session_manager
from azents.rdb.models.github_user_oauth import (
    RDBGitHubUserAttempt,
    RDBGitHubUserConnection,
)
from azents.rdb.models.toolkit import RDBToolkitConfig
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import ReadSession, WriteSession
from azents.repos.account_access import evaluate_active_subject
from azents.repos.agent import AgentRepository
from azents.repos.agent_admin import AgentAdminRepository
from azents.repos.github_user_oauth.guards import (
    capture_and_clear_user_tokens,
    capture_registration,
    distinct_revocations,
    same_app,
)
from azents.repos.github_user_oauth.payloads import (
    CandidatePayload,
    SetupPayload,
    attempt_from,
    connection_from,
    encode_registration,
)
from azents.repos.session import SessionRepository
from azents.repos.system_setting.repository import SystemSettingRepository
from azents.repos.toolkit import ToolkitRepository
from azents.repos.toolkit.data import ToolkitConfig
from azents.repos.toolkit_operations import get_encrypted_toolkit_repository
from azents.repos.user import UserRepository
from azents.repos.workspace import WorkspaceRepository
from azents.repos.workspace_user import WorkspaceUserRepository


@dataclass(frozen=True)
class GitHubUserOAuthOperationRepository:
    """Complete local writes before service-owned bounded provider effects."""

    session_manager: Annotated[
        SessionManager[WriteSession], Depends(get_session_manager)
    ]
    toolkit_repository: Annotated[
        ToolkitRepository, Depends(get_encrypted_toolkit_repository)
    ]
    cipher: Annotated[CredentialCipher, Depends(get_credential_cipher)]
    user_repository: Annotated[UserRepository, Depends(UserRepository)]
    session_repository: Annotated[SessionRepository, Depends(SessionRepository)]
    workspace_repository: Annotated[WorkspaceRepository, Depends(WorkspaceRepository)]
    workspace_user_repository: Annotated[
        WorkspaceUserRepository, Depends(WorkspaceUserRepository)
    ]
    agent_repository: Annotated[AgentRepository, Depends(AgentRepository)]
    agent_admin_repository: Annotated[
        AgentAdminRepository, Depends(AgentAdminRepository)
    ]
    system_setting_repository: Annotated[
        SystemSettingRepository, Depends(SystemSettingRepository)
    ]
    setting_payloads: Annotated[
        SystemSettingPayloadResolver, Depends(SystemSettingPayloadResolver)
    ]

    async def authorize_scope_in_session(
        self,
        session: ReadSession,
        *,
        user_id: str,
        session_id: str,
        workspace_id: str,
        agent_id: str | None,
    ) -> None:
        subject = await evaluate_active_subject(
            session,
            user_id=user_id,
            session_id=session_id,
            user_repository=self.user_repository,
            session_repository=self.session_repository,
        )
        if subject is not ActiveAccountSubjectStatus.ACTIVE:
            raise GitHubUserOAuthError(
                GitHubUserErrorCode.AUTHORITY, "Not authenticated."
            )
        workspace = await self.workspace_repository.get_by_id(session, workspace_id)
        member = await self.workspace_user_repository.get_by_workspace_and_user(
            session, workspace_id, user_id
        )
        if workspace is None or member is None:
            raise GitHubUserOAuthError(
                GitHubUserErrorCode.AUTHORITY, "Workspace membership required."
            )
        if agent_id is None:
            if not has_permission(
                get_permissions_for_role(member.role), Permissions.TOOLKITS_WRITE
            ):
                raise GitHubUserOAuthError(
                    GitHubUserErrorCode.AUTHORITY, "Toolkit write permission required."
                )
        else:
            agent = await self.agent_repository.get_by_id(session, agent_id)
            if (
                agent is None
                or agent.workspace_id != workspace_id
                or agent.lifecycle_status is not AgentLifecycleStatus.ACTIVE
            ):
                raise GitHubUserOAuthError(
                    GitHubUserErrorCode.NOT_FOUND, "Agent not found."
                )
            if (
                member.role is not WorkspaceUserRole.OWNER
                and not await self.agent_admin_repository.is_admin(
                    session, agent_id, member.id
                )
            ):
                raise GitHubUserOAuthError(
                    GitHubUserErrorCode.AUTHORITY,
                    "Agent management permission required.",
                )

    async def authorize_scope(
        self, *, user_id: str, session_id: str, workspace_id: str, agent_id: str | None
    ) -> None:
        """Authorize availability before a Toolkit has been saved."""
        async with self.session_manager() as session:
            await self.authorize_scope_in_session(
                session,
                user_id=user_id,
                session_id=session_id,
                workspace_id=workspace_id,
                agent_id=agent_id,
            )

    async def _authorize(
        self, session: WriteSession, requester: GitHubUserRequester, *, lock: bool
    ) -> ToolkitConfig:
        if lock:
            # Refresh a previously loaded ORM identity under this narrow write lock.
            await session.write_session.scalar(
                sa.select(RDBToolkitConfig)
                .where(RDBToolkitConfig.id == requester.toolkit_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        await self.authorize_scope_in_session(
            session,
            user_id=requester.user_id,
            session_id=requester.session_id,
            workspace_id=requester.workspace_id,
            agent_id=requester.agent_id,
        )
        toolkit = await self.toolkit_repository.get_by_id(session, requester.toolkit_id)
        if (
            toolkit is None
            or toolkit.workspace_id != requester.workspace_id
            or toolkit.owner_agent_id != requester.agent_id
            or toolkit.toolkit_type != "github"
        ):
            raise GitHubUserOAuthError(
                GitHubUserErrorCode.NOT_FOUND,
                "GitHub Toolkit not found in this ownership context.",
            )
        return toolkit

    async def _registration(
        self,
        session: ReadSession,
        toolkit: ToolkitConfig,
        registration: GitHubUserRegistration,
    ) -> None:
        auth_type = (
            "github_app_platform_user"
            if registration.source == "platform_user"
            else "github_app_user"
        )
        if (
            toolkit.revision != registration.toolkit_revision
            or toolkit.config.get("github_auth_type") != auth_type
        ):
            raise GitHubUserOAuthError(
                GitHubUserErrorCode.STALE,
                "Toolkit registration changed. Restart authorization.",
            )
        await self.validate_platform_registration(session, registration)

    async def validate_platform_registration(
        self, session: ReadSession, registration: GitHubUserRegistration
    ) -> None:
        """Revalidate the captured current Platform generation without I/O."""
        if registration.source == "platform_user":
            current = await self.system_setting_repository.get_current(
                session, section=SystemSettingSection.PLATFORM_GITHUB_APP
            )
            resolved = self.setting_payloads.resolve_current(
                definition=self.setting_payloads.registry.get(
                    SystemSettingSection.PLATFORM_GITHUB_APP
                ),
                current=current,
            )
            if resolved.effective_generation != registration.platform_generation:
                raise GitHubUserOAuthError(
                    GitHubUserErrorCode.STALE,
                    "Platform App settings changed. Restart authorization.",
                )

    async def _connection(
        self, session: ReadSession, toolkit_id: str
    ) -> RDBGitHubUserConnection | None:
        return await session.read_session.scalar(
            sa.select(RDBGitHubUserConnection)
            .where(RDBGitHubUserConnection.toolkit_id == toolkit_id)
            .execution_options(populate_existing=True)
        )

    async def read_context(
        self, *, requester: GitHubUserRequester
    ) -> GitHubUserContext:
        """Finish current authorized preparation without database handles."""
        async with self.session_manager() as session:
            toolkit = await self._authorize(session, requester, lock=False)
            row = await self._connection(session, toolkit.id)
            return GitHubUserContext(
                toolkit=toolkit,
                connection=None if row is None else connection_from(row, self.cipher),
            )

    async def _attempt(
        self, session: ReadSession, attempt_id: str
    ) -> RDBGitHubUserAttempt:
        row = await session.read_session.scalar(
            sa.select(RDBGitHubUserAttempt)
            .where(RDBGitHubUserAttempt.id == attempt_id)
            .execution_options(populate_existing=True)
        )
        if row is None:
            raise GitHubUserOAuthError(
                GitHubUserErrorCode.NOT_FOUND, "Authorization attempt not found."
            )
        return row

    def _bound(
        self, row: RDBGitHubUserAttempt, requester: GitHubUserRequester
    ) -> GitHubUserAttempt:
        attempt = attempt_from(row, self.cipher)
        if attempt.requester != requester:
            raise GitHubUserOAuthError(
                GitHubUserErrorCode.STALE,
                "Authorization attempt does not match this authenticated context.",
            )
        return attempt

    async def _candidate_revocation(
        self, session: ReadSession, attempt: GitHubUserAttempt
    ) -> GitHubUserRevocation | None:
        if attempt.candidate is None:
            return None
        current = await self._connection(session, attempt.requester.toolkit_id)
        if current is not None:
            active = connection_from(current, self.cipher)
            if (
                same_app(active.registration, attempt.registration)
                and active.access_token == attempt.candidate.access_token
            ):
                return None
        return GitHubUserRevocation(
            registration=attempt.registration,
            access_token=attempt.candidate.access_token,
        )

    async def start(
        self,
        *,
        requester: GitHubUserRequester,
        registration: GitHubUserRegistration,
        redirect_uri: str,
        nonce: str,
        code_verifier: str,
        expires_at: datetime.datetime,
    ) -> GitHubUserStartResult:
        """Replace stale setup locally without replacing the working connection."""
        if (
            expires_at <= datetime.datetime.now(datetime.UTC)
            or not nonce
            or not code_verifier
        ):
            raise GitHubUserOAuthError(
                GitHubUserErrorCode.INVALID, "Invalid authorization attempt lifetime."
            )
        async with self.session_manager() as session:
            toolkit = await self._authorize(session, requester, lock=True)
            await self._registration(session, toolkit, registration)
            old_rows = (
                await session.read_session.scalars(
                    sa.select(RDBGitHubUserAttempt).where(
                        RDBGitHubUserAttempt.toolkit_id == toolkit.id
                    )
                )
            ).all()
            revocations: list[GitHubUserRevocation] = []
            for old in old_rows:
                target = await self._candidate_revocation(
                    session, attempt_from(old, self.cipher)
                )
                if target is not None:
                    revocations.append(target)
                await session.write_session.delete(old)
            await session.write_session.flush()
            current = await self._connection(session, toolkit.id)
            row = RDBGitHubUserAttempt(
                toolkit_id=toolkit.id,
                user_id=requester.user_id,
                session_id=requester.session_id,
                workspace_id=requester.workspace_id,
                agent_id=requester.agent_id,
                encrypted_setup=self.cipher.encrypt(
                    SetupPayload(
                        registration=registration,
                        redirect_uri=redirect_uri,
                        nonce=nonce,
                        code_verifier=code_verifier,
                    ).model_dump_json()
                ),
                encrypted_candidate=None,
                captured_connection_id=None if current is None else current.id,
                status=GitHubUserAttemptStatus.PENDING,
                expires_at=expires_at,
            )
            session.write_session.add(row)
            await session.write_session.flush()
            return GitHubUserStartResult(
                attempt=attempt_from(row, self.cipher),
                revocations=distinct_revocations(revocations),
            )

    async def claim_exchange(
        self,
        *,
        requester: GitHubUserRequester,
        attempt_id: str,
        nonce: str,
        redirect_uri: str,
    ) -> GitHubUserAttempt:
        """Consume one setup completion under current authority before provider I/O."""
        async with self.session_manager() as session:
            toolkit = await self._authorize(session, requester, lock=True)
            row = await self._attempt(session, attempt_id)
            attempt = self._bound(row, requester)
            await self._registration(session, toolkit, attempt.registration)
            if (
                row.status is not GitHubUserAttemptStatus.PENDING
                or row.expires_at <= datetime.datetime.now(datetime.UTC)
                or not secrets.compare_digest(attempt.nonce, nonce)
                or attempt.redirect_uri != redirect_uri
            ):
                raise GitHubUserOAuthError(
                    GitHubUserErrorCode.STALE,
                    "Authorization attempt is expired, consumed or mismatched.",
                )
            row.status = GitHubUserAttemptStatus.EXCHANGING
            await session.write_session.flush()
            return attempt_from(row, self.cipher)

    async def complete_failed_exchange(self, *, attempt_id: str) -> None:
        """Clear captured failed setup locally; a late result cannot publish it."""
        async with self.session_manager() as session:
            before = await session.read_session.scalar(
                sa.select(RDBGitHubUserAttempt).where(
                    RDBGitHubUserAttempt.id == attempt_id
                )
            )
            if before is None:
                return
            await session.write_session.scalar(
                sa.select(RDBToolkitConfig)
                .where(RDBToolkitConfig.id == before.toolkit_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            await session.write_session.execute(
                sa.delete(RDBGitHubUserAttempt).where(
                    RDBGitHubUserAttempt.id == attempt_id,
                    RDBGitHubUserAttempt.status == GitHubUserAttemptStatus.EXCHANGING,
                )
            )

    async def read_review(
        self, *, requester: GitHubUserRequester, attempt_id: str
    ) -> GitHubUserAttempt:
        """Read a current verified candidate only in its originating context."""
        async with self.session_manager() as session:
            toolkit = await self._authorize(session, requester, lock=False)
            row = await self._attempt(session, attempt_id)
            attempt = self._bound(row, requester)
            await self._registration(session, toolkit, attempt.registration)
            current = await self._connection(session, toolkit.id)
            if (
                row.status is not GitHubUserAttemptStatus.REVIEW
                or row.expires_at <= datetime.datetime.now(datetime.UTC)
                or row.captured_connection_id
                != (None if current is None else current.id)
                or attempt.candidate is None
            ):
                raise GitHubUserOAuthError(
                    GitHubUserErrorCode.STALE,
                    "Authorization review is stale. Start a new attempt.",
                )
            return attempt

    async def store_review(
        self,
        *,
        requester: GitHubUserRequester,
        attempt_id: str,
        candidate: GitHubUserCandidate,
        registration: GitHubUserRegistration,
    ) -> GitHubUserAttempt:
        """Stage verified account only while all captured setup facts remain valid."""
        async with self.session_manager() as session:
            toolkit = await self._authorize(session, requester, lock=True)
            row = await self._attempt(session, attempt_id)
            attempt = self._bound(row, requester)
            await self._registration(session, toolkit, registration)
            current = await self._connection(session, toolkit.id)
            if (
                row.status is not GitHubUserAttemptStatus.EXCHANGING
                or row.expires_at <= datetime.datetime.now(datetime.UTC)
                or row.captured_connection_id
                != (None if current is None else current.id)
                or attempt.registration != registration
            ):
                raise GitHubUserOAuthError(
                    GitHubUserErrorCode.STALE,
                    "Authorization setup changed. Start a new attempt.",
                )
            row.encrypted_candidate = self.cipher.encrypt(
                CandidatePayload(candidate=candidate).model_dump_json()
            )
            row.status = GitHubUserAttemptStatus.REVIEW
            await session.write_session.flush()
            return attempt_from(row, self.cipher)

    async def confirm(
        self,
        *,
        requester: GitHubUserRequester,
        attempt_id: str,
        registration: GitHubUserRegistration,
    ) -> GitHubUserConfirmResult:
        """Transfer the reviewed token and return only its superseded predecessor."""
        async with self.session_manager() as session:
            toolkit = await self._authorize(session, requester, lock=True)
            row = await self._attempt(session, attempt_id)
            attempt = self._bound(row, requester)
            await self._registration(session, toolkit, registration)
            current = await self._connection(session, toolkit.id)
            if (
                row.status is not GitHubUserAttemptStatus.REVIEW
                or row.expires_at <= datetime.datetime.now(datetime.UTC)
                or row.captured_connection_id
                != (None if current is None else current.id)
                or attempt.registration != registration
                or attempt.candidate is None
            ):
                raise GitHubUserOAuthError(
                    GitHubUserErrorCode.STALE,
                    "Authorization confirmation is stale. Start a new attempt.",
                )
            candidate = attempt.candidate
            revocations: list[GitHubUserRevocation] = []
            if current is not None:
                previous = connection_from(current, self.cipher)
                if not same_app(previous.registration, registration):
                    raise GitHubUserOAuthError(
                        GitHubUserErrorCode.STALE,
                        "Disconnect the original connection before changing "
                        "App identity.",
                    )
                if previous.access_token != candidate.access_token:
                    toolkit_row = await session.read_session.scalar(
                        sa.select(RDBToolkitConfig).where(
                            RDBToolkitConfig.id == toolkit.id
                        )
                    )
                    revocations.append(
                        GitHubUserRevocation(
                            registration=capture_registration(
                                toolkit_row,
                                previous.registration,
                                registration,
                                self.cipher,
                            ),
                            access_token=previous.access_token,
                        )
                    )
                await session.write_session.delete(current)
                await session.write_session.flush()
            saved = RDBGitHubUserConnection(
                toolkit_id=toolkit.id,
                app_id=registration.app_id,
                account_id=candidate.account_id,
                account_login=candidate.account_login,
                account_avatar_url=candidate.account_avatar_url,
                encrypted_access_token=self.cipher.encrypt(candidate.access_token),
                encrypted_registration=encode_registration(registration, self.cipher),
                status=GitHubUserConnectionStatus.CONNECTED,
                failure_reason=None,
            )
            session.write_session.add(saved)
            await session.write_session.delete(row)
            await session.write_session.flush()
            return GitHubUserConfirmResult(
                connection=connection_from(saved, self.cipher),
                revocations=tuple(revocations),
            )

    async def cancel(
        self, *, requester: GitHubUserRequester, attempt_id: str
    ) -> tuple[GitHubUserRevocation, ...]:
        """Remove the initiating setup without modifying a saved connection."""
        async with self.session_manager() as session:
            await self._authorize(session, requester, lock=True)
            row = await session.read_session.scalar(
                sa.select(RDBGitHubUserAttempt).where(
                    RDBGitHubUserAttempt.id == attempt_id
                )
            )
            if row is None:
                return ()
            attempt = self._bound(row, requester)
            target = await self._candidate_revocation(session, attempt)
            await session.write_session.delete(row)
            return () if target is None else (target,)

    async def disconnect(
        self,
        *,
        requester: GitHubUserRequester,
        registration: GitHubUserRegistration | None,
    ) -> tuple[GitHubUserRevocation, ...]:
        """Remove execution/setup state irrespective of provider cleanup outcome."""
        async with self.session_manager() as session:
            await self._authorize(session, requester, lock=True)
            return await capture_and_clear_user_tokens(
                session, requester.toolkit_id, registration, cipher=self.cipher
            )

    async def received_revocation(
        self,
        *,
        toolkit_id: str,
        registration: GitHubUserRegistration,
        access_token: str,
    ) -> GitHubUserRevocation | None:
        """Capture late-result cleanup facts without requiring its parent to survive."""
        async with self.session_manager() as session:
            current = await self._connection(session, toolkit_id)
            if current is not None:
                saved = connection_from(current, self.cipher)
                if (
                    same_app(saved.registration, registration)
                    and saved.access_token == access_token
                ):
                    return None
        return GitHubUserRevocation(
            registration=registration, access_token=access_token
        )

    async def mark_reconnect_required(
        self, *, requester: GitHubUserRequester, connection_id: str, reason: str
    ) -> None:
        """Late account failure can affect only the exact still-current connection."""
        async with self.session_manager() as session:
            await self._authorize(session, requester, lock=True)
            await session.write_session.execute(
                sa.update(RDBGitHubUserConnection)
                .where(
                    RDBGitHubUserConnection.id == connection_id,
                    RDBGitHubUserConnection.toolkit_id == requester.toolkit_id,
                )
                .values(
                    status=GitHubUserConnectionStatus.RECONNECT_REQUIRED,
                    failure_reason=reason,
                )
            )
