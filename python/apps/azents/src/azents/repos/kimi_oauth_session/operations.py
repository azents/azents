"""Completed Kimi device-session and integration persistence operations."""

from dataclasses import dataclass
from typing import Annotated, assert_never

from azcommon.result import Failure, Result, Success
from fastapi import Depends

from azents.core.credentials import KimiOAuthConfig, KimiOAuthSecrets
from azents.core.crypto import CredentialCipher
from azents.core.deps import get_credential_cipher
from azents.core.enums import LLMProvider
from azents.rdb.deps import get_read_only_session_manager, get_session_manager
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import ReadSession, WriteSession
from azents.repos.kimi_oauth_session.data import (
    KimiOAuthSession,
    KimiOAuthSessionCreate,
    KimiOAuthSessionWithSecrets,
    NotFound,
)
from azents.repos.kimi_oauth_session.repository import KimiOAuthSessionRepository
from azents.repos.llm_provider_integration import LLMProviderIntegrationRepository
from azents.repos.llm_provider_integration.data import (
    LLMProviderIntegration,
    LLMProviderIntegrationCreate,
)
from azents.repos.llm_provider_integration.data import NotFound as IntegrationNotFound
from azents.repos.llm_provider_integration.deps import (
    get_llm_provider_integration_repository,
)


def get_kimi_oauth_session_repository(
    cipher: Annotated[CredentialCipher, Depends(get_credential_cipher)],
) -> KimiOAuthSessionRepository:
    """Inject the existing credential-aware Kimi session repository."""
    return KimiOAuthSessionRepository(cipher)


@dataclass
class KimiOAuthOperations:
    """Close every device-session database operation before Provider OAuth I/O."""

    session_manager: Annotated[
        SessionManager[WriteSession], Depends(get_session_manager)
    ]
    session_repository: Annotated[
        KimiOAuthSessionRepository, Depends(get_kimi_oauth_session_repository)
    ]
    integration_repository: Annotated[
        LLMProviderIntegrationRepository,
        Depends(get_llm_provider_integration_repository),
    ]
    read_session_manager: Annotated[
        SessionManager[ReadSession], Depends(get_read_only_session_manager)
    ]

    async def create(self, create: KimiOAuthSessionCreate) -> KimiOAuthSession:
        """Persist one already-prepared Device OAuth session."""
        async with self.session_manager() as session:
            result = await self.session_repository.create(session, create)
        return result

    async def get_by_id_with_secrets(
        self, session_id: str
    ) -> KimiOAuthSessionWithSecrets | None:
        """Return detached pending-session credentials before Provider polling."""
        async with self.read_session_manager() as session:
            result = await self.session_repository.get_by_id_with_secrets(
                session, session_id
            )
        return result

    async def increase_poll_interval(
        self, session_id: str, *, seconds: int
    ) -> Result[KimiOAuthSession, NotFound]:
        """Preserve the existing pending/expiry-conditioned interval mutation."""
        async with self.session_manager() as session:
            result = await self.session_repository.increase_poll_interval(
                session, session_id, seconds=seconds
            )
        return result

    async def cancel(self, session_id: str) -> Result[KimiOAuthSession, NotFound]:
        """Preserve the existing pending/expiry-conditioned cancellation."""
        async with self.session_manager() as session:
            result = await self.session_repository.cancel(session, session_id)
        return result

    async def consume_and_save_tokens(
        self,
        *,
        workspace_id: str,
        session_id: str,
        secrets: KimiOAuthSecrets,
        config: KimiOAuthConfig,
    ) -> Result[LLMProviderIntegration, NotFound | IntegrationNotFound]:
        """Consume the device session and create/update its integration atomically."""
        async with self.session_manager() as session:
            consume_result = await self.session_repository.consume(session, session_id)
            if isinstance(consume_result, Failure):
                return Failure(consume_result.error)
            integrations = await self.integration_repository.list_by_workspace(
                session, workspace_id
            )
            existing = next(
                (
                    item
                    for item in integrations.items
                    if item.provider == LLMProvider.KIMI_OAUTH
                ),
                None,
            )
            if existing is None:
                integration = await self.integration_repository.create(
                    session,
                    LLMProviderIntegrationCreate(
                        workspace_id=workspace_id,
                        provider=LLMProvider.KIMI_OAUTH,
                        name="Kimi subscription",
                        secrets=secrets,
                        config=config,
                    ),
                )
            else:
                update_result = await self.integration_repository.update_by_id(
                    session, existing.id, {"secrets": secrets, "config": config}
                )
                match update_result:
                    case Success(integration):
                        pass
                    case Failure(error):
                        return Failure(error)
                    case _:
                        assert_never(update_result)
        return Success(integration)
