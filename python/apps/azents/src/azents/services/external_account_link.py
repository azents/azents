"""External account linking service."""

import datetime
import hashlib
import secrets
from typing import Annotated

from fastapi import Depends

from azents.core.external_account_link import (
    EXTERNAL_ACCOUNT_LINK_CLEANUP_RETENTION,
    ExternalAccountLinkCandidateCreated,
    ExternalAccountLinkCandidateView,
    ExternalAccountLinkCleanupSummary,
    ExternalAccountLinkOriginView,
    ExternalAccountLinkView,
    ExternalAccountNativeLinkState,
    ExternalAccountOriginCreated,
    ExternalAccountProviderProofResult,
    VerifiedExternalAccountActor,
)
from azents.repos.external_account_link import ExternalAccountLinkRepository


class ExternalAccountLinkService:
    """Sequence completed external account link repository operations."""

    def __init__(
        self,
        repository: Annotated[
            ExternalAccountLinkRepository,
            Depends(ExternalAccountLinkRepository),
        ],
    ) -> None:
        self.repository = repository

    async def get_native_link_state(
        self,
        *,
        actor: VerifiedExternalAccountActor,
        now: datetime.datetime,
    ) -> ExternalAccountNativeLinkState:
        """Resolve current actor-private link state."""
        return await self.repository.get_native_link_state(actor=actor, now=now)

    async def create_origin(
        self,
        *,
        actor: VerifiedExternalAccountActor,
        now: datetime.datetime,
    ) -> ExternalAccountOriginCreated:
        """Create an actor-bound native origin."""
        return await self.repository.create_origin(actor=actor, now=now)

    async def verify_candidate_code(
        self,
        *,
        actor: VerifiedExternalAccountActor,
        origin_id: str,
        code: str,
        now: datetime.datetime,
    ) -> ExternalAccountProviderProofResult:
        """Verify a transient plaintext code without retaining it."""
        return await self.repository.verify_candidate_code(
            actor=actor,
            origin_id=origin_id,
            code_hash=_hash_code(code.strip()),
            now=now,
        )

    async def list_links(
        self,
        *,
        user_id: str,
        now: datetime.datetime,
    ) -> list[ExternalAccountLinkView]:
        """List own links including inactive membership projections."""
        return await self.repository.list_links(user_id=user_id, now=now)

    async def unlink(
        self,
        *,
        user_id: str,
        auth_session_id: str,
        link_id: str,
        now: datetime.datetime,
    ) -> ExternalAccountLinkView:
        """Terminally unlink one elevated owner link."""
        return await self.repository.unlink(
            user_id=user_id,
            auth_session_id=auth_session_id,
            link_id=link_id,
            now=now,
        )

    async def get_origin(
        self,
        *,
        user_id: str,
        origin_id: str,
        now: datetime.datetime,
    ) -> ExternalAccountLinkOriginView:
        """Load browser-safe origin confirmation context."""
        return await self.repository.get_origin(
            user_id=user_id,
            origin_id=origin_id,
            now=now,
        )

    async def create_candidate(
        self,
        *,
        user_id: str,
        auth_session_id: str,
        origin_id: str,
        now: datetime.datetime,
    ) -> ExternalAccountLinkCandidateCreated:
        """Stage one immutable elevated browser candidate."""
        code = secrets.token_urlsafe(16)
        return await self.repository.create_candidate(
            user_id=user_id,
            auth_session_id=auth_session_id,
            origin_id=origin_id,
            code_hash=_hash_code(code),
            plaintext_code=code,
            now=now,
        )

    async def get_candidate(
        self,
        *,
        user_id: str,
        auth_session_id: str,
        candidate_id: str,
        now: datetime.datetime,
    ) -> ExternalAccountLinkCandidateView:
        """Get exact current User/auth-Session candidate status."""
        return await self.repository.get_candidate(
            user_id=user_id,
            auth_session_id=auth_session_id,
            candidate_id=candidate_id,
            now=now,
        )

    async def confirm_candidate(
        self,
        *,
        user_id: str,
        auth_session_id: str,
        candidate_id: str,
        now: datetime.datetime,
    ) -> ExternalAccountLinkView:
        """Finalize an exact elevated browser candidate."""
        return await self.repository.confirm_candidate(
            user_id=user_id,
            auth_session_id=auth_session_id,
            candidate_id=candidate_id,
            now=now,
        )

    async def cancel_candidate(
        self,
        *,
        user_id: str,
        auth_session_id: str,
        candidate_id: str,
        now: datetime.datetime,
    ) -> ExternalAccountLinkCandidateView:
        """Cancel one exact current User/auth-Session candidate."""
        return await self.repository.cancel_candidate(
            user_id=user_id,
            auth_session_id=auth_session_id,
            candidate_id=candidate_id,
            now=now,
        )

    async def cleanup_expired(
        self,
        *,
        now: datetime.datetime,
        limit: int,
    ) -> ExternalAccountLinkCleanupSummary:
        """Remove one bounded batch older than the proof retention window."""
        return await self.repository.cleanup_expired(
            cutoff=now - EXTERNAL_ACCOUNT_LINK_CLEANUP_RETENTION,
            limit=limit,
        )


def _hash_code(code: str) -> str:
    """Return the one-way candidate-code hash."""
    return hashlib.sha256(code.encode()).hexdigest()
