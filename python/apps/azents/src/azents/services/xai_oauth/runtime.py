"""xAI OAuth runtime token refresh support."""

import datetime
from typing import assert_never

from azcommon.result import Failure, Result, Success

from azents.core.credentials import XaiOAuthConfig, XaiOAuthSecrets
from azents.core.enums import LLMProvider
from azents.core.xai_oauth import (
    XaiOAuthConnectionMethod,
    XaiOAuthConnectionStatus,
)
from azents.repos.llm_provider_integration.data import (
    LLMProviderIntegrationWithSecrets,
)
from azents.repos.xai_oauth_runtime import XaiOAuthRuntimeRepository
from azents.services.oauth_runtime_clients import XaiOAuthClientFactory

from .data import (
    ProviderEntitlementDenied,
    ProviderRejected,
    ProviderUnavailable,
    TokenSet,
)

_REFRESH_WINDOW = datetime.timedelta(minutes=5)


async def ensure_runtime_tokens(
    *,
    integration: LLMProviderIntegrationWithSecrets,
    persistence_repository: XaiOAuthRuntimeRepository,
    client_factory: XaiOAuthClientFactory,
) -> Result[
    LLMProviderIntegrationWithSecrets,
    ProviderRejected | ProviderEntitlementDenied | ProviderUnavailable,
]:
    """Ensure xAI OAuth token freshness before Runtime execution."""
    if integration.provider != LLMProvider.XAI_OAUTH:
        return Success(integration)
    if not isinstance(integration.secrets, XaiOAuthSecrets) or not isinstance(
        integration.config, XaiOAuthConfig
    ):
        return Failure(ProviderRejected(reason="xAI OAuth integration is invalid"))
    retryable_statuses = {
        XaiOAuthConnectionStatus.CONNECTED.value,
        XaiOAuthConnectionStatus.TEMPORARILY_UNAVAILABLE.value,
    }
    if integration.config.status not in retryable_statuses:
        return Failure(ProviderRejected(reason="xAI OAuth reconnect is required"))
    refresh_threshold = datetime.datetime.now(datetime.UTC) + _REFRESH_WINDOW
    if integration.secrets.expires_at > refresh_threshold:
        return Success(integration)
    return await refresh_runtime_tokens(
        integration=integration,
        persistence_repository=persistence_repository,
        client_factory=client_factory,
    )


async def refresh_runtime_tokens(
    *,
    integration: LLMProviderIntegrationWithSecrets,
    persistence_repository: XaiOAuthRuntimeRepository,
    client_factory: XaiOAuthClientFactory,
) -> Result[
    LLMProviderIntegrationWithSecrets,
    ProviderRejected | ProviderEntitlementDenied | ProviderUnavailable,
]:
    """Force one xAI OAuth refresh for a rejected runtime credential."""
    if integration.provider != LLMProvider.XAI_OAUTH:
        return Failure(ProviderRejected(reason="xAI OAuth integration is invalid"))
    if not isinstance(integration.secrets, XaiOAuthSecrets) or not isinstance(
        integration.config, XaiOAuthConfig
    ):
        return Failure(ProviderRejected(reason="xAI OAuth integration is invalid"))
    async with client_factory() as client:
        refresh_result = await client.refresh_tokens(
            refresh_token=integration.secrets.refresh_token,
            connection_method=XaiOAuthConnectionMethod(
                integration.config.connection_method
            ),
        )
    match refresh_result:
        case Success(tokens):
            refresh_success = await _persist_refresh_success(
                integration=integration,
                persistence_repository=persistence_repository,
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
                persistence_repository=persistence_repository,
                error=error,
            )
            if recovered is not None:
                return Success(recovered)
            return Failure(error)


async def _persist_refresh_success(
    *,
    integration: LLMProviderIntegrationWithSecrets,
    persistence_repository: XaiOAuthRuntimeRepository,
    tokens: TokenSet,
) -> Result[LLMProviderIntegrationWithSecrets, ProviderRejected]:
    """Store refresh success result and return latest integration."""
    if not isinstance(integration.config, XaiOAuthConfig):
        return Failure(ProviderRejected(reason="xAI OAuth integration is invalid"))
    config = integration.config
    refreshed = await persistence_repository.update_and_reload(
        original_integration=integration,
        secrets=XaiOAuthSecrets(
            access_token=tokens.access_token,
            refresh_token=tokens.refresh_token,
            id_token=tokens.id_token,
            expires_at=tokens.expires_at,
        ),
        config=XaiOAuthConfig(
            account_id=tokens.account_id or config.account_id,
            email=tokens.email or config.email,
            connection_method=config.connection_method,
            status=XaiOAuthConnectionStatus.CONNECTED.value,
            connected_at=config.connected_at,
            last_refreshed_at=datetime.datetime.now(datetime.UTC),
        ),
    )
    if refreshed is None:
        return Failure(ProviderRejected(reason="xAI OAuth integration was not found"))
    return Success(refreshed)


async def _persist_refresh_failure(
    *,
    integration: LLMProviderIntegrationWithSecrets,
    persistence_repository: XaiOAuthRuntimeRepository,
    error: ProviderRejected | ProviderEntitlementDenied | ProviderUnavailable,
) -> LLMProviderIntegrationWithSecrets | None:
    """Store refresh failure state or return concurrent refresh success result."""
    if not isinstance(integration.config, XaiOAuthConfig) or not isinstance(
        integration.secrets, XaiOAuthSecrets
    ):
        return None
    config = integration.config
    status = _failure_status(error)
    return await persistence_repository.persist_refresh_failure(
        original_integration=integration,
        config=XaiOAuthConfig(
            account_id=config.account_id,
            email=config.email,
            connection_method=config.connection_method,
            status=status.value,
            entitlement_status=(
                "denied"
                if status == XaiOAuthConnectionStatus.ENTITLEMENT_DENIED
                else config.entitlement_status
            ),
            connected_at=config.connected_at,
            last_refreshed_at=config.last_refreshed_at,
            last_failed_at=datetime.datetime.now(datetime.UTC),
            last_failure_reason=_safe_failure_reason(error),
        ),
    )


def _safe_failure_reason(
    error: ProviderRejected | ProviderEntitlementDenied | ProviderUnavailable,
) -> str:
    """Keep only classified diagnostics at the plaintext persistence boundary."""
    match error:
        case ProviderEntitlementDenied():
            return "xAI OAuth entitlement was denied"
        case ProviderRejected():
            return "xAI OAuth refresh was rejected"
        case ProviderUnavailable():
            return "xAI OAuth provider was unavailable"
        case _:
            assert_never(error)


def _failure_status(
    error: ProviderRejected | ProviderEntitlementDenied | ProviderUnavailable,
) -> XaiOAuthConnectionStatus:
    """Map provider refresh failure to connection status."""
    if isinstance(error, ProviderEntitlementDenied):
        return XaiOAuthConnectionStatus.ENTITLEMENT_DENIED
    if isinstance(error, ProviderRejected):
        return XaiOAuthConnectionStatus.REFRESH_REQUIRED
    return XaiOAuthConnectionStatus.TEMPORARILY_UNAVAILABLE
