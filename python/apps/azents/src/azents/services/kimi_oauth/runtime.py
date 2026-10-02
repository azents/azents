"""Kimi OAuth token orchestration between completed persistence operations."""

import datetime
from typing import assert_never

import httpx
from azcommon.result import Failure, Result, Success

from azents.core.enums import LLMProvider
from azents.core.kimi_oauth import KimiOAuthConnectionMethod, KimiOAuthConnectionStatus
from azents.repos.kimi_oauth_runtime import KimiOAuthRuntimeRepository
from azents.repos.kimi_oauth_runtime_data import (
    KimiOAuthRefreshTokens,
    KimiRuntimeIntegrationMissing,
    KimiRuntimeInvalidCredentials,
    kimi_oauth_credentials,
)
from azents.repos.llm_provider_integration.data import LLMProviderIntegrationWithSecrets

from .client import KimiOAuthClient
from .data import ProviderRejected, ProviderUnavailable

_REFRESH_WINDOW = datetime.timedelta(minutes=5)


async def ensure_runtime_tokens(
    *,
    integration: LLMProviderIntegrationWithSecrets,
    persistence_repository: KimiOAuthRuntimeRepository,
) -> Result[LLMProviderIntegrationWithSecrets, ProviderRejected | ProviderUnavailable]:
    """Ensure Kimi token freshness using the existing status and time predicates."""
    if integration.provider != LLMProvider.KIMI_OAUTH:
        return Success(integration)
    credentials = kimi_oauth_credentials(integration)
    if credentials is None:
        return Failure(ProviderRejected(reason="Kimi OAuth integration is invalid"))
    secrets, config = credentials
    retryable_statuses = {
        KimiOAuthConnectionStatus.CONNECTED.value,
        KimiOAuthConnectionStatus.TEMPORARILY_UNAVAILABLE.value,
    }
    if config.status not in retryable_statuses:
        return Failure(ProviderRejected(reason="Kimi OAuth reconnect is required"))
    refresh_threshold = datetime.datetime.now(datetime.UTC) + _REFRESH_WINDOW
    if secrets.expires_at > refresh_threshold:
        return Success(integration)
    return await refresh_runtime_tokens(
        integration=integration,
        persistence_repository=persistence_repository,
    )


async def refresh_runtime_tokens(
    *,
    integration: LLMProviderIntegrationWithSecrets,
    persistence_repository: KimiOAuthRuntimeRepository,
) -> Result[LLMProviderIntegrationWithSecrets, ProviderRejected | ProviderUnavailable]:
    """Perform the existing bounded HTTP refresh before database finalization."""
    credentials = kimi_oauth_credentials(integration)
    if integration.provider != LLMProvider.KIMI_OAUTH or credentials is None:
        return Failure(ProviderRejected(reason="Kimi OAuth integration is invalid"))
    secrets, config = credentials
    async with httpx.AsyncClient(timeout=20.0) as http_client:
        refresh_result = await KimiOAuthClient(http_client).refresh_tokens(
            refresh_token=secrets.refresh_token,
            device_id=secrets.device_id,
            connection_method=KimiOAuthConnectionMethod(config.connection_method),
        )
    match refresh_result:
        case Success(tokens):
            persisted = await persistence_repository.persist_success(
                integration=integration,
                tokens=KimiOAuthRefreshTokens(
                    access_token=tokens.access_token,
                    refresh_token=tokens.refresh_token,
                    expires_at=tokens.expires_at,
                ),
            )
            match persisted:
                case Success(value):
                    return Success(value)
                case Failure(error):
                    match error:
                        case KimiRuntimeInvalidCredentials():
                            return Failure(
                                ProviderRejected(
                                    reason="Kimi OAuth integration is invalid"
                                )
                            )
                        case KimiRuntimeIntegrationMissing():
                            return Failure(
                                ProviderRejected(
                                    reason="Kimi OAuth integration was not found"
                                )
                            )
                        case _:
                            assert_never(error)
                case _:
                    assert_never(persisted)
        case Failure(error):
            status = (
                KimiOAuthConnectionStatus.REFRESH_REQUIRED
                if isinstance(error, ProviderRejected)
                else KimiOAuthConnectionStatus.TEMPORARILY_UNAVAILABLE
            )
            recovered = await persistence_repository.persist_failure(
                integration=integration,
                status=status,
                reason=error.reason,
            )
            if recovered is not None:
                return Success(recovered)
            return Failure(error)
        case _:
            assert_never(refresh_result)
