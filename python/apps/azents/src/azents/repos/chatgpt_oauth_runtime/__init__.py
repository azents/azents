"""Database operations for ChatGPT OAuth runtime token persistence."""

import dataclasses
from typing import Annotated

from azcommon.result import Failure
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.credentials import ChatGPTOAuthConfig, ChatGPTOAuthSecrets
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.llm_provider_integration import LLMProviderIntegrationRepository
from azents.repos.llm_provider_integration.data import LLMProviderIntegrationWithSecrets
from azents.repos.llm_provider_integration.deps import (
    get_llm_provider_integration_repository,
)


@dataclasses.dataclass
class ChatGPTOAuthRuntimeRepository:
    """Own completed integration persistence operations for OAuth refreshes."""

    integration_repository: Annotated[
        LLMProviderIntegrationRepository,
        Depends(get_llm_provider_integration_repository),
    ]
    session_manager: Annotated[
        SessionManager[AsyncSession], Depends(get_session_manager)
    ]

    async def load_integration(
        self,
        *,
        integration_id: str,
    ) -> LLMProviderIntegrationWithSecrets | None:
        """Load one current integration and close its read transaction."""
        async with self.session_manager() as session:
            return await self.integration_repository.get_by_id_with_secrets(
                session,
                integration_id,
            )

    async def update_and_reload(
        self,
        *,
        original_integration: LLMProviderIntegrationWithSecrets,
        secrets: ChatGPTOAuthSecrets,
        config: ChatGPTOAuthConfig,
    ) -> LLMProviderIntegrationWithSecrets | None:
        """Store success only while the original refresh identity remains current."""
        async with self.session_manager() as session:
            latest = (
                await self.integration_repository.get_by_id_with_secrets_for_update(
                    session, original_integration.id
                )
            )
            if latest is None or not _refresh_identity_matches(
                latest=latest, original=original_integration
            ):
                return latest
            update = await self.integration_repository.update_runtime_state_by_id(
                session,
                original_integration.id,
                {"secrets": secrets, "config": config},
            )
            if isinstance(update, Failure):
                return None
            return await self.integration_repository.get_by_id_with_secrets(
                session,
                original_integration.id,
            )

    async def persist_refresh_failure(
        self,
        *,
        original_integration: LLMProviderIntegrationWithSecrets,
        config: ChatGPTOAuthConfig,
    ) -> LLMProviderIntegrationWithSecrets | None:
        """Persist failure only while its original refresh identity remains current."""
        async with self.session_manager() as session:
            latest = (
                await self.integration_repository.get_by_id_with_secrets_for_update(
                    session, original_integration.id
                )
            )
            if latest is None or not _refresh_identity_matches(
                latest=latest, original=original_integration
            ):
                return latest
            await self.integration_repository.update_runtime_state_by_id(
                session,
                original_integration.id,
                {"config": config},
            )
            return None


def _refresh_identity_matches(
    *,
    latest: LLMProviderIntegrationWithSecrets,
    original: LLMProviderIntegrationWithSecrets,
) -> bool:
    """Compare user generation and refresh identity, allowing state-only failures."""
    if not isinstance(latest.secrets, ChatGPTOAuthSecrets) or not isinstance(
        original.secrets, ChatGPTOAuthSecrets
    ):
        return False
    if not isinstance(latest.config, ChatGPTOAuthConfig) or not isinstance(
        original.config, ChatGPTOAuthConfig
    ):
        return False
    return (
        latest.catalog_configuration_version == original.catalog_configuration_version
        and latest.secrets == original.secrets
        and latest.config.last_refreshed_at == original.config.last_refreshed_at
    )
