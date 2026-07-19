"""Kimi OAuth runtime token refresh support."""

import datetime
from typing import cast

import httpx
from azcommon.result import Failure, Result, Success
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.credentials import KimiOAuthConfig, KimiOAuthSecrets
from azents.core.enums import LLMProvider
from azents.core.kimi_oauth import KimiOAuthConnectionMethod, KimiOAuthConnectionStatus
from azents.rdb.session import SessionManager
from azents.repos.llm_provider_integration import LLMProviderIntegrationRepository
from azents.repos.llm_provider_integration.data import LLMProviderIntegrationWithSecrets

from .client import KimiOAuthClient
from .data import ProviderRejected, ProviderUnavailable, TokenSet

_REFRESH_WINDOW = datetime.timedelta(minutes=5)


async def ensure_runtime_tokens(
    *,
    integration: LLMProviderIntegrationWithSecrets,
    integration_repository: LLMProviderIntegrationRepository,
    session_manager: SessionManager[AsyncSession],
) -> Result[
    LLMProviderIntegrationWithSecrets,
    ProviderRejected | ProviderUnavailable,
]:
    """Ensure Kimi OAuth token freshness before a provider operation."""
    if integration.provider != LLMProvider.KIMI_OAUTH:
        return Success(integration)
    credentials = _credentials(integration)
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
        integration_repository=integration_repository,
        session_manager=session_manager,
    )


async def refresh_runtime_tokens(
    *,
    integration: LLMProviderIntegrationWithSecrets,
    integration_repository: LLMProviderIntegrationRepository,
    session_manager: SessionManager[AsyncSession],
) -> Result[
    LLMProviderIntegrationWithSecrets,
    ProviderRejected | ProviderUnavailable,
]:
    """Force one Kimi OAuth refresh for a rejected provider credential."""
    credentials = _credentials(integration)
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
            return await _persist_refresh_success(
                integration=integration,
                integration_repository=integration_repository,
                session_manager=session_manager,
                tokens=tokens,
            )
        case Failure(error):
            recovered = await _persist_refresh_failure(
                integration=integration,
                integration_repository=integration_repository,
                session_manager=session_manager,
                error=error,
            )
            if recovered is not None:
                return Success(recovered)
            return Failure(error)


async def _persist_refresh_success(
    *,
    integration: LLMProviderIntegrationWithSecrets,
    integration_repository: LLMProviderIntegrationRepository,
    session_manager: SessionManager[AsyncSession],
    tokens: TokenSet,
) -> Result[
    LLMProviderIntegrationWithSecrets,
    ProviderRejected | ProviderUnavailable,
]:
    """Store refresh success and return the latest integration."""
    config = cast(KimiOAuthConfig, integration.config)
    secrets = cast(KimiOAuthSecrets, integration.secrets)
    async with session_manager() as session:
        latest = await integration_repository.get_by_id_with_secrets_for_update(
            session, integration.id
        )
        if latest is None:
            return Failure(
                ProviderRejected(reason="Kimi OAuth integration was not found")
            )
        if _credentials_changed(original=integration, latest=latest):
            return Success(latest)
        update = await integration_repository.update_by_id(
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
            return Failure(
                ProviderRejected(reason="Kimi OAuth integration was not found")
            )
        refreshed = await integration_repository.get_by_id_with_secrets(
            session, integration.id
        )
    if refreshed is None:
        return Failure(ProviderRejected(reason="Kimi OAuth integration was not found"))
    return Success(refreshed)


async def _persist_refresh_failure(
    *,
    integration: LLMProviderIntegrationWithSecrets,
    integration_repository: LLMProviderIntegrationRepository,
    session_manager: SessionManager[AsyncSession],
    error: ProviderRejected | ProviderUnavailable,
) -> LLMProviderIntegrationWithSecrets | None:
    """Store a refresh failure unless a concurrent refresh already won."""
    config = cast(KimiOAuthConfig, integration.config)
    status = (
        KimiOAuthConnectionStatus.REFRESH_REQUIRED
        if isinstance(error, ProviderRejected)
        else KimiOAuthConnectionStatus.TEMPORARILY_UNAVAILABLE
    )
    async with session_manager() as session:
        latest = await integration_repository.get_by_id_with_secrets_for_update(
            session, integration.id
        )
        if latest is None:
            return None
        if _credentials_changed(original=integration, latest=latest):
            return latest
        await integration_repository.update_by_id(
            session,
            integration.id,
            {
                "config": KimiOAuthConfig(
                    connection_method=config.connection_method,
                    status=status.value,
                    connected_at=config.connected_at,
                    last_refreshed_at=config.last_refreshed_at,
                    last_failed_at=datetime.datetime.now(datetime.UTC),
                    last_failure_reason=error.reason,
                )
            },
        )
    return None


def _credentials_changed(
    *,
    original: LLMProviderIntegrationWithSecrets,
    latest: LLMProviderIntegrationWithSecrets,
) -> bool:
    """Return whether another refresh or reconnect replaced credentials."""
    return original.secrets != latest.secrets


def _credentials(
    integration: LLMProviderIntegrationWithSecrets,
) -> tuple[KimiOAuthSecrets, KimiOAuthConfig] | None:
    """Return typed Kimi credentials from one integration."""
    if not isinstance(integration.secrets, KimiOAuthSecrets) or not isinstance(
        integration.config, KimiOAuthConfig
    ):
        return None
    return integration.secrets, integration.config
