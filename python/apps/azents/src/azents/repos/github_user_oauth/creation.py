"""Database-only unpublished creation, one-use review and atomic publication."""

import dataclasses
import datetime
import secrets
from typing import Annotated

import sqlalchemy as sa
from fastapi import Depends
from pydantic import BaseModel, ConfigDict

from azents.core.github_user_creation import (
    GitHubUserCreationAttempt,
    GitHubUserCreationStart,
    GitHubUserCreationSubject,
)
from azents.core.github_user_oauth import (
    GitHubUserAttemptStatus,
    GitHubUserCandidate,
    GitHubUserConnectionStatus,
    GitHubUserErrorCode,
    GitHubUserOAuthError,
    GitHubUserRegistration,
    GitHubUserRevocation,
)
from azents.rdb.models.github_user_oauth import (
    RDBGitHubUserConnection,
    RDBGitHubUserCreation,
)
from azents.rdb.models.session import RDBSession
from azents.rdb.session_capabilities import WriteSession
from azents.repos.github_user_oauth.operations import GitHubUserOAuthOperationRepository
from azents.repos.github_user_oauth.payloads import (
    CandidatePayload,
    SetupPayload,
    encode_registration,
)
from azents.repos.toolkit.data import ToolkitCreate
from azents.repos.toolkit_namespace import ToolkitNamespaceRepository


class CreationPayload(BaseModel):
    """Only encrypted creation retains submitted registration and settings."""

    model_config = ConfigDict(hide_input_in_errors=True, extra="forbid")
    desired: ToolkitCreate
    setup: SetupPayload


def creation_from(
    row: RDBGitHubUserCreation, operations: GitHubUserOAuthOperationRepository
) -> GitHubUserCreationAttempt:
    payload = CreationPayload.model_validate_json(
        operations.cipher.decrypt(row.encrypted_setup)
    )
    candidate = (
        None
        if row.encrypted_candidate is None
        else CandidatePayload.model_validate_json(
            operations.cipher.decrypt(row.encrypted_candidate)
        ).candidate
    )
    return GitHubUserCreationAttempt(
        id=row.id,
        subject=GitHubUserCreationSubject(
            row.user_id, row.session_id, row.workspace_id, row.agent_id
        ),
        desired=payload.desired,
        registration=payload.setup.registration,
        redirect_uri=payload.setup.redirect_uri,
        nonce=payload.setup.nonce,
        code_verifier=payload.setup.code_verifier,
        expires_at=row.expires_at,
        status=row.status,
        candidate=candidate,
    )


def revocations(attempt: GitHubUserCreationAttempt) -> tuple[GitHubUserRevocation, ...]:
    return (
        ()
        if attempt.candidate is None
        else (
            GitHubUserRevocation(attempt.registration, attempt.candidate.access_token),
        )
    )


@dataclasses.dataclass(frozen=True)
class GitHubUserCreationRepository:
    """Revalidate exact manager scope without treating attempts as Toolkits."""

    operations: Annotated[GitHubUserOAuthOperationRepository, Depends()]
    namespaces: Annotated[ToolkitNamespaceRepository, Depends()]

    async def authorize(self, subject: GitHubUserCreationSubject) -> None:
        await self.operations.authorize_scope(**dataclasses.asdict(subject))

    async def _scope(
        self, session: WriteSession, subject: GitHubUserCreationSubject
    ) -> None:
        await self.operations.authorize_scope_in_session(
            session, **dataclasses.asdict(subject)
        )

    async def _row(
        self,
        session: WriteSession,
        subject: GitHubUserCreationSubject,
        attempt_id: str,
        *,
        live: bool,
    ) -> RDBGitHubUserCreation:
        await self._scope(session, subject)
        row = await session.write_session.scalar(
            sa.select(RDBGitHubUserCreation)
            .where(RDBGitHubUserCreation.id == attempt_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if row is None:
            raise GitHubUserOAuthError(
                GitHubUserErrorCode.NOT_FOUND, "GitHub creation attempt not found."
            )
        admitted = GitHubUserCreationSubject(
            row.user_id, row.session_id, row.workspace_id, row.agent_id
        )
        if admitted != subject:
            raise GitHubUserOAuthError(
                GitHubUserErrorCode.AUTHORITY,
                "GitHub creation does not match this authenticated context.",
            )
        if live and row.expires_at <= datetime.datetime.now(datetime.UTC):
            raise GitHubUserOAuthError(
                GitHubUserErrorCode.STALE, "GitHub creation authorization has expired."
            )
        return row

    async def start(
        self,
        subject: GitHubUserCreationSubject,
        *,
        desired: ToolkitCreate,
        setup: SetupPayload,
        expires_at: datetime.datetime,
    ) -> GitHubUserCreationStart:
        async with self.operations.session_manager() as session:
            # Serialize one current creation per initiating authentication scope.
            await session.write_session.scalar(
                sa.select(RDBSession.id)
                .where(RDBSession.id == subject.session_id)
                .with_for_update()
            )
            await self._scope(session, subject)
            await self.operations.validate_platform_registration(
                session, setup.registration
            )
            if (
                desired.workspace_id != subject.workspace_id
                or desired.owner_agent_id != subject.agent_id
            ):
                raise GitHubUserOAuthError(
                    GitHubUserErrorCode.AUTHORITY,
                    "GitHub creation ownership does not match.",
                )
            old = await session.write_session.scalar(
                sa.select(RDBGitHubUserCreation)
                .where(
                    RDBGitHubUserCreation.session_id == subject.session_id,
                    RDBGitHubUserCreation.workspace_id == subject.workspace_id,
                    RDBGitHubUserCreation.agent_id == subject.agent_id,
                )
                .with_for_update()
            )
            discarded = (
                () if old is None else revocations(creation_from(old, self.operations))
            )
            if old is not None:
                await session.write_session.delete(old)
                await session.write_session.flush()
            row = RDBGitHubUserCreation(
                user_id=subject.user_id,
                session_id=subject.session_id,
                workspace_id=subject.workspace_id,
                agent_id=subject.agent_id,
                encrypted_setup=self.operations.cipher.encrypt(
                    CreationPayload(desired=desired, setup=setup).model_dump_json()
                ),
                encrypted_candidate=None,
                status=GitHubUserAttemptStatus.PENDING,
                expires_at=expires_at,
            )
            session.write_session.add(row)
            await session.write_session.flush()
            return GitHubUserCreationStart(
                creation_from(row, self.operations), discarded
            )

    async def load(
        self, subject: GitHubUserCreationSubject, attempt_id: str
    ) -> GitHubUserCreationAttempt:
        async with self.operations.session_manager() as session:
            return creation_from(
                await self._row(session, subject, attempt_id, live=True),
                self.operations,
            )

    async def claim(
        self,
        subject: GitHubUserCreationSubject,
        *,
        attempt_id: str,
        nonce: str,
        redirect_uri: str,
    ) -> GitHubUserCreationAttempt:
        async with self.operations.session_manager() as session:
            row = await self._row(session, subject, attempt_id, live=True)
            attempt = creation_from(row, self.operations)
            if (
                row.status is not GitHubUserAttemptStatus.PENDING
                or not secrets.compare_digest(attempt.nonce, nonce)
                or attempt.redirect_uri != redirect_uri
            ):
                raise GitHubUserOAuthError(
                    GitHubUserErrorCode.STALE,
                    "GitHub creation state is invalid or already consumed.",
                )
            await self.operations.validate_platform_registration(
                session, attempt.registration
            )
            row.status = GitHubUserAttemptStatus.EXCHANGING
            await session.write_session.flush()
            return creation_from(row, self.operations)

    async def stage(
        self,
        subject: GitHubUserCreationSubject,
        *,
        attempt_id: str,
        registration: GitHubUserRegistration,
        candidate: GitHubUserCandidate,
    ) -> GitHubUserCreationAttempt:
        async with self.operations.session_manager() as session:
            row = await self._row(session, subject, attempt_id, live=True)
            attempt = creation_from(row, self.operations)
            if (
                row.status is not GitHubUserAttemptStatus.EXCHANGING
                or attempt.registration != registration
            ):
                raise GitHubUserOAuthError(
                    GitHubUserErrorCode.STALE, "GitHub creation registration changed."
                )
            await self.operations.validate_platform_registration(session, registration)
            row.encrypted_candidate = self.operations.cipher.encrypt(
                CandidatePayload(candidate=candidate).model_dump_json()
            )
            row.status = GitHubUserAttemptStatus.REVIEW
            await session.write_session.flush()
            return creation_from(row, self.operations)

    async def cancel(
        self, subject: GitHubUserCreationSubject, attempt_id: str
    ) -> tuple[GitHubUserRevocation, ...]:
        async with self.operations.session_manager() as session:
            row = await self._row(session, subject, attempt_id, live=False)
            captured = revocations(creation_from(row, self.operations))
            await session.write_session.delete(row)
            return captured

    async def discard_claimed(self, attempt_id: str) -> None:
        """Remove only this claimed failure; a later reservation has another ID."""
        async with self.operations.session_manager() as session:
            await session.write_session.execute(
                sa.delete(RDBGitHubUserCreation).where(
                    RDBGitHubUserCreation.id == attempt_id,
                    RDBGitHubUserCreation.status == GitHubUserAttemptStatus.EXCHANGING,
                )
            )

    async def confirm(
        self,
        subject: GitHubUserCreationSubject,
        *,
        attempt_id: str,
        registration: GitHubUserRegistration,
    ) -> str:
        async with self.operations.session_manager() as session:
            row = await self._row(session, subject, attempt_id, live=True)
            attempt = creation_from(row, self.operations)
            if (
                row.status is not GitHubUserAttemptStatus.REVIEW
                or attempt.candidate is None
                or attempt.registration != registration
            ):
                raise GitHubUserOAuthError(
                    GitHubUserErrorCode.STALE,
                    "GitHub creation account is not ready for confirmation.",
                )
            await self.operations.validate_platform_registration(session, registration)
            toolkit = await self.operations.toolkit_repository.create(
                session, attempt.desired
            )
            if subject.agent_id is not None:
                await self.namespaces.ensure_active(
                    session,
                    agent_id=subject.agent_id,
                    toolkit_id=toolkit.id,
                    base_slug=toolkit.slug,
                )
            candidate = attempt.candidate
            session.write_session.add(
                RDBGitHubUserConnection(
                    toolkit_id=toolkit.id,
                    app_id=registration.app_id,
                    account_id=candidate.account_id,
                    account_login=candidate.account_login,
                    account_avatar_url=candidate.account_avatar_url,
                    encrypted_access_token=self.operations.cipher.encrypt(
                        candidate.access_token
                    ),
                    encrypted_registration=encode_registration(
                        registration, self.operations.cipher
                    ),
                    status=GitHubUserConnectionStatus.CONNECTED,
                    failure_reason=None,
                )
            )
            await session.write_session.delete(row)
            await session.write_session.flush()
            return toolkit.id
