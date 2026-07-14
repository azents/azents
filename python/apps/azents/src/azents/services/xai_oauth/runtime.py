"""xAI OAuth runtime token refresh support."""

import asyncio
import datetime

import httpx
from azcommon.result import Failure, Result, Success
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.credentials import XaiOAuthConfig, XaiOAuthSecrets
from azents.core.enums import LLMProvider
from azents.core.xai_oauth import (
    XaiOAuthConnectionMethod,
    XaiOAuthConnectionStatus,
)
from azents.rdb.session import SessionManager
from azents.repos.llm_provider_integration import LLMProviderIntegrationRepository
from azents.repos.llm_provider_integration.data import (
    LLMProviderIntegrationWithSecrets,
)
from azents.utils.task_recovery import (
    current_task_is_cancelling,
    run_bounded_cancellation_safe,
)

from .client import XaiOAuthClient
from .data import (
    ProviderEntitlementDenied,
    ProviderRejected,
    ProviderUnavailable,
    TokenSet,
)

_REFRESH_WINDOW = datetime.timedelta(hours=1)
_REFRESH_PERSIST_ATTEMPTS = 3


async def ensure_runtime_tokens(
    *,
    integration: LLMProviderIntegrationWithSecrets,
    integration_repository: LLMProviderIntegrationRepository,
    session_manager: SessionManager[AsyncSession],
) -> Result[
    LLMProviderIntegrationWithSecrets,
    ProviderRejected | ProviderEntitlementDenied | ProviderUnavailable,
]:
    """Ensure xAI OAuth token freshness before Runtime execution."""
    if integration.provider != LLMProvider.XAI_OAUTH:
        return Success(integration)
    async with session_manager() as session:
        latest = await integration_repository.get_by_id_with_secrets(
            session,
            integration.id,
        )
    rejection = _runtime_rejection(latest)
    if rejection is not None:
        return Failure(rejection)
    assert latest is not None
    assert isinstance(latest.secrets, XaiOAuthSecrets)
    assert isinstance(latest.config, XaiOAuthConfig)
    refresh_threshold = datetime.datetime.now(datetime.UTC) + _REFRESH_WINDOW
    if latest.secrets.expires_at > refresh_threshold:
        return Success(latest)

    async with httpx.AsyncClient(timeout=20.0) as http_client:
        refresh_result = await XaiOAuthClient(http_client).refresh_tokens(
            refresh_token=latest.secrets.refresh_token,
            connection_method=XaiOAuthConnectionMethod(latest.config.connection_method),
        )
    match refresh_result:
        case Success(tokens):
            refresh_success = await _persist_refresh_success(
                integration=latest,
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
            return await _persist_refresh_failure(
                integration=latest,
                integration_repository=integration_repository,
                session_manager=session_manager,
                error=error,
            )


async def _persist_refresh_success(
    *,
    integration: LLMProviderIntegrationWithSecrets,
    integration_repository: LLMProviderIntegrationRepository,
    session_manager: SessionManager[AsyncSession],
    tokens: TokenSet,
) -> Result[LLMProviderIntegrationWithSecrets, ProviderRejected]:
    """Durably store provider-rotated tokens without abandoning them on cancel."""
    assert isinstance(integration.config, XaiOAuthConfig)
    config = integration.config
    expected_secrets = XaiOAuthSecrets(
        access_token=tokens.access_token,
        refresh_token=tokens.refresh_token,
        id_token=tokens.id_token,
        expires_at=tokens.expires_at,
    )
    expected_config = XaiOAuthConfig(
        account_id=tokens.account_id or config.account_id,
        email=tokens.email or config.email,
        connection_method=config.connection_method,
        status=XaiOAuthConnectionStatus.CONNECTED.value,
        connected_at=config.connected_at,
        last_refreshed_at=datetime.datetime.now(datetime.UTC),
    )

    async def persist_or_repair() -> Result[
        LLMProviderIntegrationWithSecrets,
        ProviderRejected,
    ]:
        first_error: Exception | None = None
        last_error: Exception | None = None
        for _attempt in range(_REFRESH_PERSIST_ATTEMPTS):
            try:
                async with session_manager() as session:
                    latest = await integration_repository.lock_by_id_with_secrets(
                        session,
                        integration.id,
                    )
                    if _matches_expected_refresh(
                        latest,
                        integration_id=integration.id,
                        expected_secrets=expected_secrets,
                        expected_config=expected_config,
                    ):
                        assert latest is not None
                        return Success(latest)
                    rejection = _runtime_rejection(latest)
                    if rejection is not None:
                        return Failure(rejection)
                    assert latest is not None
                    if _refresh_authority_changed(latest, integration):
                        return Success(latest)
                    update = await integration_repository.update_by_id(
                        session,
                        integration.id,
                        {
                            "secrets": expected_secrets,
                            "config": expected_config,
                        },
                    )
                    if isinstance(update, Failure):
                        return Failure(
                            ProviderRejected(
                                reason="xAI OAuth integration was not found"
                            )
                        )
                    refreshed = await integration_repository.get_by_id_with_secrets(
                        session,
                        integration.id,
                    )
                    if refreshed is None:
                        return Failure(
                            ProviderRejected(
                                reason="xAI OAuth integration was not found"
                            )
                        )
                return Success(refreshed)
            except asyncio.CancelledError as persistence_cancellation:
                if current_task_is_cancelling() or first_error is None:
                    raise
                raise first_error from persistence_cancellation
            except Exception as persistence_error:
                if first_error is None:
                    first_error = persistence_error
                last_error = persistence_error

        assert first_error is not None
        if last_error is first_error:
            raise first_error
        raise first_error from last_error

    return await run_bounded_cancellation_safe(persist_or_repair)


def _matches_expected_refresh(
    integration: LLMProviderIntegrationWithSecrets | None,
    *,
    integration_id: str,
    expected_secrets: XaiOAuthSecrets,
    expected_config: XaiOAuthConfig,
) -> bool:
    """Return whether the exact rotated token generation became durable."""
    return (
        integration is not None
        and integration.id == integration_id
        and integration.enabled
        and integration.provider == LLMProvider.XAI_OAUTH
        and integration.secrets == expected_secrets
        and integration.config == expected_config
    )


async def _persist_refresh_failure(
    *,
    integration: LLMProviderIntegrationWithSecrets,
    integration_repository: LLMProviderIntegrationRepository,
    session_manager: SessionManager[AsyncSession],
    error: ProviderRejected | ProviderEntitlementDenied | ProviderUnavailable,
) -> Result[
    LLMProviderIntegrationWithSecrets,
    ProviderRejected | ProviderEntitlementDenied | ProviderUnavailable,
]:
    """CAS refresh failure state without overwriting concurrent user changes."""
    status = _failure_status(error)
    async with session_manager() as session:
        latest = await integration_repository.lock_by_id_with_secrets(
            session,
            integration.id,
        )
        rejection = _runtime_rejection(latest)
        if rejection is not None:
            return Failure(rejection)
        assert latest is not None
        assert isinstance(latest.secrets, XaiOAuthSecrets)
        assert isinstance(latest.config, XaiOAuthConfig)
        if _refresh_authority_changed(latest, integration):
            return Success(latest)
        config = latest.config
        update = await integration_repository.update_by_id(
            session,
            integration.id,
            {
                "config": XaiOAuthConfig(
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
                    last_failure_reason=error.reason,
                )
            },
        )
        if isinstance(update, Failure):
            return Failure(
                ProviderRejected(reason="xAI OAuth integration was not found")
            )
    return Failure(error)


def _runtime_rejection(
    integration: LLMProviderIntegrationWithSecrets | None,
) -> ProviderRejected | None:
    """Validate current runtime authority before and after provider I/O."""
    if integration is None:
        return ProviderRejected(reason="xAI OAuth integration was not found")
    if not integration.enabled:
        return ProviderRejected(reason="xAI OAuth integration is disabled")
    if (
        integration.provider != LLMProvider.XAI_OAUTH
        or not isinstance(integration.secrets, XaiOAuthSecrets)
        or not isinstance(integration.config, XaiOAuthConfig)
    ):
        return ProviderRejected(reason="xAI OAuth integration is invalid")
    if integration.config.status not in {
        XaiOAuthConnectionStatus.CONNECTED.value,
        XaiOAuthConnectionStatus.TEMPORARILY_UNAVAILABLE.value,
    }:
        return ProviderRejected(reason="xAI OAuth reconnect is required")
    return None


def _refresh_authority_changed(
    latest: LLMProviderIntegrationWithSecrets,
    original: LLMProviderIntegrationWithSecrets,
) -> bool:
    """Return whether another writer changed the token refresh authority."""
    assert isinstance(latest.config, XaiOAuthConfig)
    assert isinstance(original.config, XaiOAuthConfig)
    return (
        latest.secrets != original.secrets
        or latest.config.connection_method != original.config.connection_method
    )


def _failure_status(
    error: ProviderRejected | ProviderEntitlementDenied | ProviderUnavailable,
) -> XaiOAuthConnectionStatus:
    """Map provider refresh failure to connection status."""
    if isinstance(error, ProviderEntitlementDenied):
        return XaiOAuthConnectionStatus.ENTITLEMENT_DENIED
    if isinstance(error, ProviderRejected):
        return XaiOAuthConnectionStatus.REFRESH_REQUIRED
    return XaiOAuthConnectionStatus.TEMPORARILY_UNAVAILABLE
