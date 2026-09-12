"""External account link service tests."""

import base64
import datetime
import hashlib
from typing import Any, cast

import pytest

from azents.core.enums import ExternalChannelProvider
from azents.core.external_account_link import (
    ExternalAccountLinkCandidateCreated,
    ExternalAccountLinkCandidateStatus,
    ExternalAccountProviderProofResult,
    VerifiedExternalAccountActor,
)

from .external_account_link import ExternalAccountLinkService


class _Repository:
    """Repository double that records transient code boundaries."""

    def __init__(self) -> None:
        self.candidate_code_hash: str | None = None
        self.candidate_plaintext_code: str | None = None
        self.proof_code_hash: str | None = None

    async def create_candidate(
        self,
        *,
        user_id: str,
        auth_session_id: str,
        origin_id: str,
        code_hash: str,
        plaintext_code: str,
        now: datetime.datetime,
    ) -> ExternalAccountLinkCandidateCreated:
        """Record candidate persistence inputs."""
        del user_id, auth_session_id
        self.candidate_code_hash = code_hash
        self.candidate_plaintext_code = plaintext_code
        return ExternalAccountLinkCandidateCreated(
            id="candidate-1",
            origin_id=origin_id,
            code=plaintext_code,
            expires_at=now + datetime.timedelta(minutes=10),
            status=ExternalAccountLinkCandidateStatus.PENDING_PROVIDER_PROOF,
        )

    async def verify_candidate_code(
        self,
        *,
        actor: VerifiedExternalAccountActor,
        origin_id: str,
        code_hash: str,
        now: datetime.datetime,
    ) -> ExternalAccountProviderProofResult:
        """Record proof persistence inputs."""
        del actor, origin_id, now
        self.proof_code_hash = code_hash
        return ExternalAccountProviderProofResult(
            candidate_id="candidate-1",
            status=ExternalAccountLinkCandidateStatus.PROVIDER_VERIFIED,
            remaining_attempts=5,
        )


def _actor() -> VerifiedExternalAccountActor:
    return VerifiedExternalAccountActor(
        connection_id="connection-1",
        connection_configuration_generation=1,
        principal_id="principal-1",
        provider=ExternalChannelProvider.SLACK,
        provider_tenant_id="team-1",
        provider_tenant_display_label="Team One",
        provider_user_id="user-external-1",
        provider_display_label="External User",
        provider_interaction_id="interaction-1",
        provider_channel_id="channel-1",
        provider_thread_id=None,
    )


@pytest.mark.asyncio
async def test_candidate_code_has_128_bits_and_repository_receives_hash() -> None:
    """Generate one plaintext code while persisting only its one-way hash."""
    repository = _Repository()
    service = ExternalAccountLinkService(repository=cast(Any, repository))
    now = datetime.datetime(2026, 9, 12, tzinfo=datetime.UTC)

    created = await service.create_candidate(
        user_id="user-1",
        auth_session_id="session-1",
        origin_id="origin-1",
        now=now,
    )

    assert repository.candidate_code_hash is not None
    persisted_hash = repository.candidate_code_hash
    assert persisted_hash == hashlib.sha256(created.code.encode()).hexdigest()
    assert created.code not in persisted_hash
    padding = "=" * (-len(created.code) % 4)
    assert len(base64.urlsafe_b64decode(created.code + padding)) == 16


@pytest.mark.asyncio
async def test_provider_code_hash_normalizes_copy_paste_whitespace() -> None:
    """Ignore surrounding copy/paste whitespace without retaining plaintext."""
    repository = _Repository()
    service = ExternalAccountLinkService(repository=cast(Any, repository))
    now = datetime.datetime(2026, 9, 12, tzinfo=datetime.UTC)

    await service.verify_candidate_code(
        actor=_actor(),
        origin_id="origin-1",
        code="  browser-code\n",
        now=now,
    )

    assert repository.proof_code_hash == hashlib.sha256(b"browser-code").hexdigest()
