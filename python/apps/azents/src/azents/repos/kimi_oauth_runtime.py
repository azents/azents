"""Completed database-only Kimi runtime refresh persistence."""

import datetime
from dataclasses import dataclass
from typing import Annotated

from azcommon.result import Failure, Result, Success
from fastapi import Depends

from azents.core.credentials import KimiOAuthConfig, KimiOAuthSecrets
from azents.core.kimi_oauth import KimiOAuthConnectionStatus
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import WriteSession
from azents.repos.kimi_oauth_runtime_data import (
    KimiOAuthRefreshTokens,
    KimiRuntimeIntegrationMissing,
    KimiRuntimeInvalidCredentials,
    kimi_oauth_credentials,
)
from azents.repos.llm_provider_integration import LLMProviderIntegrationRepository
from azents.repos.llm_provider_integration.data import LLMProviderIntegrationWithSecrets
from azents.repos.llm_provider_integration.deps import (
    get_llm_provider_integration_repository,
)


@dataclass(frozen=True)
class KimiOAuthRuntimeRepository:
    """Retain the original row lock and secrets-only refresh identity fence."""

    session_manager: Annotated[
        SessionManager[WriteSession], Depends(get_session_manager)
    ]
    integration_repository: Annotated[
        LLMProviderIntegrationRepository,
        Depends(get_llm_provider_integration_repository),
    ]

    async def load_integration(
        self, *, integration_id: str
    ) -> LLMProviderIntegrationWithSecrets | None:
        """Capture detached credentials before a separate provider operation."""
        async with self.session_manager() as session:
            return await self.integration_repository.get_by_id_with_secrets(
                session, integration_id
            )

    async def persist_success(
        self,
        *,
        integration: LLMProviderIntegrationWithSecrets,
        tokens: KimiOAuthRefreshTokens,
    ) -> Result[
        LLMProviderIntegrationWithSecrets,
        KimiRuntimeInvalidCredentials | KimiRuntimeIntegrationMissing,
    ]:
        """Persist success or return the already-won concurrent credentials."""
        credentials = kimi_oauth_credentials(integration)
        if credentials is None:
            return Failure(KimiRuntimeInvalidCredentials())
        secrets, config = credentials
        async with self.session_manager() as session:
            latest = (
                await self.integration_repository.get_by_id_with_secrets_for_update(
                    session,
                    integration.id,
                )
            )
            if latest is None:
                return Failure(KimiRuntimeIntegrationMissing())
            if integration.secrets != latest.secrets:
                return Success(latest)
            update = await self.integration_repository.update_runtime_state_by_id(
                session,
                integration.id,
                {
                    "secrets": KimiOAuthSecrets(
                        access_token=tokens.access_token,
                        refresh_token=tokens.refresh_token,
                        expires_at=tokens.expires_at,
                        device_id=secrets.device_id,
                    ),
                    "config": KimiOAuthConfig(
                        connection_method=config.connection_method,
                        status=KimiOAuthConnectionStatus.CONNECTED.value,
                        connected_at=config.connected_at,
                        last_refreshed_at=datetime.datetime.now(datetime.UTC),
                        last_failed_at=None,
                        last_failure_reason=None,
                    ),
                },
            )
            if isinstance(update, Failure):
                return Failure(KimiRuntimeIntegrationMissing())
            refreshed = await self.integration_repository.get_by_id_with_secrets(
                session,
                integration.id,
            )
        if refreshed is None:
            return Failure(KimiRuntimeIntegrationMissing())
        return Success(refreshed)

    async def persist_failure(
        self,
        *,
        integration: LLMProviderIntegrationWithSecrets,
        status: KimiOAuthConnectionStatus,
        reason: str,
    ) -> LLMProviderIntegrationWithSecrets | None:
        """Keep failure updates and concurrent-secret recovery behavior unchanged."""
        credentials = kimi_oauth_credentials(integration)
        if credentials is None:
            return None
        _, config = credentials
        async with self.session_manager() as session:
            latest = (
                await self.integration_repository.get_by_id_with_secrets_for_update(
                    session,
                    integration.id,
                )
            )
            if latest is None:
                return None
            if integration.secrets != latest.secrets:
                return latest
            await self.integration_repository.update_runtime_state_by_id(
                session,
                integration.id,
                {
                    "config": KimiOAuthConfig(
                        connection_method=config.connection_method,
                        status=status.value,
                        connected_at=config.connected_at,
                        last_refreshed_at=config.last_refreshed_at,
                        last_failed_at=datetime.datetime.now(datetime.UTC),
                        last_failure_reason=reason,
                    ),
                },
            )
        return None
