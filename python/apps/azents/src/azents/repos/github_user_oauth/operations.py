"""Completed database-only GitHub user setup, activation and token retirement."""

import dataclasses
import datetime
import secrets
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
    GitHubUserCleanup,
    GitHubUserCleanupStatus,
    GitHubUserConnection,
    GitHubUserConnectionStatus,
    GitHubUserContext,
    GitHubUserErrorCode,
    GitHubUserOAuthError,
    GitHubUserRegistration,
    GitHubUserRequester,
)
from azents.core.system_setting import SystemSettingSection
from azents.core.system_setting_payload import SystemSettingPayloadResolver
from azents.rdb.deps import get_session_manager
from azents.rdb.models.github_user_oauth import (
    RDBGitHubUserAttempt,
    RDBGitHubUserCleanup,
    RDBGitHubUserConnection,
)
from azents.rdb.models.toolkit import RDBToolkitConfig
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import ReadSession, WriteSession
from azents.repos.account_access import evaluate_active_subject
from azents.repos.agent import AgentRepository
from azents.repos.agent_admin import AgentAdminRepository
from azents.repos.github_user_oauth.guards import cleanup_pending
from azents.repos.github_user_oauth.payloads import (
    CandidatePayload,
    CleanupPayload,
    SetupPayload,
    attempt_from,
    cleanup_from,
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

_CURRENT = (
    GitHubUserAttemptStatus.PENDING,
    GitHubUserAttemptStatus.EXCHANGING,
    GitHubUserAttemptStatus.REVIEW,
)


def _error(code: GitHubUserErrorCode, message: str) -> GitHubUserOAuthError:
    return GitHubUserOAuthError(code, message)


def _same_registration(
    left: GitHubUserRegistration, right: GitHubUserRegistration
) -> bool:
    """Compare exact setup facts without placing them in diagnostics."""
    return left == right


@dataclasses.dataclass(frozen=True)
class GitHubUserOAuthOperationRepository:
    """Complete narrowly locked local lifecycle writes before provider effects."""

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

    async def _scope(
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
            raise _error(GitHubUserErrorCode.AUTHORITY, "Not authenticated.")
        workspace = await self.workspace_repository.get_by_id(session, workspace_id)
        member = await self.workspace_user_repository.get_by_workspace_and_user(
            session, workspace_id, user_id
        )
        if workspace is None or member is None:
            raise _error(
                GitHubUserErrorCode.AUTHORITY, "Workspace membership required."
            )
        if agent_id is None:
            if not has_permission(
                get_permissions_for_role(member.role), Permissions.TOOLKITS_WRITE
            ):
                raise _error(
                    GitHubUserErrorCode.AUTHORITY, "Toolkit write permission required."
                )
        else:
            agent = await self.agent_repository.get_by_id(session, agent_id)
            if (
                agent is None
                or agent.workspace_id != workspace_id
                or agent.lifecycle_status is not AgentLifecycleStatus.ACTIVE
            ):
                raise _error(GitHubUserErrorCode.NOT_FOUND, "Agent not found.")
            if (
                member.role is not WorkspaceUserRole.OWNER
                and not await self.agent_admin_repository.is_admin(
                    session, agent_id, member.id
                )
            ):
                raise _error(
                    GitHubUserErrorCode.AUTHORITY,
                    "Agent management permission required.",
                )

    async def authorize_scope(
        self, *, user_id: str, session_id: str, workspace_id: str, agent_id: str | None
    ) -> None:
        """Authorize availability before a Toolkit has been saved."""
        async with self.session_manager() as session:
            await self._scope(
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
            # Serializes only this Toolkit's local setup/mutation, never external I/O.
            await session.write_session.scalar(
                sa.select(RDBToolkitConfig.id)
                .where(RDBToolkitConfig.id == requester.toolkit_id)
                .with_for_update()
            )
        await self._scope(
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
            raise _error(
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
            raise _error(
                GitHubUserErrorCode.STALE,
                "Toolkit registration changed. Restart authorization.",
            )
        if registration.source == "platform_user":
            current = await self.system_setting_repository.get_current(
                session, section=SystemSettingSection.PLATFORM_GITHUB_APP
            )
            definition = self.setting_payloads.registry.get(
                SystemSettingSection.PLATFORM_GITHUB_APP
            )
            resolved = self.setting_payloads.resolve_current(
                definition=definition, current=current
            )
            if resolved.effective_generation != registration.platform_generation:
                raise _error(
                    GitHubUserErrorCode.STALE,
                    "Platform App settings changed. Restart authorization.",
                )

    async def _connection(
        self, session: ReadSession, toolkit_id: str
    ) -> RDBGitHubUserConnection | None:
        return await session.read_session.scalar(
            sa.select(RDBGitHubUserConnection).where(
                RDBGitHubUserConnection.toolkit_id == toolkit_id
            )
        )

    async def read_context(
        self, *, requester: GitHubUserRequester
    ) -> GitHubUserContext:
        """Finish authorized preparation without holding transaction handles."""
        async with self.session_manager() as session:
            toolkit = await self._authorize(session, requester, lock=False)
            connection = await self._connection(session, toolkit.id)
            pending = await cleanup_pending(session, toolkit.id)
            return GitHubUserContext(
                toolkit=toolkit,
                connection=None
                if connection is None
                else connection_from(connection, self.cipher),
                cleanup_pending=pending,
            )

    async def _attempt(
        self, session: ReadSession, attempt_id: str
    ) -> RDBGitHubUserAttempt:
        attempt = await session.read_session.scalar(
            sa.select(RDBGitHubUserAttempt).where(RDBGitHubUserAttempt.id == attempt_id)
        )
        if attempt is None:
            raise _error(
                GitHubUserErrorCode.NOT_FOUND, "Authorization attempt not found."
            )
        return attempt

    def _bound(
        self, row: RDBGitHubUserAttempt, requester: GitHubUserRequester
    ) -> GitHubUserAttempt:
        attempt = attempt_from(row, self.cipher)
        if attempt.requester != requester:
            raise _error(
                GitHubUserErrorCode.STALE,
                "Authorization attempt does not match this authenticated context.",
            )
        return attempt

    async def _retire(
        self,
        session: WriteSession,
        *,
        toolkit_id: str,
        registration: GitHubUserRegistration,
        access_token: str,
        reason: str,
    ) -> GitHubUserCleanup:
        # Deduplication is local retry safety, not a provider-account aggregate.
        existing = (
            await session.read_session.scalars(
                sa.select(RDBGitHubUserCleanup).where(
                    RDBGitHubUserCleanup.toolkit_id == toolkit_id
                )
            )
        ).all()
        for row in existing:
            saved = cleanup_from(row, self.cipher)
            if (
                saved.access_token == access_token
                and saved.registration.app_id == registration.app_id
                and saved.registration.client_id == registration.client_id
            ):
                return saved
        row = RDBGitHubUserCleanup(
            toolkit_id=toolkit_id,
            encrypted_payload=self.cipher.encrypt(
                CleanupPayload(
                    registration=registration, access_token=access_token
                ).model_dump_json()
            ),
            reason=reason,
            status=GitHubUserCleanupStatus.PENDING,
            failure_reason=None,
        )
        session.write_session.add(row)
        await session.write_session.flush()
        return cleanup_from(row, self.cipher)

    async def _retire_candidate(
        self,
        session: WriteSession,
        *,
        toolkit_id: str,
        registration: GitHubUserRegistration,
        access_token: str,
        reason: str,
    ) -> GitHubUserCleanup | None:
        """Only retire material that is not the same Toolkit's active credential."""
        current = await self._connection(session, toolkit_id)
        if current is not None:
            saved = connection_from(current, self.cipher)
            if (
                saved.access_token == access_token
                and saved.registration.app_id == registration.app_id
                and saved.registration.client_id == registration.client_id
            ):
                return None
        return await self._retire(
            session,
            toolkit_id=toolkit_id,
            registration=registration,
            access_token=access_token,
            reason=reason,
        )

    async def _cancel(
        self, session: WriteSession, row: RDBGitHubUserAttempt, *, reason: str
    ) -> None:
        setup = attempt_from(row, self.cipher)
        if row.encrypted_issued_token is not None:
            await self._retire_candidate(
                session,
                toolkit_id=row.toolkit_id,
                registration=setup.registration,
                access_token=self.cipher.decrypt(row.encrypted_issued_token),
                reason=reason,
            )
        elif setup.candidate is not None:
            await self._retire_candidate(
                session,
                toolkit_id=row.toolkit_id,
                registration=setup.registration,
                access_token=setup.candidate.access_token,
                reason=reason,
            )
        row.encrypted_issued_token = None
        row.encrypted_candidate = None
        row.status = GitHubUserAttemptStatus.CANCELLED
        await self._prune_terminal(session, row)

    async def _prune_terminal(
        self, session: WriteSession, row: RDBGitHubUserAttempt
    ) -> None:
        """Erase setup secrets after token transfer or independent cleanup capture."""
        if (
            row.status
            in (
                GitHubUserAttemptStatus.COMPLETED,
                GitHubUserAttemptStatus.CANCELLED,
            )
            and not row.exchange_in_flight
            and row.encrypted_candidate is None
            and row.encrypted_issued_token is None
        ):
            await session.write_session.delete(row)

    async def start(
        self,
        *,
        requester: GitHubUserRequester,
        registration: GitHubUserRegistration,
        redirect_uri: str,
        nonce: str,
        code_verifier: str,
        expires_at: datetime.datetime,
    ) -> GitHubUserAttempt:
        """Reserve one current candidate while retaining the saved connection."""
        if (
            expires_at <= datetime.datetime.now(datetime.UTC)
            or not nonce
            or not code_verifier
        ):
            raise _error(
                GitHubUserErrorCode.INVALID, "Invalid authorization attempt lifetime."
            )
        async with self.session_manager() as session:
            toolkit = await self._authorize(session, requester, lock=True)
            await self._registration(session, toolkit, registration)
            current_attempts = (
                await session.read_session.scalars(
                    sa.select(RDBGitHubUserAttempt).where(
                        RDBGitHubUserAttempt.toolkit_id == toolkit.id,
                        RDBGitHubUserAttempt.status.in_(_CURRENT),
                    )
                )
            ).all()
            for old in current_attempts:
                await self._cancel(session, old, reason="superseded")
            await session.write_session.flush()
            connection = await self._connection(session, toolkit.id)
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
                encrypted_issued_token=None,
                exchange_in_flight=False,
                captured_connection_id=None if connection is None else connection.id,
                status=GitHubUserAttemptStatus.PENDING,
                expires_at=expires_at,
            )
            session.write_session.add(row)
            await session.write_session.flush()
            return attempt_from(row, self.cipher)

    async def claim_exchange(
        self,
        *,
        requester: GitHubUserRequester,
        attempt_id: str,
        nonce: str,
        redirect_uri: str,
    ) -> GitHubUserAttempt:
        """Consume setup completion exactly once before external code exchange."""
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
                raise _error(
                    GitHubUserErrorCode.STALE,
                    "Authorization attempt is expired, consumed or mismatched.",
                )
            row.status = GitHubUserAttemptStatus.EXCHANGING
            row.exchange_in_flight = True
            await session.write_session.flush()
            return attempt_from(row, self.cipher)

    async def record_exchange_token(
        self,
        *,
        attempt_id: str,
        registration: GitHubUserRegistration,
        access_token: str,
    ) -> GitHubUserCleanup | None:
        """Retain the received token before identity I/O despite cancellation."""
        async with self.session_manager() as session:
            row = await self._attempt(session, attempt_id)
            await session.write_session.scalar(
                sa.select(RDBToolkitConfig.id)
                .where(RDBToolkitConfig.id == row.toolkit_id)
                .with_for_update()
            )
            # Refresh after the Toolkit lock so cancellation's committed state wins.
            await session.write_session.refresh(row)
            attempt = attempt_from(row, self.cipher)
            if not _same_registration(attempt.registration, registration):
                raise _error(
                    GitHubUserErrorCode.STALE,
                    "Exchange registration does not match the reserved attempt.",
                )
            row.exchange_in_flight = False
            discarded = (
                row.status is not GitHubUserAttemptStatus.EXCHANGING
                or row.expires_at <= datetime.datetime.now(datetime.UTC)
            )
            if discarded:
                row.exchange_in_flight = False
                row.status = GitHubUserAttemptStatus.CANCELLED
                cleanup = await self._retire_candidate(
                    session,
                    toolkit_id=row.toolkit_id,
                    registration=registration,
                    access_token=access_token,
                    reason="discarded_exchange",
                )
                await self._prune_terminal(session, row)
            else:
                row.encrypted_issued_token = self.cipher.encrypt(access_token)
                cleanup = None
        if discarded and cleanup is None:
            raise _error(
                GitHubUserErrorCode.STALE,
                "Authorization setup is no longer current.",
            )
        return cleanup

    async def complete_failed_exchange(self, *, attempt_id: str) -> None:
        """Release a failed one-use exchange without discarding received credentials."""
        async with self.session_manager() as session:
            row = await self._attempt(session, attempt_id)
            await session.write_session.scalar(
                sa.select(RDBToolkitConfig.id)
                .where(RDBToolkitConfig.id == row.toolkit_id)
                .with_for_update()
            )
            await session.write_session.refresh(row)
            row.exchange_in_flight = False
            await self._cancel(session, row, reason="exchange_failed")

    async def read_review(
        self, *, requester: GitHubUserRequester, attempt_id: str
    ) -> GitHubUserAttempt:
        """Return a verified candidate only to its current originating manager."""
        async with self.session_manager() as session:
            toolkit = await self._authorize(session, requester, lock=False)
            row = await self._attempt(session, attempt_id)
            attempt = self._bound(row, requester)
            await self._registration(session, toolkit, attempt.registration)
            current = await self._connection(session, toolkit.id)
            current_id = None if current is None else current.id
            if (
                row.status is not GitHubUserAttemptStatus.REVIEW
                or row.expires_at <= datetime.datetime.now(datetime.UTC)
                or row.captured_connection_id != current_id
                or attempt.candidate is None
            ):
                raise _error(
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
        """Publish verified account only to the exact still-current attempt."""
        async with self.session_manager() as session:
            toolkit = await self._authorize(session, requester, lock=True)
            row = await self._attempt(session, attempt_id)
            attempt = self._bound(row, requester)
            await self._registration(session, toolkit, registration)
            current = await self._connection(session, toolkit.id)
            current_id = None if current is None else current.id
            if (
                row.status is not GitHubUserAttemptStatus.EXCHANGING
                or row.expires_at <= datetime.datetime.now(datetime.UTC)
                or current_id != row.captured_connection_id
                or not _same_registration(attempt.registration, registration)
            ):
                raise _error(
                    GitHubUserErrorCode.STALE,
                    "Authorization setup changed. Start a new attempt.",
                )
            if (
                row.encrypted_issued_token is None
                or self.cipher.decrypt(row.encrypted_issued_token)
                != candidate.access_token
            ):
                raise _error(
                    GitHubUserErrorCode.STALE,
                    "The verified candidate does not match the received token.",
                )
            row.encrypted_candidate = self.cipher.encrypt(
                CandidatePayload(candidate=candidate).model_dump_json()
            )
            row.status = GitHubUserAttemptStatus.REVIEW
            row.exchange_in_flight = False
            await session.write_session.flush()
            return attempt_from(row, self.cipher)

    async def confirm(
        self,
        *,
        requester: GitHubUserRequester,
        attempt_id: str,
        registration: GitHubUserRegistration,
    ) -> GitHubUserConnection:
        """Atomically transfer a reviewed credential and retire only the old token."""
        async with self.session_manager() as session:
            toolkit = await self._authorize(session, requester, lock=True)
            row = await self._attempt(session, attempt_id)
            attempt = self._bound(row, requester)
            await self._registration(session, toolkit, registration)
            current = await self._connection(session, toolkit.id)
            current_id = None if current is None else current.id
            if (
                row.status is not GitHubUserAttemptStatus.REVIEW
                or row.expires_at <= datetime.datetime.now(datetime.UTC)
                or row.captured_connection_id != current_id
                or not _same_registration(attempt.registration, registration)
                or attempt.candidate is None
            ):
                raise _error(
                    GitHubUserErrorCode.STALE,
                    "Authorization confirmation is stale. Start a new attempt.",
                )
            candidate = attempt.candidate
            if current is not None:
                previous = connection_from(current, self.cipher)
                cleanup_registration = dataclasses.replace(
                    previous.registration, client_secret=registration.client_secret
                )
                if (
                    previous.registration.app_id != registration.app_id
                    or previous.registration.client_id != registration.client_id
                    or previous.registration.source != registration.source
                ):
                    raise _error(
                        GitHubUserErrorCode.STALE,
                        "Disconnect the original App connection before changing "
                        "App identity.",
                    )
                if previous.access_token != candidate.access_token:
                    await self._retire(
                        session,
                        toolkit_id=toolkit.id,
                        registration=cleanup_registration,
                        access_token=previous.access_token,
                        reason="replaced",
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
            row.encrypted_issued_token = None
            row.encrypted_candidate = None
            row.exchange_in_flight = False
            row.status = GitHubUserAttemptStatus.COMPLETED
            await self._prune_terminal(session, row)
            await session.write_session.flush()
            return connection_from(saved, self.cipher)

    async def retire_exchange_result(
        self,
        *,
        attempt_id: str,
        registration: GitHubUserRegistration,
        access_token: str,
        reason: str,
    ) -> GitHubUserCleanup | None:
        """Retire an issued token even after management authority is lost."""
        async with self.session_manager() as session:
            before = await session.read_session.scalar(
                sa.select(RDBGitHubUserAttempt).where(
                    RDBGitHubUserAttempt.id == attempt_id
                )
            )
            if before is None:
                # Terminal pruning follows successful transfer or cleanup capture.
                return None
            await session.write_session.scalar(
                sa.select(RDBToolkitConfig.id)
                .where(RDBToolkitConfig.id == before.toolkit_id)
                .with_for_update()
            )
            row = await session.read_session.scalar(
                sa.select(RDBGitHubUserAttempt)
                .where(RDBGitHubUserAttempt.id == attempt_id)
                .execution_options(populate_existing=True)
            )
            if row is None:
                return None
            attempt = attempt_from(row, self.cipher)
            if (
                not _same_registration(attempt.registration, registration)
                or row.status is GitHubUserAttemptStatus.COMPLETED
            ):
                raise _error(
                    GitHubUserErrorCode.STALE,
                    "The issued token cannot be retired through this setup.",
                )
            if (
                row.encrypted_issued_token is not None
                and self.cipher.decrypt(row.encrypted_issued_token) != access_token
            ):
                raise _error(
                    GitHubUserErrorCode.STALE,
                    "Issued token differs from the captured exchange.",
                )
            row.encrypted_issued_token = None
            row.encrypted_candidate = None
            row.exchange_in_flight = False
            row.status = GitHubUserAttemptStatus.CANCELLED
            cleanup = await self._retire_candidate(
                session,
                toolkit_id=row.toolkit_id,
                registration=registration,
                access_token=access_token,
                reason=reason,
            )
            await self._prune_terminal(session, row)
            return cleanup

    async def retain_discarded(
        self,
        *,
        requester: GitHubUserRequester,
        registration: GitHubUserRegistration,
        access_token: str,
        reason: str,
    ) -> GitHubUserCleanup | None:
        """Retain a rejected token for authorized cleanup."""
        async with self.session_manager() as session:
            await self._authorize(session, requester, lock=True)
            return await self._retire_candidate(
                session,
                toolkit_id=requester.toolkit_id,
                registration=registration,
                access_token=access_token,
                reason=reason,
            )

    async def cancel(self, *, requester: GitHubUserRequester, attempt_id: str) -> None:
        """Cancel only the initiating context and never clear a working connection."""
        async with self.session_manager() as session:
            await self._authorize(session, requester, lock=True)
            row = await self._attempt(session, attempt_id)
            self._bound(row, requester)
            if row.status is GitHubUserAttemptStatus.COMPLETED:
                return
            await self._cancel(session, row, reason="cancelled")

    async def disconnect(
        self,
        *,
        requester: GitHubUserRequester,
        registration: GitHubUserRegistration | None,
    ) -> None:
        """Disable local credentials first and retain exact original cleanup facts."""
        async with self.session_manager() as session:
            await self._authorize(session, requester, lock=True)
            current = await self._connection(session, requester.toolkit_id)
            if current is not None:
                before = connection_from(current, self.cipher)
                cleanup_registration = before.registration
                if (
                    registration is not None
                    and registration.app_id == before.registration.app_id
                    and registration.client_id == before.registration.client_id
                    and registration.source == before.registration.source
                ):
                    cleanup_registration = registration
                await self._retire(
                    session,
                    toolkit_id=requester.toolkit_id,
                    registration=cleanup_registration,
                    access_token=before.access_token,
                    reason="disconnected",
                )
                await session.write_session.delete(current)
            rows = (
                await session.read_session.scalars(
                    sa.select(RDBGitHubUserAttempt).where(
                        RDBGitHubUserAttempt.toolkit_id == requester.toolkit_id,
                        RDBGitHubUserAttempt.status.in_(_CURRENT),
                    )
                )
            ).all()
            for row in rows:
                await self._cancel(session, row, reason="disconnected")
            in_flight = await session.read_session.scalar(
                sa.select(RDBGitHubUserAttempt.id)
                .where(
                    RDBGitHubUserAttempt.toolkit_id == requester.toolkit_id,
                    RDBGitHubUserAttempt.exchange_in_flight.is_(True),
                )
                .limit(1)
            )
        if in_flight is not None:
            raise _error(
                GitHubUserErrorCode.CLEANUP_REQUIRED,
                "Local use is disabled, but token cleanup is incomplete. "
                "Retry when the original App registration is available and "
                "pending setup has finished.",
            )

    async def ensure_cleanup_complete(self, *, requester: GitHubUserRequester) -> None:
        """A canceled in-flight exchange cannot masquerade as completed cleanup."""
        async with self.session_manager() as session:
            await self._authorize(session, requester, lock=False)
            if await cleanup_pending(session, requester.toolkit_id):
                raise _error(
                    GitHubUserErrorCode.CLEANUP_REQUIRED,
                    "Token cleanup is incomplete. Retry after pending setup finishes.",
                )

    async def list_cleanup(
        self, *, requester: GitHubUserRequester
    ) -> tuple[GitHubUserCleanup, ...]:
        """Return only this authorized Toolkit's retired provider-cleanup facts."""
        async with self.session_manager() as session:
            await self._authorize(session, requester, lock=False)
            rows = (
                await session.read_session.scalars(
                    sa.select(RDBGitHubUserCleanup)
                    .where(RDBGitHubUserCleanup.toolkit_id == requester.toolkit_id)
                    .order_by(RDBGitHubUserCleanup.created_at, RDBGitHubUserCleanup.id)
                )
            ).all()
            return tuple(cleanup_from(row, self.cipher) for row in rows)

    async def finish_cleanup(
        self, *, requester: GitHubUserRequester, cleanup_id: str
    ) -> None:
        """Erase only the exact manager-authorized completed retirement."""
        async with self.session_manager() as session:
            await self._authorize(session, requester, lock=True)
            await session.write_session.execute(
                sa.delete(RDBGitHubUserCleanup).where(
                    RDBGitHubUserCleanup.id == cleanup_id,
                    RDBGitHubUserCleanup.toolkit_id == requester.toolkit_id,
                )
            )

    async def finish_retired(self, *, cleanup_id: str) -> None:
        """Erase exact cleanup after provider success despite lost setup rights."""
        async with self.session_manager() as session:
            await session.write_session.execute(
                sa.delete(RDBGitHubUserCleanup).where(
                    RDBGitHubUserCleanup.id == cleanup_id
                )
            )

    async def mark_cleanup_failure(
        self, *, requester: GitHubUserRequester, cleanup_id: str, reason: str
    ) -> None:
        """Persist a safe failed-cleanup state for current management details."""
        async with self.session_manager() as session:
            await self._authorize(session, requester, lock=True)
            await session.write_session.execute(
                sa.update(RDBGitHubUserCleanup)
                .where(
                    RDBGitHubUserCleanup.id == cleanup_id,
                    RDBGitHubUserCleanup.toolkit_id == requester.toolkit_id,
                )
                .values(status=GitHubUserCleanupStatus.FAILED, failure_reason=reason)
            )

    async def mark_retired_failure(self, *, cleanup_id: str, reason: str) -> None:
        """Record failure for a captured cleanup without restoring use authority."""
        async with self.session_manager() as session:
            await session.write_session.execute(
                sa.update(RDBGitHubUserCleanup)
                .where(RDBGitHubUserCleanup.id == cleanup_id)
                .values(status=GitHubUserCleanupStatus.FAILED, failure_reason=reason)
            )

    async def mark_reconnect_required(
        self, *, requester: GitHubUserRequester, connection_id: str, reason: str
    ) -> None:
        """A late authentication failure cannot invalidate a new connection."""
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
