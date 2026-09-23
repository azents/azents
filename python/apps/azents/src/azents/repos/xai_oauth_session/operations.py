"""Completed database operations for xAI device OAuth sessions."""

from typing import Annotated, assert_never

from azcommon.result import Failure, Result, Success
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.credentials import XaiOAuthConfig, XaiOAuthSecrets
from azents.core.crypto import CredentialCipher
from azents.core.deps import get_credential_cipher
from azents.core.enums import LLMCatalogLowererTarget, LLMCatalogPurpose, LLMProvider
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.llm_catalog import LLMCatalogRepository
from azents.repos.llm_provider_integration import LLMProviderIntegrationRepository
from azents.repos.llm_provider_integration.data import (
    LLMProviderIntegration,
    LLMProviderIntegrationCreate,
)
from azents.repos.llm_provider_integration.deps import (
    get_llm_provider_integration_repository,
)
from azents.repos.oauth_persistence_errors import OAuthPersistenceError
from azents.repos.xai_oauth_session import XaiOAuthSessionRepository
from azents.repos.xai_oauth_session.data import (
    NotFound,
    XaiOAuthSession,
    XaiOAuthSessionCreate,
    XaiOAuthSessionWithSecrets,
)


def _get_session_repository(
    cipher: Annotated[CredentialCipher, Depends(get_credential_cipher)],
) -> XaiOAuthSessionRepository:
    """Build the session repository with the configured credential cipher."""
    return XaiOAuthSessionRepository(cipher)


class XaiOAuthOperations:
    """Compose OAuth sessions, integrations and catalog writes atomically."""

    def __init__(
        self,
        session_manager: Annotated[
            SessionManager[AsyncSession], Depends(get_session_manager)
        ],
        session_repository: Annotated[
            XaiOAuthSessionRepository, Depends(_get_session_repository)
        ],
        integration_repository: Annotated[
            LLMProviderIntegrationRepository,
            Depends(get_llm_provider_integration_repository),
        ],
        catalog_repository: Annotated[
            LLMCatalogRepository, Depends(LLMCatalogRepository)
        ],
    ) -> None:
        self.session_manager = session_manager
        self.session_repository = session_repository
        self.integration_repository = integration_repository
        self.catalog_repository = catalog_repository

    async def valid_target(self, *, workspace_id: str, integration_id: str) -> bool:
        """Check the target's workspace and provider before external OAuth I/O."""
        async with self.session_manager() as session:
            target = await self.integration_repository.get_by_id(
                session, integration_id
            )
            return (
                target is not None
                and target.workspace_id == workspace_id
                and target.provider == LLMProvider.XAI_OAUTH
            )

    async def create_session(self, create: XaiOAuthSessionCreate) -> XaiOAuthSession:
        """Create a device session in one completed transaction."""
        async with self.session_manager() as session:
            return await self.session_repository.create(session, create)

    async def get_session_with_secrets(
        self, session_id: str
    ) -> XaiOAuthSessionWithSecrets | None:
        """Return a detached session value after a completed read."""
        async with self.session_manager() as session:
            return await self.session_repository.get_by_id_with_secrets(
                session, session_id
            )

    async def cancel_session(
        self, session_id: str
    ) -> Result[XaiOAuthSession, NotFound]:
        """Cancel a pending device session in one completed transaction."""
        async with self.session_manager() as session:
            return await self.session_repository.cancel(session, session_id)

    async def increase_poll_interval(
        self, session_id: str, *, seconds: int
    ) -> Result[XaiOAuthSession, NotFound]:
        """Increase the pending polling interval in one completed transaction."""
        async with self.session_manager() as session:
            return await self.session_repository.increase_poll_interval(
                session, session_id, seconds=seconds
            )

    async def save_tokens(
        self,
        *,
        workspace_id: str,
        session_id: str,
        secrets: XaiOAuthSecrets,
        config: XaiOAuthConfig,
    ) -> Result[LLMProviderIntegration, OAuthPersistenceError]:
        """Atomically consume a device session and publish integration credentials."""
        async with self.session_manager() as session:
            oauth_session = await self.session_repository.get_by_id(session, session_id)
            if oauth_session is None:
                return Failure(OAuthPersistenceError.TRANSITION_FAILED)
            target = None
            if oauth_session.integration_id is not None:
                target = (
                    await self.integration_repository.get_by_id_with_secrets_for_update(
                        session, oauth_session.integration_id
                    )
                )
                if (
                    target is None
                    or target.workspace_id != workspace_id
                    or target.provider != LLMProvider.XAI_OAUTH
                ):
                    return Failure(OAuthPersistenceError.INVALID_TARGET)
            consumed = await self.session_repository.consume(session, session_id)
            if isinstance(consumed, Failure):
                return Failure(OAuthPersistenceError.TRANSITION_FAILED)
            if target is None:
                integration = await self.integration_repository.create(
                    session,
                    LLMProviderIntegrationCreate(
                        workspace_id=workspace_id,
                        provider=LLMProvider.XAI_OAUTH,
                        name="xAI Grok OAuth",
                        secrets=secrets,
                        config=config,
                    ),
                )
            else:
                updated = await self.integration_repository.update_by_id(
                    session, target.id, {"secrets": secrets, "config": config}
                )
                match updated:
                    case Success(integration):
                        pass
                    case Failure():
                        # A locked target cannot disappear; propagate to roll back
                        # the already-consumed OAuth session if this invariant fails.
                        raise RuntimeError("Locked xAI integration update failed")
                    case _:
                        assert_never(updated)
            await self.catalog_repository.ensure_integration_catalog(
                session,
                integration_id=integration.id,
                provider=integration.provider,
                lowerer_target=LLMCatalogLowererTarget.LITELLM,
                purpose=LLMCatalogPurpose.CONVERSATION,
            )
            return Success(integration)
