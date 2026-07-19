"""Subscription usage service tests."""

import datetime
import logging
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from typing import Literal
from unittest.mock import AsyncMock

import httpx
import pytest
from azcommon.result import Failure, Success
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.chatgpt_oauth import ChatGPTOAuthConnectionMethod
from azents.core.credentials import ChatGPTOAuthConfig, ChatGPTOAuthSecrets
from azents.core.enums import LLMProvider
from azents.repos.llm_provider_integration.data import LLMProviderIntegrationWithSecrets
from azents.services.chatgpt_oauth.data import ProviderRejected, ProviderUnavailable

from .data import (
    SubscriptionUsageAvailable,
    SubscriptionUsageNotFound,
    SubscriptionUsageNotInWorkspace,
    SubscriptionUsageUnavailable,
    SubscriptionUsageUnavailableReason,
    SubscriptionUsageUnsupportedProvider,
)
from .service import SubscriptionUsageService

_SERVICE_MODULE = "azents.services.subscription_usage.service"


class _SessionManager:
    """Expose a typed no-op session context for repository mocks."""

    def __init__(self) -> None:
        self.session = AsyncSession()

    def __call__(self) -> AbstractAsyncContextManager[AsyncSession]:
        return self

    async def __aenter__(self) -> AsyncSession:
        return self.session

    async def __aexit__(self, *_args: object) -> None:
        return None


def _integration(
    *,
    workspace_id: str = "workspace-1",
    provider: LLMProvider = LLMProvider.CHATGPT_OAUTH,
    enabled: bool = True,
    status: Literal[
        "connected", "refresh_required", "temporarily_unavailable", "disabled"
    ] = "connected",
) -> LLMProviderIntegrationWithSecrets:
    now = datetime.datetime.now(datetime.UTC)
    return LLMProviderIntegrationWithSecrets(
        id="integration-1",
        workspace_id=workspace_id,
        provider=provider,
        name="ChatGPT Subscription",
        config=ChatGPTOAuthConfig(
            account_id="account-1",
            email="account@example.com",
            connection_method=ChatGPTOAuthConnectionMethod.DEVICE.value,
            status=status,
            connected_at=now,
            last_refreshed_at=now,
        ),
        enabled=enabled,
        created_at=now,
        updated_at=now,
        secrets=ChatGPTOAuthSecrets(
            access_token="access-1",
            refresh_token="refresh-1",
            expires_at=now + datetime.timedelta(hours=1),
        ),
    )


def _payload() -> dict[str, object]:
    return {
        "plan_type": "Pro",
        "rate_limit": {
            "primary_window": {
                "used_percent": 40,
                "limit_window_seconds": 18_000,
                "reset_at": 1_780_000_000,
            }
        },
        "credits": {"has_credits": True, "unlimited": False, "balance": "10.00"},
    }


async def _service(
    handler: Callable[[httpx.Request], httpx.Response],
    *,
    integration: LLMProviderIntegrationWithSecrets | None,
) -> tuple[SubscriptionUsageService, AsyncMock]:
    repository = AsyncMock()
    repository.get_by_id_with_secrets.return_value = integration
    transport = httpx.MockTransport(handler)
    http_client = httpx.AsyncClient(transport=transport)
    return (
        SubscriptionUsageService(
            repository=repository,
            session_manager=_SessionManager(),
            http_client=http_client,
            chatgpt_usage_base_url="https://usage.example.test/backend-api",
        ),
        repository,
    )


async def test_missing_and_cross_workspace_are_controlled_service_failures() -> None:
    """Avoid provider calls for absent or cross-workspace integrations."""
    missing, _ = await _service(
        lambda _request: pytest.fail("provider must not be called"),
        integration=None,
    )
    cross_workspace, _ = await _service(
        lambda _request: pytest.fail("provider must not be called"),
        integration=_integration(workspace_id="other-workspace"),
    )
    try:
        missing_result = await missing.read(
            integration_id="integration-1",
            workspace_id="workspace-1",
            include_financial_details=False,
        )
        cross_workspace_result = await cross_workspace.read(
            integration_id="integration-1",
            workspace_id="workspace-1",
            include_financial_details=False,
        )
    finally:
        await missing.http_client.aclose()
        await cross_workspace.http_client.aclose()

    assert isinstance(missing_result, Failure)
    assert isinstance(missing_result.error, SubscriptionUsageNotFound)
    assert isinstance(cross_workspace_result, Failure)
    assert isinstance(cross_workspace_result.error, SubscriptionUsageNotInWorkspace)


async def test_api_key_provider_is_unsupported() -> None:
    """Keep API-key billing outside the normalized subscription usage contract."""
    integration = _integration(provider=LLMProvider.OPENAI)
    service, _ = await _service(
        lambda _request: pytest.fail("provider must not be called"),
        integration=integration,
    )
    try:
        result = await service.read(
            integration_id=integration.id,
            workspace_id=integration.workspace_id,
            include_financial_details=True,
        )
    finally:
        await service.http_client.aclose()

    assert isinstance(result, Failure)
    assert isinstance(result.error, SubscriptionUsageUnsupportedProvider)


@pytest.mark.parametrize(
    ("integration", "expected_outcome", "expected_provider"),
    [
        (None, "not_found", None),
        (
            _integration(workspace_id="other-workspace"),
            "not_in_workspace",
            "chatgpt_oauth",
        ),
        (_integration(provider=LLMProvider.OPENAI), "unsupported_provider", "openai"),
    ],
)
async def test_early_service_failures_log_one_safe_completion_event(
    caplog: pytest.LogCaptureFixture,
    integration: LLMProviderIntegrationWithSecrets | None,
    expected_outcome: str,
    expected_provider: str | None,
) -> None:
    """Record completion telemetry even when provider dispatch never begins."""
    caplog.set_level(logging.INFO, logger=_SERVICE_MODULE)
    service, _ = await _service(
        lambda _request: pytest.fail("provider must not be called"),
        integration=integration,
    )
    try:
        await service.read(
            integration_id="integration-1",
            workspace_id="workspace-1",
            include_financial_details=False,
        )
    finally:
        await service.http_client.aclose()

    records = [
        record
        for record in caplog.records
        if record.getMessage() == "Subscription usage read completed."
    ]
    assert len(records) == 1
    record = records[0]
    assert getattr(record, "integration_id", None) == "integration-1"
    assert getattr(record, "operation", None) == "subscription_usage_read"
    assert getattr(record, "outcome", None) == expected_outcome
    assert getattr(record, "adapter_contract_version", "missing") is None
    assert getattr(record, "provider", None) == expected_provider


async def test_disabled_chatgpt_returns_without_refresh_or_usage_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Disabled ChatGPT integrations do not invoke token freshness or usage HTTP."""
    integration = _integration(enabled=False)
    ensure = AsyncMock()
    monkeypatch.setattr(f"{_SERVICE_MODULE}.ensure_runtime_tokens", ensure)
    service, _ = await _service(
        lambda _request: pytest.fail("provider must not be called"),
        integration=integration,
    )
    try:
        result = await service.read(
            integration_id=integration.id,
            workspace_id=integration.workspace_id,
            include_financial_details=True,
        )
    finally:
        await service.http_client.aclose()

    assert isinstance(result, Success)
    assert isinstance(result.value, SubscriptionUsageUnavailable)
    assert result.value.reason == SubscriptionUsageUnavailableReason.DISABLED
    ensure.assert_not_awaited()


async def test_financial_projection_depends_on_write_permission(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Strip provider financial values for read-only members before conversion."""
    integration = _integration()
    monkeypatch.setattr(
        f"{_SERVICE_MODULE}.ensure_runtime_tokens",
        AsyncMock(return_value=Success(integration)),
    )
    service, _ = await _service(
        lambda _request: httpx.Response(200, json=_payload()),
        integration=integration,
    )
    try:
        read_only = await service.read(
            integration_id=integration.id,
            workspace_id=integration.workspace_id,
            include_financial_details=False,
        )
        writer = await service.read(
            integration_id=integration.id,
            workspace_id=integration.workspace_id,
            include_financial_details=True,
        )
    finally:
        await service.http_client.aclose()

    assert isinstance(read_only, Success)
    assert isinstance(read_only.value, SubscriptionUsageAvailable)
    assert read_only.value.financial_details is None
    assert isinstance(writer, Success)
    assert isinstance(writer.value, SubscriptionUsageAvailable)
    assert writer.value.financial_details is not None


@pytest.mark.parametrize(
    ("refresh_failure", "reason", "retryable"),
    [
        (
            ProviderRejected(reason="invalid_grant"),
            SubscriptionUsageUnavailableReason.RECONNECT_REQUIRED,
            False,
        ),
        (
            ProviderUnavailable(reason="timeout"),
            SubscriptionUsageUnavailableReason.TEMPORARILY_UNAVAILABLE,
            True,
        ),
    ],
)
async def test_freshness_failures_map_to_controlled_usage_outcomes(
    monkeypatch: pytest.MonkeyPatch,
    refresh_failure: ProviderRejected | ProviderUnavailable,
    reason: SubscriptionUsageUnavailableReason,
    retryable: bool,
) -> None:
    """Retain the shared OAuth lifecycle while projecting its safe usage state."""
    integration = _integration()
    monkeypatch.setattr(
        f"{_SERVICE_MODULE}.ensure_runtime_tokens",
        AsyncMock(return_value=Failure(refresh_failure)),
    )
    service, _ = await _service(
        lambda _request: pytest.fail("provider must not be called"),
        integration=integration,
    )
    try:
        result = await service.read(
            integration_id=integration.id,
            workspace_id=integration.workspace_id,
            include_financial_details=True,
        )
    finally:
        await service.http_client.aclose()

    assert isinstance(result, Success)
    assert isinstance(result.value, SubscriptionUsageUnavailable)
    assert result.value.reason == reason
    assert result.value.retryable is retryable


async def test_one_unauthorized_response_forces_one_refresh_then_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Retry usage once with the token returned by the forced refresh operation."""
    integration = _integration()
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            assert request.headers["authorization"] == "Bearer access-1"
            return httpx.Response(401)
        assert request.headers["authorization"] == "Bearer refreshed-access-1"
        return httpx.Response(200, json=_payload())

    refreshed_integration = integration.model_copy(
        update={
            "secrets": ChatGPTOAuthSecrets(
                access_token="refreshed-access-1",
                refresh_token="refreshed-refresh-1",
                expires_at=datetime.datetime.now(datetime.UTC)
                + datetime.timedelta(hours=1),
            )
        }
    )
    ensure = AsyncMock(return_value=Success(integration))
    refresh = AsyncMock(return_value=Success(refreshed_integration))
    monkeypatch.setattr(f"{_SERVICE_MODULE}.ensure_runtime_tokens", ensure)
    monkeypatch.setattr(f"{_SERVICE_MODULE}.refresh_runtime_tokens", refresh)
    service, _ = await _service(handler, integration=integration)
    try:
        result = await service.read(
            integration_id=integration.id,
            workspace_id=integration.workspace_id,
            include_financial_details=True,
        )
    finally:
        await service.http_client.aclose()

    assert isinstance(result, Success)
    assert isinstance(result.value, SubscriptionUsageAvailable)
    assert calls == 2
    refresh.assert_awaited_once()


async def test_repeated_unauthorized_stops_after_the_forced_refresh_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A second usage 401 does not trigger a third provider call or refresh."""
    integration = _integration()
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(401)

    refresh = AsyncMock(return_value=Success(integration))
    monkeypatch.setattr(
        f"{_SERVICE_MODULE}.ensure_runtime_tokens",
        AsyncMock(return_value=Success(integration)),
    )
    monkeypatch.setattr(f"{_SERVICE_MODULE}.refresh_runtime_tokens", refresh)
    service, _ = await _service(handler, integration=integration)
    try:
        result = await service.read(
            integration_id=integration.id,
            workspace_id=integration.workspace_id,
            include_financial_details=True,
        )
    finally:
        await service.http_client.aclose()

    assert isinstance(result, Success)
    assert isinstance(result.value, SubscriptionUsageUnavailable)
    assert result.value.reason == SubscriptionUsageUnavailableReason.RECONNECT_REQUIRED
    assert calls == 2
    refresh.assert_awaited_once()


async def test_usage_permission_denied_does_not_mutate_integration_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Usage-specific 403 is independent from inference connection lifecycle state."""
    integration = _integration()
    repository: AsyncMock
    monkeypatch.setattr(
        f"{_SERVICE_MODULE}.ensure_runtime_tokens",
        AsyncMock(return_value=Success(integration)),
    )
    service, repository = await _service(
        lambda _request: httpx.Response(403),
        integration=integration,
    )
    try:
        result = await service.read(
            integration_id=integration.id,
            workspace_id=integration.workspace_id,
            include_financial_details=True,
        )
    finally:
        await service.http_client.aclose()

    assert isinstance(result, Success)
    assert isinstance(result.value, SubscriptionUsageUnavailable)
    assert result.value.reason == SubscriptionUsageUnavailableReason.PERMISSION_DENIED
    repository.update_by_id.assert_not_awaited()


async def test_unexpected_adapter_exception_propagates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep programming failures visible to normal server error handling."""
    integration = _integration()
    monkeypatch.setattr(
        f"{_SERVICE_MODULE}.ensure_runtime_tokens",
        AsyncMock(return_value=Success(integration)),
    )
    service, _ = await _service(
        lambda _request: httpx.Response(200, json=_payload()),
        integration=integration,
    )

    async def fail_get(*_args: object, **_kwargs: object) -> httpx.Response:
        raise RuntimeError("unexpected adapter defect")

    monkeypatch.setattr(service.http_client, "get", fail_get)
    try:
        with pytest.raises(RuntimeError, match="unexpected adapter defect"):
            await service.read(
                integration_id=integration.id,
                workspace_id=integration.workspace_id,
                include_financial_details=True,
            )
    finally:
        await service.http_client.aclose()
