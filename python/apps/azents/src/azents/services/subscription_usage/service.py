"""Subscription usage read service."""

import dataclasses
import datetime
import logging
import time
from collections.abc import AsyncIterator
from typing import Annotated, assert_never

import httpx
from azcommon.result import Failure, Result, Success
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.chatgpt_oauth import (
    CHATGPT_USAGE_BASE_URL,
    ChatGPTOAuthConnectionStatus,
    resolve_chatgpt_usage_base_url,
)
from azents.core.credentials import (
    ApiKeySecrets,
    ChatGPTOAuthConfig,
    ChatGPTOAuthSecrets,
    XaiOAuthConfig,
    XaiOAuthSecrets,
)
from azents.core.enums import LLMProvider
from azents.core.openrouter import OPENROUTER_API_BASE_URL
from azents.core.xai_oauth import (
    XAI_USAGE_BASE_URL,
    XaiOAuthConnectionStatus,
    resolve_xai_usage_base_url,
)
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.llm_provider_integration import LLMProviderIntegrationRepository
from azents.repos.llm_provider_integration.data import LLMProviderIntegrationWithSecrets
from azents.repos.llm_provider_integration.deps import (
    get_llm_provider_integration_repository,
)
from azents.services.chatgpt_oauth.data import ProviderRejected, ProviderUnavailable
from azents.services.chatgpt_oauth.runtime import (
    ensure_runtime_tokens,
    refresh_runtime_tokens,
)
from azents.services.xai_oauth.data import (
    ProviderEntitlementDenied as XaiProviderEntitlementDenied,
)
from azents.services.xai_oauth.data import ProviderRejected as XaiProviderRejected
from azents.services.xai_oauth.data import ProviderUnavailable as XaiProviderUnavailable
from azents.services.xai_oauth.runtime import (
    ensure_runtime_tokens as ensure_xai_runtime_tokens,
)
from azents.services.xai_oauth.runtime import (
    refresh_runtime_tokens as refresh_xai_runtime_tokens,
)

from .chatgpt_client import (
    CHATGPT_USAGE_CONTRACT_VERSION,
    ChatGPTSubscriptionUsageClient,
)
from .data import (
    ChatGPTUsageSnapshot,
    ChatGPTUsageUnauthorized,
    ChatGPTUsageUnavailable,
    OpenRouterUsageHidden,
    OpenRouterUsageSnapshot,
    OpenRouterUsageUnavailable,
    SubscriptionUsageAvailable,
    SubscriptionUsageExternal,
    SubscriptionUsageNotFound,
    SubscriptionUsageNotInWorkspace,
    SubscriptionUsageOutcome,
    SubscriptionUsageServiceFailure,
    SubscriptionUsageUnavailable,
    SubscriptionUsageUnavailableReason,
    SubscriptionUsageUnsupportedProvider,
    XaiUsageExternal,
    XaiUsageSnapshot,
    XaiUsageUnauthorized,
    XaiUsageUnavailable,
    unavailable_message,
)
from .openrouter_client import (
    OPENROUTER_USAGE_CONTRACT_VERSION,
    OpenRouterSubscriptionUsageClient,
)
from .xai_client import (
    XAI_USAGE_CONTRACT_VERSION,
    XAI_USAGE_EXTERNAL_MESSAGE,
    XaiSubscriptionUsageClient,
)

logger = logging.getLogger(__name__)


async def _get_http_client() -> AsyncIterator[httpx.AsyncClient]:
    """Create the request-scoped HTTP client used for usage reads."""
    async with httpx.AsyncClient(timeout=20.0) as http_client:
        yield http_client


def get_chatgpt_usage_base_url() -> str:
    """Resolve the non-secret ChatGPT usage backend root."""
    return resolve_chatgpt_usage_base_url()


def get_xai_usage_base_url() -> str:
    """Resolve the non-secret xAI CLI proxy usage root."""
    return resolve_xai_usage_base_url()


def get_openrouter_usage_base_url() -> str:
    """Return the fixed OpenRouter API root used for key-credit reads."""
    return OPENROUTER_API_BASE_URL


@dataclasses.dataclass
class SubscriptionUsageService:
    """Load, authorize, refresh, and normalize one subscription usage read."""

    repository: Annotated[
        LLMProviderIntegrationRepository,
        Depends(get_llm_provider_integration_repository),
    ]
    session_manager: Annotated[
        SessionManager[AsyncSession], Depends(get_session_manager)
    ]
    http_client: Annotated[httpx.AsyncClient, Depends(_get_http_client)]
    chatgpt_usage_base_url: Annotated[str, Depends(get_chatgpt_usage_base_url)]
    xai_usage_base_url: Annotated[str, Depends(get_xai_usage_base_url)]
    openrouter_usage_base_url: Annotated[str, Depends(get_openrouter_usage_base_url)]

    async def read(
        self,
        *,
        integration_id: str,
        workspace_id: str,
        include_financial_details: bool,
    ) -> Result[SubscriptionUsageOutcome, SubscriptionUsageServiceFailure]:
        """Read subscription usage for one workspace integration."""
        started_at = time.perf_counter()
        async with self.session_manager() as session:
            integration = await self.repository.get_by_id_with_secrets(
                session, integration_id
            )
        if integration is None:
            failure = SubscriptionUsageNotFound(integration_id=integration_id)
            self._log_service_failure(
                integration_id=integration_id,
                provider=None,
                outcome="not_found",
                started_at=started_at,
            )
            return Failure(failure)
        if integration.workspace_id != workspace_id:
            failure = SubscriptionUsageNotInWorkspace(integration_id=integration_id)
            self._log_service_failure(
                integration_id=integration.id,
                provider=integration.provider,
                outcome="not_in_workspace",
                started_at=started_at,
            )
            return Failure(failure)
        match integration.provider:
            case LLMProvider.CHATGPT_OAUTH:
                result = await self._read_chatgpt_usage(
                    integration=integration,
                    include_financial_details=include_financial_details,
                )
            case LLMProvider.XAI_OAUTH:
                result = await self._read_xai_usage(
                    integration=integration,
                    include_financial_details=include_financial_details,
                )
            case LLMProvider.OPENROUTER:
                result = await self._read_openrouter_usage(
                    integration=integration,
                    include_financial_details=include_financial_details,
                )
            case _:
                failure = SubscriptionUsageUnsupportedProvider(
                    provider=integration.provider
                )
                self._log_service_failure(
                    integration_id=integration.id,
                    provider=integration.provider,
                    outcome="unsupported_provider",
                    started_at=started_at,
                )
                return Failure(failure)
        self._log_completion(
            integration=integration,
            outcome=result.value,
            http_status=result.http_status,
            started_at=started_at,
        )
        return Success(result.value)

    async def _read_chatgpt_usage(
        self,
        *,
        integration: LLMProviderIntegrationWithSecrets,
        include_financial_details: bool,
    ) -> "_UsageReadResult":
        """Execute the ChatGPT-specific freshness and one-retry flow."""
        if not integration.enabled:
            return self._unavailable(
                integration=integration,
                reason=SubscriptionUsageUnavailableReason.DISABLED,
                retryable=False,
                http_status=None,
            )
        if not isinstance(integration.secrets, ChatGPTOAuthSecrets) or not isinstance(
            integration.config, ChatGPTOAuthConfig
        ):
            return self._unavailable(
                integration=integration,
                reason=SubscriptionUsageUnavailableReason.INVALID_PROVIDER_RESPONSE,
                retryable=False,
                http_status=None,
            )
        if integration.config.status == ChatGPTOAuthConnectionStatus.DISABLED.value:
            return self._unavailable(
                integration=integration,
                reason=SubscriptionUsageUnavailableReason.DISABLED,
                retryable=False,
                http_status=None,
            )
        if (
            integration.config.status
            == ChatGPTOAuthConnectionStatus.REFRESH_REQUIRED.value
        ):
            return self._unavailable(
                integration=integration,
                reason=SubscriptionUsageUnavailableReason.RECONNECT_REQUIRED,
                retryable=False,
                http_status=None,
            )

        fresh_result = await ensure_runtime_tokens(
            integration=integration,
            integration_repository=self.repository,
            session_manager=self.session_manager,
        )
        match fresh_result:
            case Success(fresh_integration):
                return await self._read_chatgpt_with_retry(
                    integration=fresh_integration,
                    include_financial_details=include_financial_details,
                )
            case Failure(error):
                return self._refresh_failure(
                    integration=integration,
                    error=error,
                )
            case _:
                assert_never(fresh_result)

    async def _read_chatgpt_with_retry(
        self,
        *,
        integration: LLMProviderIntegrationWithSecrets,
        include_financial_details: bool,
    ) -> "_UsageReadResult":
        """Read usage and force exactly one refresh only after an adapter 401."""
        credentials = _chatgpt_credentials(integration)
        if credentials is None:
            return self._unavailable(
                integration=integration,
                reason=SubscriptionUsageUnavailableReason.INVALID_PROVIDER_RESPONSE,
                retryable=False,
                http_status=None,
            )
        first = await self._chatgpt_client().read_usage(
            secrets=credentials.secrets,
            config=credentials.config,
        )
        match first:
            case ChatGPTUsageSnapshot():
                return self._available(
                    integration=integration,
                    snapshot=first,
                    include_financial_details=include_financial_details,
                )
            case ChatGPTUsageUnavailable():
                return self._from_adapter_unavailable(
                    integration=integration,
                    outcome=first,
                )
            case ChatGPTUsageUnauthorized():
                return await self._retry_after_unauthorized(
                    integration=integration,
                    include_financial_details=include_financial_details,
                    first_unauthorized=first,
                )
            case _:
                assert_never(first)

    async def _retry_after_unauthorized(
        self,
        *,
        integration: LLMProviderIntegrationWithSecrets,
        include_financial_details: bool,
        first_unauthorized: ChatGPTUsageUnauthorized,
    ) -> "_UsageReadResult":
        """Force one token refresh and retry one unauthorized usage request once."""
        refresh_result = await refresh_runtime_tokens(
            integration=integration,
            integration_repository=self.repository,
            session_manager=self.session_manager,
        )
        match refresh_result:
            case Failure(error):
                return self._refresh_failure(
                    integration=integration,
                    error=error,
                    http_status=first_unauthorized.http_status,
                )
            case Success(refreshed_integration):
                credentials = _chatgpt_credentials(refreshed_integration)
                if credentials is None:
                    return self._unavailable(
                        integration=refreshed_integration,
                        reason=(
                            SubscriptionUsageUnavailableReason.INVALID_PROVIDER_RESPONSE
                        ),
                        retryable=False,
                        http_status=first_unauthorized.http_status,
                    )
                retry = await self._chatgpt_client().read_usage(
                    secrets=credentials.secrets,
                    config=credentials.config,
                )
                match retry:
                    case ChatGPTUsageSnapshot():
                        return self._available(
                            integration=refreshed_integration,
                            snapshot=retry,
                            include_financial_details=include_financial_details,
                        )
                    case ChatGPTUsageUnavailable():
                        return self._from_adapter_unavailable(
                            integration=refreshed_integration,
                            outcome=retry,
                        )
                    case ChatGPTUsageUnauthorized():
                        return self._unavailable(
                            integration=refreshed_integration,
                            reason=SubscriptionUsageUnavailableReason.RECONNECT_REQUIRED,
                            retryable=False,
                            http_status=retry.http_status,
                        )
                    case _:
                        assert_never(retry)
            case _:
                assert_never(refresh_result)

    async def _read_xai_usage(
        self,
        *,
        integration: LLMProviderIntegrationWithSecrets,
        include_financial_details: bool,
    ) -> "_UsageReadResult":
        """Execute the xAI-specific freshness and one-retry flow."""
        if not integration.enabled:
            return self._unavailable(
                integration=integration,
                reason=SubscriptionUsageUnavailableReason.DISABLED,
                retryable=False,
                http_status=None,
            )
        credentials = _xai_credentials(integration)
        if credentials is None:
            return self._unavailable(
                integration=integration,
                reason=SubscriptionUsageUnavailableReason.INVALID_PROVIDER_RESPONSE,
                retryable=False,
                http_status=None,
            )
        status = credentials.config.status
        if status == XaiOAuthConnectionStatus.DISABLED.value:
            return self._unavailable(
                integration=integration,
                reason=SubscriptionUsageUnavailableReason.DISABLED,
                retryable=False,
                http_status=None,
            )
        if status == XaiOAuthConnectionStatus.REFRESH_REQUIRED.value:
            return self._unavailable(
                integration=integration,
                reason=SubscriptionUsageUnavailableReason.RECONNECT_REQUIRED,
                retryable=False,
                http_status=None,
            )
        if status == XaiOAuthConnectionStatus.ENTITLEMENT_DENIED.value:
            return self._unavailable(
                integration=integration,
                reason=SubscriptionUsageUnavailableReason.ENTITLEMENT_UNAVAILABLE,
                retryable=False,
                http_status=None,
            )
        fresh_result = await ensure_xai_runtime_tokens(
            integration=integration,
            integration_repository=self.repository,
            session_manager=self.session_manager,
        )
        match fresh_result:
            case Success(fresh_integration):
                return await self._read_xai_with_retry(
                    integration=fresh_integration,
                    include_financial_details=include_financial_details,
                )
            case Failure(error):
                return self._xai_refresh_failure(
                    integration=integration,
                    error=error,
                )
            case _:
                assert_never(fresh_result)

    async def _read_xai_with_retry(
        self,
        *,
        integration: LLMProviderIntegrationWithSecrets,
        include_financial_details: bool,
    ) -> "_UsageReadResult":
        """Read xAI usage and force one refresh after a required request 401."""
        credentials = _xai_credentials(integration)
        if credentials is None:
            return self._unavailable(
                integration=integration,
                reason=SubscriptionUsageUnavailableReason.INVALID_PROVIDER_RESPONSE,
                retryable=False,
                http_status=None,
            )
        first = await self._xai_client().read_usage(
            secrets=credentials.secrets,
            config=credentials.config,
        )
        match first:
            case XaiUsageSnapshot():
                return self._available(
                    integration=integration,
                    snapshot=first,
                    include_financial_details=include_financial_details,
                )
            case XaiUsageExternal():
                return self._external(integration=integration, url=first.url)
            case XaiUsageUnavailable():
                return self._from_adapter_unavailable(
                    integration=integration,
                    outcome=first,
                )
            case XaiUsageUnauthorized():
                return await self._retry_xai_after_unauthorized(
                    integration=integration,
                    include_financial_details=include_financial_details,
                    first_unauthorized=first,
                )
            case _:
                assert_never(first)

    async def _retry_xai_after_unauthorized(
        self,
        *,
        integration: LLMProviderIntegrationWithSecrets,
        include_financial_details: bool,
        first_unauthorized: XaiUsageUnauthorized,
    ) -> "_UsageReadResult":
        """Force one xAI token refresh and repeat the full usage sequence once."""
        refresh_result = await refresh_xai_runtime_tokens(
            integration=integration,
            integration_repository=self.repository,
            session_manager=self.session_manager,
        )
        match refresh_result:
            case Failure(error):
                return self._xai_refresh_failure(
                    integration=integration,
                    error=error,
                    http_status=first_unauthorized.http_status,
                )
            case Success(refreshed_integration):
                credentials = _xai_credentials(refreshed_integration)
                if credentials is None:
                    return self._unavailable(
                        integration=refreshed_integration,
                        reason=(
                            SubscriptionUsageUnavailableReason.INVALID_PROVIDER_RESPONSE
                        ),
                        retryable=False,
                        http_status=first_unauthorized.http_status,
                    )
                retry = await self._xai_client().read_usage(
                    secrets=credentials.secrets,
                    config=credentials.config,
                )
                match retry:
                    case XaiUsageSnapshot():
                        return self._available(
                            integration=refreshed_integration,
                            snapshot=retry,
                            include_financial_details=include_financial_details,
                        )
                    case XaiUsageExternal():
                        return self._external(
                            integration=refreshed_integration,
                            url=retry.url,
                        )
                    case XaiUsageUnavailable():
                        return self._from_adapter_unavailable(
                            integration=refreshed_integration,
                            outcome=retry,
                        )
                    case XaiUsageUnauthorized():
                        return self._unavailable(
                            integration=refreshed_integration,
                            reason=SubscriptionUsageUnavailableReason.RECONNECT_REQUIRED,
                            retryable=False,
                            http_status=retry.http_status,
                        )
                    case _:
                        assert_never(retry)
            case _:
                assert_never(refresh_result)

    async def _read_openrouter_usage(
        self,
        *,
        integration: LLMProviderIntegrationWithSecrets,
        include_financial_details: bool,
    ) -> "_UsageReadResult":
        """Read the current OpenRouter API key's bounded credit usage."""
        if not integration.enabled:
            return self._unavailable(
                integration=integration,
                reason=SubscriptionUsageUnavailableReason.DISABLED,
                retryable=False,
                http_status=None,
            )
        if not isinstance(integration.secrets, ApiKeySecrets):
            return self._unavailable(
                integration=integration,
                reason=SubscriptionUsageUnavailableReason.INVALID_PROVIDER_RESPONSE,
                retryable=False,
                http_status=None,
            )
        outcome = await self._openrouter_client().read_usage(
            secrets=integration.secrets
        )
        match outcome:
            case OpenRouterUsageSnapshot():
                return self._available(
                    integration=integration,
                    snapshot=outcome,
                    include_financial_details=include_financial_details,
                )
            case OpenRouterUsageHidden():
                return self._hidden(integration=integration)
            case OpenRouterUsageUnavailable():
                return self._from_adapter_unavailable(
                    integration=integration,
                    outcome=outcome,
                )
            case _:
                assert_never(outcome)

    def _chatgpt_client(self) -> ChatGPTSubscriptionUsageClient:
        """Create the ChatGPT adapter from request-scoped dependencies."""
        return ChatGPTSubscriptionUsageClient(
            http_client=self.http_client,
            usage_base_url=self.chatgpt_usage_base_url,
        )

    def _xai_client(self) -> XaiSubscriptionUsageClient:
        """Create the xAI adapter from request-scoped dependencies."""
        return XaiSubscriptionUsageClient(
            http_client=self.http_client,
            usage_base_url=self.xai_usage_base_url,
        )

    def _openrouter_client(self) -> OpenRouterSubscriptionUsageClient:
        """Create the OpenRouter adapter from request-scoped dependencies."""
        return OpenRouterSubscriptionUsageClient(
            http_client=self.http_client,
            api_base_url=self.openrouter_usage_base_url,
        )

    def _available(
        self,
        *,
        integration: LLMProviderIntegrationWithSecrets,
        snapshot: ChatGPTUsageSnapshot | XaiUsageSnapshot | OpenRouterUsageSnapshot,
        include_financial_details: bool,
    ) -> "_UsageReadResult":
        """Project a normalized adapter snapshot into an integration outcome."""
        return _UsageReadResult(
            value=SubscriptionUsageAvailable(
                integration_id=integration.id,
                provider=integration.provider,
                fetched_at=datetime.datetime.now(datetime.UTC),
                plan_label=snapshot.plan_label,
                limits=snapshot.limits,
                financial_details=(
                    snapshot.financial_details if include_financial_details else None
                ),
            ),
            http_status=None,
        )

    def _hidden(
        self,
        *,
        integration: LLMProviderIntegrationWithSecrets,
    ) -> "_UsageReadResult":
        """Project a successful read with no displayable usage limit."""
        return self._unavailable(
            integration=integration,
            reason=SubscriptionUsageUnavailableReason.NO_CREDIT_LIMIT,
            retryable=False,
            http_status=None,
        )

    def _external(
        self,
        *,
        integration: LLMProviderIntegrationWithSecrets,
        url: str,
    ) -> "_UsageReadResult":
        """Project a validated provider-managed usage page."""
        return _UsageReadResult(
            value=SubscriptionUsageExternal(
                integration_id=integration.id,
                provider=integration.provider,
                fetched_at=datetime.datetime.now(datetime.UTC),
                url=url,
                message=XAI_USAGE_EXTERNAL_MESSAGE,
            ),
            http_status=None,
        )

    def _from_adapter_unavailable(
        self,
        *,
        integration: LLMProviderIntegrationWithSecrets,
        outcome: ChatGPTUsageUnavailable
        | XaiUsageUnavailable
        | OpenRouterUsageUnavailable,
    ) -> "_UsageReadResult":
        """Project a controlled adapter failure without exposing HTTP details."""
        return self._unavailable(
            integration=integration,
            reason=outcome.reason,
            retryable=outcome.retryable,
            http_status=outcome.http_status,
        )

    def _refresh_failure(
        self,
        *,
        integration: LLMProviderIntegrationWithSecrets,
        error: ProviderRejected | ProviderUnavailable,
        http_status: int | None = None,
    ) -> "_UsageReadResult":
        """Map the shared OAuth freshness result to a usage availability state."""
        if isinstance(error, ProviderRejected):
            return self._unavailable(
                integration=integration,
                reason=SubscriptionUsageUnavailableReason.RECONNECT_REQUIRED,
                retryable=False,
                http_status=http_status,
            )
        return self._unavailable(
            integration=integration,
            reason=SubscriptionUsageUnavailableReason.TEMPORARILY_UNAVAILABLE,
            retryable=True,
            http_status=http_status,
        )

    def _xai_refresh_failure(
        self,
        *,
        integration: LLMProviderIntegrationWithSecrets,
        error: XaiProviderRejected
        | XaiProviderEntitlementDenied
        | XaiProviderUnavailable,
        http_status: int | None = None,
    ) -> "_UsageReadResult":
        """Map the shared xAI OAuth lifecycle to usage availability."""
        if isinstance(error, XaiProviderEntitlementDenied):
            return self._unavailable(
                integration=integration,
                reason=SubscriptionUsageUnavailableReason.ENTITLEMENT_UNAVAILABLE,
                retryable=False,
                http_status=http_status,
            )
        if isinstance(error, XaiProviderRejected):
            return self._unavailable(
                integration=integration,
                reason=SubscriptionUsageUnavailableReason.RECONNECT_REQUIRED,
                retryable=False,
                http_status=http_status,
            )
        return self._unavailable(
            integration=integration,
            reason=SubscriptionUsageUnavailableReason.TEMPORARILY_UNAVAILABLE,
            retryable=True,
            http_status=http_status,
        )

    def _unavailable(
        self,
        *,
        integration: LLMProviderIntegrationWithSecrets,
        reason: SubscriptionUsageUnavailableReason,
        retryable: bool,
        http_status: int | None,
    ) -> "_UsageReadResult":
        """Build a fixed-message unavailable response for one integration."""
        return _UsageReadResult(
            value=SubscriptionUsageUnavailable(
                integration_id=integration.id,
                provider=integration.provider,
                fetched_at=datetime.datetime.now(datetime.UTC),
                reason=reason,
                message=unavailable_message(reason),
                retryable=retryable,
            ),
            http_status=http_status,
        )

    def _log_service_failure(
        self,
        *,
        integration_id: str,
        provider: LLMProvider | None,
        outcome: str,
        started_at: float,
    ) -> None:
        """Record a safe completion event before provider dispatch begins."""
        extra: dict[str, object] = {
            "integration_id": integration_id,
            "operation": "subscription_usage_read",
            "outcome": outcome,
            "adapter_contract_version": None,
            "duration_ms": round((time.perf_counter() - started_at) * 1000),
        }
        if provider is not None:
            extra["provider"] = provider.value
        logger.info("Subscription usage read completed.", extra=extra)

    def _log_completion(
        self,
        *,
        integration: LLMProviderIntegrationWithSecrets,
        outcome: SubscriptionUsageOutcome,
        http_status: int | None,
        started_at: float,
    ) -> None:
        """Record one safe completion event without provider or credential data."""
        outcome_category = _outcome_category(outcome)
        extra: dict[str, object] = {
            "provider": integration.provider.value,
            "integration_id": integration.id,
            "operation": "subscription_usage_read",
            "outcome": outcome_category,
            "adapter_contract_version": _adapter_contract_version(integration.provider),
            "duration_ms": round((time.perf_counter() - started_at) * 1000),
        }
        if http_status is not None:
            extra["http_status"] = http_status
        logger.info("Subscription usage read completed.", extra=extra)


@dataclasses.dataclass(frozen=True)
class _UsageReadResult:
    """Internal service outcome paired with safe HTTP status telemetry."""

    value: SubscriptionUsageOutcome
    http_status: int | None


@dataclasses.dataclass(frozen=True)
class _ChatGPTUsageCredentials:
    """Validated ChatGPT credentials required by the private usage adapter."""

    secrets: ChatGPTOAuthSecrets
    config: ChatGPTOAuthConfig


def _chatgpt_credentials(
    integration: LLMProviderIntegrationWithSecrets,
) -> _ChatGPTUsageCredentials | None:
    """Narrow encrypted integration data before passing it to the adapter."""
    if not isinstance(integration.secrets, ChatGPTOAuthSecrets) or not isinstance(
        integration.config, ChatGPTOAuthConfig
    ):
        return None
    return _ChatGPTUsageCredentials(
        secrets=integration.secrets,
        config=integration.config,
    )


@dataclasses.dataclass(frozen=True)
class _XaiUsageCredentials:
    """Validated xAI credentials required by the private usage adapter."""

    secrets: XaiOAuthSecrets
    config: XaiOAuthConfig


def _xai_credentials(
    integration: LLMProviderIntegrationWithSecrets,
) -> _XaiUsageCredentials | None:
    """Narrow encrypted integration data before passing it to the xAI adapter."""
    if not isinstance(integration.secrets, XaiOAuthSecrets) or not isinstance(
        integration.config, XaiOAuthConfig
    ):
        return None
    return _XaiUsageCredentials(
        secrets=integration.secrets,
        config=integration.config,
    )


def _adapter_contract_version(provider: LLMProvider) -> str:
    """Return the provider-specific usage adapter contract version."""
    match provider:
        case LLMProvider.CHATGPT_OAUTH:
            return CHATGPT_USAGE_CONTRACT_VERSION
        case LLMProvider.XAI_OAUTH:
            return XAI_USAGE_CONTRACT_VERSION
        case LLMProvider.OPENROUTER:
            return OPENROUTER_USAGE_CONTRACT_VERSION
        case _:
            msg = "Subscription usage adapter has an unsupported provider."
            raise ValueError(msg)


def _outcome_category(outcome: SubscriptionUsageOutcome) -> str:
    """Return the closed public outcome category for safe logging."""
    match outcome:
        case SubscriptionUsageAvailable():
            return "available"
        case SubscriptionUsageExternal():
            return "external"
        case SubscriptionUsageUnavailable(
            reason=SubscriptionUsageUnavailableReason.NO_CREDIT_LIMIT
        ):
            return "hidden"
        case SubscriptionUsageUnavailable():
            return "unavailable"
        case _:
            assert_never(outcome)


CHATGPT_USAGE_DEFAULT_BASE_URL = CHATGPT_USAGE_BASE_URL
XAI_USAGE_DEFAULT_BASE_URL = XAI_USAGE_BASE_URL
