"""Database-only unpublished creation, one-use review and atomic publication."""

import dataclasses
import datetime
import secrets
from typing import Annotated

import sqlalchemy as sa
from fastapi import Depends
from pydantic import BaseModel, ConfigDict

from azents.core.github_user_creation import (
    GitHubCreationSubject,
    GitHubPersonalCreationSubject,
    GitHubUserCreationAttempt,
    GitHubUserCreationSettings,
    GitHubUserCreationStart,
    github_creation_subject_for_owner,
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
from azents.core.toolkit_ownership import ToolkitOwnerKind, toolkit_owner_from_fields
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
from azents.repos.toolkit.data import ToolkitCreate, ToolkitCreation
from azents.repos.toolkit_namespace import ToolkitNamespaceRepository


class CreationPayload(BaseModel):
    """Only encrypted creation retains submitted registration and settings."""

    model_config = ConfigDict(hide_input_in_errors=True, extra="forbid")
    desired: ToolkitCreate
    setup: SetupPayload


class PersonalCreationPayload(BaseModel):
    """Explicit User-owned creation keeps the same Provider fields without Workspace."""

    model_config = ConfigDict(hide_input_in_errors=True, extra="forbid")
    desired: ToolkitCreation
    setup: SetupPayload


def creation_subject(row: RDBGitHubUserCreation) -> GitHubCreationSubject:
    """Decode exact persisted setup ownership, retaining old shared callback context."""
    return github_creation_subject_for_owner(
        row.user_id,
        row.session_id,
        toolkit_owner_from_fields(
            row.owner_kind,
            workspace_id=row.workspace_id,
            agent_id=row.agent_id,
            user_id=row.owner_user_id,
        ),
    )


def creation_from(
    row: RDBGitHubUserCreation, operations: GitHubUserOAuthOperationRepository
) -> GitHubUserCreationAttempt:
    payload_type = (
        PersonalCreationPayload
        if row.owner_kind is ToolkitOwnerKind.USER
        else CreationPayload
    )
    payload = payload_type.model_validate_json(
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
        subject=creation_subject(row),
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

    async def authorize(self, subject: GitHubCreationSubject) -> None:
        if isinstance(subject, GitHubPersonalCreationSubject):
            await self.operations.authorize_personal_scope(
                user_id=subject.user_id,
                session_id=subject.session_id,
                workspace_id=subject.workspace_id,
            )
        else:
            await self.operations.authorize_scope(**dataclasses.asdict(subject))

    async def _scope(
        self, session: WriteSession, subject: GitHubCreationSubject
    ) -> None:
        if isinstance(subject, GitHubPersonalCreationSubject):
            await self.operations.authorize_personal_scope_in_session(
                session,
                user_id=subject.user_id,
                session_id=subject.session_id,
                workspace_id=subject.workspace_id,
            )
        else:
            await self.operations.authorize_scope_in_session(
                session, **dataclasses.asdict(subject)
            )

    async def _row(
        self,
        session: WriteSession,
        subject: GitHubCreationSubject,
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
        admitted = creation_subject(row)
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
        subject: GitHubCreationSubject,
        *,
        desired: ToolkitCreation,
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
            if isinstance(subject, GitHubPersonalCreationSubject):
                if isinstance(desired, ToolkitCreate):
                    raise GitHubUserOAuthError(
                        GitHubUserErrorCode.AUTHORITY,
                        "Personal GitHub creation cannot have Workspace ownership.",
                    )
                payload = PersonalCreationPayload(desired=desired, setup=setup)
            elif (
                not isinstance(desired, ToolkitCreate)
                or desired.workspace_id != subject.workspace_id
                or desired.owner_agent_id != subject.agent_id
            ):
                raise GitHubUserOAuthError(
                    GitHubUserErrorCode.AUTHORITY,
                    "GitHub creation ownership does not match.",
                )
            else:
                payload = CreationPayload(desired=desired, setup=setup)
            old = await session.write_session.scalar(
                sa.select(RDBGitHubUserCreation)
                .where(
                    RDBGitHubUserCreation.session_id == subject.session_id,
                    RDBGitHubUserCreation.workspace_id == subject.workspace_id,
                    RDBGitHubUserCreation.agent_id == subject.agent_id,
                    RDBGitHubUserCreation.owner_kind == subject.owner.kind,
                    RDBGitHubUserCreation.owner_user_id
                    == (
                        subject.user_id
                        if isinstance(subject, GitHubPersonalCreationSubject)
                        else None
                    ),
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
                owner_kind=subject.owner.kind,
                owner_user_id=subject.user_id
                if isinstance(subject, GitHubPersonalCreationSubject)
                else None,
                workspace_id=subject.workspace_id,
                agent_id=subject.agent_id,
                encrypted_setup=self.operations.cipher.encrypt(
                    payload.model_dump_json()
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
        self, subject: GitHubCreationSubject, attempt_id: str
    ) -> GitHubUserCreationAttempt:
        async with self.operations.session_manager() as session:
            return creation_from(
                await self._row(session, subject, attempt_id, live=True),
                self.operations,
            )

    async def load_review(
        self, subject: GitHubCreationSubject, attempt_id: str
    ) -> GitHubUserCreationAttempt:
        """Admit live REVIEW and current registration for metadata observations."""
        async with self.operations.session_manager() as session:
            attempt = creation_from(
                await self._row(session, subject, attempt_id, live=True),
                self.operations,
            )
            if (
                attempt.status is not GitHubUserAttemptStatus.REVIEW
                or attempt.candidate is None
            ):
                raise GitHubUserOAuthError(
                    GitHubUserErrorCode.STALE,
                    "GitHub creation is not ready for review.",
                )
            await self.operations.validate_platform_registration(
                session, attempt.registration
            )
            return attempt

    async def claim(
        self,
        subject: GitHubCreationSubject,
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
        subject: GitHubCreationSubject,
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
        self, subject: GitHubCreationSubject, attempt_id: str
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
        subject: GitHubCreationSubject,
        *,
        attempt_id: str,
        registration: GitHubUserRegistration,
        settings: GitHubUserCreationSettings,
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
            desired = settings.apply(attempt.desired)
            if isinstance(subject, GitHubPersonalCreationSubject):
                toolkit = await self.operations.personal_toolkits.create_personal(
                    session,
                    user_id=subject.owner.user_id,
                    workspace_id=subject.workspace_id,
                    create=desired,
                )
            else:
                if not isinstance(desired, ToolkitCreate):
                    raise RuntimeError(
                        "Shared GitHub creation is missing its owner keys"
                    )
                toolkit = await self.operations.toolkit_repository.create(
                    session, desired
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
