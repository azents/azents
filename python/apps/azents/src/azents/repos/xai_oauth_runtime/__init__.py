"""Completed database operations for xAI OAuth runtime token persistence."""

import dataclasses
from typing import Annotated

from azcommon.result import Failure
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.credentials import XaiOAuthConfig, XaiOAuthSecrets
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.llm_provider_integration import LLMProviderIntegrationRepository
from azents.repos.llm_provider_integration.data import LLMProviderIntegrationWithSecrets
from azents.repos.llm_provider_integration.deps import (
    get_llm_provider_integration_repository,
)


@dataclasses.dataclass
class XaiOAuthRuntimeRepository:
    """Own short, database-only operations for runtime OAuth refreshes."""

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
        """Return the current integration after completing its read transaction."""
        async with self.session_manager() as session:
            return await self.integration_repository.get_by_id_with_secrets(
                session, integration_id
            )

    async def update_and_reload(
        self,
        *,
        integration_id: str,
        secrets: XaiOAuthSecrets,
        config: XaiOAuthConfig,
    ) -> LLMProviderIntegrationWithSecrets | None:
        """Atomically store successful refresh credentials and return their row."""
        async with self.session_manager() as session:
            update = await self.integration_repository.update_runtime_state_by_id(
                session,
                integration_id,
                {"secrets": secrets, "config": config},
            )
            if isinstance(update, Failure):
                return None
            return await self.integration_repository.get_by_id_with_secrets(
                session, integration_id
            )

    async def persist_refresh_failure(
        self,
        *,
        integration_id: str,
        original_secrets: XaiOAuthSecrets,
        original_config: XaiOAuthConfig,
        config: XaiOAuthConfig,
    ) -> LLMProviderIntegrationWithSecrets | None:
        """Preserve a concurrent refresh using a locked identity check and write."""
        async with self.session_manager() as session:
            latest = (
                await self.integration_repository.get_by_id_with_secrets_for_update(
                    session, integration_id
                )
            )
            if (
                latest is None
                or not isinstance(latest.secrets, XaiOAuthSecrets)
                or not isinstance(latest.config, XaiOAuthConfig)
            ):
                return None
            if (
                latest.secrets.refresh_token != original_secrets.refresh_token
                or latest.config.last_refreshed_at != original_config.last_refreshed_at
            ):
                return latest
            await self.integration_repository.update_runtime_state_by_id(
                session, integration_id, {"config": config}
            )
            return None
