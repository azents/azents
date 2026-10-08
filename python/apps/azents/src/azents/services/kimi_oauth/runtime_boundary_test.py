"""Injected transport lifetime regression for completed Kimi persistence."""

import datetime
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import httpx
from azcommon.result import Success

from azents.core.credentials import KimiOAuthConfig, KimiOAuthSecrets
from azents.core.enums import LLMProvider
from azents.core.kimi_oauth import KimiOAuthConnectionMethod
from azents.repos.kimi_oauth_runtime import KimiOAuthRuntimeRepository
from azents.repos.kimi_oauth_runtime_data import KimiOAuthRefreshTokens
from azents.repos.llm_provider_integration.data import LLMProviderIntegrationWithSecrets
from azents.testing.types import require_instance

from .client import KimiOAuthClient
from .runtime import refresh_runtime_tokens


async def test_refresh_closes_injected_transport_before_persistence() -> None:
    """Provider I/O cannot overlap the following completed persistence operation."""
    now = datetime.datetime.now(datetime.UTC)
    integration = LLMProviderIntegrationWithSecrets(
        id="i" * 32,
        workspace_id="w" * 32,
        provider=LLMProvider.KIMI_OAUTH,
        name="Kimi boundary fixture",
        enabled=True,
        catalog_configuration_version=1,
        created_at=now,
        updated_at=now,
        secrets=KimiOAuthSecrets(
            access_token="old-access",
            refresh_token="old-refresh",
            device_id="device-1",
            expires_at=now,
        ),
        config=KimiOAuthConfig(
            connection_method=KimiOAuthConnectionMethod.DEVICE.value,
            status="connected",
            connected_at=now,
            last_refreshed_at=now,
            last_failed_at=None,
            last_failure_reason=None,
        ),
    )
    events: list[str] = []

    async def persist_success(
        *,
        integration: LLMProviderIntegrationWithSecrets,
        tokens: KimiOAuthRefreshTokens,
    ) -> Success[LLMProviderIntegrationWithSecrets]:
        assert events == ["open", "refresh", "closed"]
        assert isinstance(integration.secrets, KimiOAuthSecrets)
        events.append("persist")
        return Success(
            integration.model_copy(
                update={
                    "secrets": integration.secrets.model_copy(
                        update={
                            "access_token": tokens.access_token,
                            "refresh_token": tokens.refresh_token,
                            "expires_at": tokens.expires_at,
                        }
                    )
                }
            )
        )

    persistence = MagicMock(spec=KimiOAuthRuntimeRepository)
    persistence.persist_success = AsyncMock(side_effect=persist_success)

    def handle(request: httpx.Request) -> httpx.Response:
        assert events == ["open"]
        events.append("refresh")
        return httpx.Response(
            200,
            json={
                "access_token": "new-access",
                "refresh_token": "new-refresh",
                "expires_in": 3600,
            },
        )

    @asynccontextmanager
    async def client_factory() -> AsyncIterator[KimiOAuthClient]:
        events.append("open")
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            yield KimiOAuthClient(client)
        events.append("closed")

    result = await refresh_runtime_tokens(
        integration=integration,
        persistence_repository=require_instance(
            persistence, KimiOAuthRuntimeRepository
        ),
        client_factory=client_factory,
    )
    assert isinstance(result, Success)
    assert isinstance(result.value.secrets, KimiOAuthSecrets)
    assert result.value.secrets.refresh_token == "new-refresh"
    assert events == ["open", "refresh", "closed", "persist"]
