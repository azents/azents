"""ChatGPT OAuth runtime token refresh support."""

import datetime
from typing import cast

import httpx
from azcommon.result import Failure, Result, Success
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.chatgpt_oauth import (
    ChatGPTOAuthConnectionMethod,
    ChatGPTOAuthConnectionStatus,
)
from azents.core.credentials import ChatGPTOAuthConfig, ChatGPTOAuthSecrets
from azents.core.enums import LLMProvider
from azents.rdb.session import SessionManager
from azents.repos.llm_provider_integration import LLMProviderIntegrationRepository
from azents.repos.llm_provider_integration.data import (
    LLMProviderIntegrationWithSecrets,
)

from .client import ChatGPTOAuthClient
from .data import ProviderRejected, ProviderUnavailable, TokenSet

_REFRESH_WINDOW = datetime.timedelta(minutes=5)


async def ensure_runtime_tokens(
    *,
    integration: LLMProviderIntegrationWithSecrets,
    integration_repository: LLMProviderIntegrationRepository,
    session_manager: SessionManager[AsyncSession],
) -> Result[LLMProviderIntegrationWithSecrets, ProviderRejected | ProviderUnavailable]:
    """Ensure ChatGPT OAuth token freshness before Runtime execution."""
    if integration.provider != LLMProvider.CHATGPT_OAUTH:
        return Success(integration)
    if not isinstance(integration.secrets, ChatGPTOAuthSecrets) or not isinstance(
        integration.config, ChatGPTOAuthConfig
    ):
        return Failure(ProviderRejected(reason="ChatGPT OAuth integration is invalid"))
    retryable_statuses = {
        ChatGPTOAuthConnectionStatus.CONNECTED.value,
        ChatGPTOAuthConnectionStatus.TEMPORARILY_UNAVAILABLE.value,
    }
    if integration.config.status not in retryable_statuses:
        return Failure(ProviderRejected(reason="ChatGPT OAuth reconnect is required"))
    refresh_threshold = datetime.datetime.now(datetime.UTC) + _REFRESH_WINDOW
    if integration.secrets.expires_at > refresh_threshold:
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
) -> Result[LLMProviderIntegrationWithSecrets, ProviderRejected | ProviderUnavailable]:
    """Force one ChatGPT OAuth refresh for a rejected runtime credential."""
    if integration.provider != LLMProvider.CHATGPT_OAUTH:
        return Failure(ProviderRejected(reason="ChatGPT OAuth integration is invalid"))
    if not isinstance(integration.secrets, ChatGPTOAuthSecrets) or not isinstance(
        integration.config, ChatGPTOAuthConfig
    ):
        return Failure(ProviderRejected(reason="ChatGPT OAuth integration is invalid"))
    async with httpx.AsyncClient(timeout=20.0) as http_client:
        refresh_result = await ChatGPTOAuthClient(http_client).refresh_tokens(
            refresh_token=integration.secrets.refresh_token,
            connection_method=ChatGPTOAuthConnectionMethod(
                integration.config.connection_method
            ),
        )
    match refresh_result:
        case Success(tokens):
            refresh_success = await _persist_refresh_success(
                integration=integration,
                integration_repository=integration_repository,
                session_manager=session_manager,
                tokens=tokens,
            )
            match refresh_success:
                case Success(value):
                    return Success(value)
                case Failure(error):
                    return Failure(error)
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
) -> Result[LLMProviderIntegrationWithSecrets, ProviderRejected]:
    """Store refresh success result and return latest integration."""
    config = cast(ChatGPTOAuthConfig, integration.config)
    async with session_manager() as session:
        update = await integration_repository.update_by_id(
            session,
            integration.id,
            {
                "secrets": ChatGPTOAuthSecrets(
                    access_token=tokens.access_token,
                    refresh_token=tokens.refresh_token,
                    id_token=tokens.id_token,
                    expires_at=tokens.expires_at,
                ),
                "config": ChatGPTOAuthConfig(
                    account_id=tokens.account_id or config.account_id,
                    email=tokens.email or config.email,
                    plan_type=tokens.plan_type or config.plan_type,
                    connection_method=config.connection_method,
                    status=ChatGPTOAuthConnectionStatus.CONNECTED.value,
                    connected_at=config.connected_at,
                    last_refreshed_at=datetime.datetime.now(datetime.UTC),
                ),
            },
        )
        if isinstance(update, Failure):
            return Failure(
                ProviderRejected(reason="ChatGPT OAuth integration was not found")
            )
        refreshed = await integration_repository.get_by_id_with_secrets(
            session, integration.id
        )
    if refreshed is None:
        return Failure(
            ProviderRejected(reason="ChatGPT OAuth integration was not found")
        )
    return Success(refreshed)


async def _persist_refresh_failure(
    *,
    integration: LLMProviderIntegrationWithSecrets,
    integration_repository: LLMProviderIntegrationRepository,
    session_manager: SessionManager[AsyncSession],
    error: ProviderRejected | ProviderUnavailable,
) -> LLMProviderIntegrationWithSecrets | None:
    """Store refresh failure state or return concurrent refresh success result."""
    config = cast(ChatGPTOAuthConfig, integration.config)
    original_secrets = cast(ChatGPTOAuthSecrets, integration.secrets)
    async with session_manager() as session:
        latest = await integration_repository.get_by_id_with_secrets(
            session, integration.id
        )
    if (
        latest is not None
        and isinstance(latest.secrets, ChatGPTOAuthSecrets)
        and isinstance(latest.config, ChatGPTOAuthConfig)
    ):
        if (
            latest.secrets.refresh_token != original_secrets.refresh_token
            or latest.config.last_refreshed_at != config.last_refreshed_at
        ):
            return latest
    status = (
        ChatGPTOAuthConnectionStatus.REFRESH_REQUIRED
        if isinstance(error, ProviderRejected)
        else ChatGPTOAuthConnectionStatus.TEMPORARILY_UNAVAILABLE
    )
    async with session_manager() as session:
        await integration_repository.update_by_id(
            session,
            integration.id,
            {
                "config": ChatGPTOAuthConfig(
                    account_id=config.account_id,
                    email=config.email,
                    plan_type=config.plan_type,
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
