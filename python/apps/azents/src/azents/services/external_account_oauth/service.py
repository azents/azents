"""Provider identity OAuth attempt service."""

import datetime
import hashlib
import secrets
from dataclasses import dataclass
from typing import Annotated

from azcommon.datetime import tznow
from azcommon.uuid import uuid7
from fastapi import Depends

from azents.core.crypto import CredentialCipher
from azents.core.deps import get_credential_cipher
from azents.core.enums import ExternalChannelProvider
from azents.core.external_account_oauth import EXTERNAL_ACCOUNT_OAUTH_ATTEMPT_TTL
from azents.core.oauth2 import generate_pkce_pair
from azents.repos.external_account_oauth.data import (
    ExternalAccountOAuthAttempt,
    ExternalAccountOAuthAttemptCreate,
)
from azents.repos.external_account_oauth.repository import (
    ExternalAccountOAuthAttemptRepository,
)


@dataclass(frozen=True)
class ExternalAccountOAuthAttemptStart:
    """One-time state and PKCE values for authorization URL creation."""

    attempt: ExternalAccountOAuthAttempt
    state: str
    code_verifier: str | None
    code_challenge: str | None


class ExternalAccountOAuthAttemptService:
    """Create and claim short-lived provider OAuth attempts."""

    def __init__(
        self,
        repository: Annotated[
            ExternalAccountOAuthAttemptRepository,
            Depends(ExternalAccountOAuthAttemptRepository),
        ],
        cipher: Annotated[CredentialCipher, Depends(get_credential_cipher)],
    ) -> None:
        self.repository = repository
        self.cipher = cipher

    async def create(
        self,
        *,
        user_id: str,
        auth_session_id: str,
        provider: ExternalChannelProvider,
        setting_generation: str,
        redirect_uri: str,
        use_pkce: bool,
        now: datetime.datetime | None = None,
    ) -> ExternalAccountOAuthAttemptStart:
        """Create one DB-backed open attempt after generating opaque state."""
        current = now or tznow()
        state = secrets.token_urlsafe(32)
        state_hash = hashlib.sha256(state.encode("ascii")).hexdigest()
        code_verifier, code_challenge = (
            generate_pkce_pair() if use_pkce else (None, None)
        )
        encrypted_verifier = (
            self.cipher.encrypt(code_verifier) if code_verifier is not None else None
        )
        create = ExternalAccountOAuthAttemptCreate(
            id=uuid7().hex,
            state_hash=state_hash,
            user_id=user_id,
            auth_session_id=auth_session_id,
            provider=provider,
            setting_generation=setting_generation,
            redirect_uri=redirect_uri,
            encrypted_pkce_verifier=encrypted_verifier,
            expires_at=current + EXTERNAL_ACCOUNT_OAUTH_ATTEMPT_TTL,
        )
        attempt = await self.repository.create(create=create)
        return ExternalAccountOAuthAttemptStart(
            attempt=attempt,
            state=state,
            code_verifier=code_verifier,
            code_challenge=code_challenge,
        )

    async def claim(
        self,
        *,
        state: str,
        user_id: str,
        auth_session_id: str,
        provider: ExternalChannelProvider,
        setting_generation: str,
        redirect_uri: str,
        now: datetime.datetime | None = None,
    ) -> ExternalAccountOAuthAttempt | None:
        """Atomically claim one exact open attempt and live authority."""
        current = now or tznow()
        state_hash = hashlib.sha256(state.encode("ascii")).hexdigest()
        return await self.repository.claim_open(
            state_hash=state_hash,
            user_id=user_id,
            auth_session_id=auth_session_id,
            provider=provider,
            setting_generation=setting_generation,
            redirect_uri=redirect_uri,
            now=current,
        )

    async def classify_claim_failure(
        self,
        *,
        state: str,
        user_id: str,
        auth_session_id: str,
        provider: ExternalChannelProvider,
        setting_generation: str,
        redirect_uri: str,
        now: datetime.datetime | None = None,
    ) -> str:
        """Classify one rejected callback with a sanitized stable code."""
        current = now or tznow()
        try:
            state_hash = hashlib.sha256(state.encode("ascii")).hexdigest()
        except UnicodeEncodeError:
            return "invalid_attempt"
        return await self.repository.classify_claim_failure(
            state_hash=state_hash,
            user_id=user_id,
            auth_session_id=auth_session_id,
            provider=provider,
            setting_generation=setting_generation,
            redirect_uri=redirect_uri,
            now=current,
        )

    async def fail(
        self,
        *,
        attempt_id: str,
        failure_code: str,
        now: datetime.datetime | None = None,
    ) -> bool:
        """Terminalize one claimed attempt with a sanitized failure code."""
        return await self.repository.fail(
            attempt_id=attempt_id,
            failure_code=failure_code,
            now=now or tznow(),
        )

    def decrypt_pkce_verifier(self, attempt: ExternalAccountOAuthAttempt) -> str | None:
        """Decrypt a request-local PKCE verifier for provider exchange."""
        if attempt.encrypted_pkce_verifier is None:
            return None
        return self.cipher.decrypt(attempt.encrypted_pkce_verifier)
