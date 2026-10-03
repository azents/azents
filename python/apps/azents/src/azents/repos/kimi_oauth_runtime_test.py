"""Genuine PostgreSQL Kimi persistence and closed HTTP boundary regression."""

import asyncio
import datetime
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import NamedTuple, Never

import httpx
import pytest
from azcommon.result import Success
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.credentials import KimiOAuthConfig, KimiOAuthSecrets
from azents.core.crypto import CredentialCipher
from azents.core.kimi_oauth import KimiOAuthConnectionMethod, KimiOAuthConnectionStatus
from azents.rdb.session import SessionManager
from azents.repos.kimi_oauth_runtime import KimiOAuthRuntimeRepository
from azents.repos.kimi_oauth_runtime_data import KimiOAuthRefreshTokens
from azents.repos.llm_provider_integration import LLMProviderIntegrationRepository
from azents.repos.llm_provider_integration.data import (
    LLMProviderIntegrationUpdate,
    LLMProviderIntegrationWithSecrets,
)
from azents.repos.worker_executor_read_test import _Boundary
from azents.services.kimi_oauth import runtime as runtime_module
from azents.services.kimi_oauth.client import KimiOAuthClient
from azents.services.kimi_oauth.data import TokenSet
from azents.services.kimi_oauth.runtime_test import _TEST_KEY, _create_integration


class _Fixture(NamedTuple):
    boundary: _Boundary
    query: LLMProviderIntegrationRepository
    original: LLMProviderIntegrationWithSecrets
    repository: KimiOAuthRuntimeRepository


async def _fixture(manager: SessionManager[AsyncSession]) -> _Fixture:
    async with manager() as session:
        query, integration_id = await _create_integration(
            session,
            expires_at=datetime.datetime.now(datetime.UTC)
            - datetime.timedelta(minutes=1),
        )
        original = await query.get_by_id_with_secrets(session, integration_id)
        assert original is not None
    boundary = _Boundary(manager)
    return _Fixture(
        boundary,
        query,
        original,
        KimiOAuthRuntimeRepository(
            session_manager=boundary.session_manager,
            integration_repository=query,
        ),
    )


def _tokens() -> KimiOAuthRefreshTokens:
    return KimiOAuthRefreshTokens(
        access_token="test-new-access",
        refresh_token="test-new-refresh",
        expires_at=datetime.datetime.now(datetime.UTC) + datetime.timedelta(hours=2),
    )


async def test_integration_capture_finishes_its_database_transaction(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """The added complete read exposes detached data, not a live transaction."""
    fixture = await _fixture(rdb_session_manager)
    captured = await fixture.repository.load_integration(
        integration_id=fixture.original.id
    )
    assert captured == fixture.original
    fixture.boundary.closed()
    assert len(fixture.boundary.opened) == 1
    assert await fixture.repository.load_integration(integration_id="0" * 32) is None
    fixture.boundary.closed()


async def test_http_precedes_persistence_and_returns_detached_credentials(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    fixture = await _fixture(rdb_session_manager)
    calls = 0

    class Client(KimiOAuthClient):
        def __init__(self, http_client: httpx.AsyncClient) -> None:
            fixture.boundary.closed()
            super().__init__(http_client)

        async def refresh_tokens(
            self,
            *,
            refresh_token: str,
            device_id: str,
            connection_method: KimiOAuthConnectionMethod,
        ) -> Success[TokenSet]:
            nonlocal calls
            fixture.boundary.closed()
            assert not fixture.boundary.opened
            calls += 1
            return Success(
                TokenSet(
                    access_token="test-new-access",
                    refresh_token="test-new-refresh",
                    expires_at=_tokens().expires_at,
                    connection_method=KimiOAuthConnectionMethod.DEVICE,
                )
            )

    def unexpected_http(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("The controlled Kimi refresh must not perform HTTP")

    @asynccontextmanager
    async def client_factory() -> AsyncIterator[KimiOAuthClient]:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(unexpected_http), timeout=20.0
        ) as http_client:
            yield Client(http_client)

    result = await runtime_module.ensure_runtime_tokens(
        integration=fixture.original,
        persistence_repository=fixture.repository,
        client_factory=client_factory,
    )
    assert isinstance(result, Success)
    assert isinstance(result.value.secrets, KimiOAuthSecrets)
    assert result.value.secrets.access_token == "test-new-access"
    assert (
        result.value.catalog_configuration_version
        == fixture.original.catalog_configuration_version
    )
    assert calls == 1 and len(fixture.boundary.opened) == 1
    fixture.boundary.closed()


async def test_original_secrets_only_fence_preserves_config_only_change_behavior(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    fixture = await _fixture(rdb_session_manager)
    assert isinstance(fixture.original.config, KimiOAuthConfig)
    original_config = fixture.original.config
    async with rdb_session_manager() as session:
        await fixture.query.update_runtime_state_by_id(
            session,
            fixture.original.id,
            {
                "config": original_config.model_copy(
                    update={"status": KimiOAuthConnectionStatus.REFRESH_REQUIRED.value}
                ),
            },
        )
    result = await fixture.repository.persist_success(
        integration=fixture.original, tokens=_tokens()
    )
    assert isinstance(result, Success)
    assert isinstance(result.value.config, KimiOAuthConfig)
    assert result.value.config.status == KimiOAuthConnectionStatus.CONNECTED.value
    assert result.value.config.connected_at == original_config.connected_at
    fixture.boundary.closed()


async def test_changed_secrets_win_over_success_and_failure_without_new_status_fence(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    fixture = await _fixture(rdb_session_manager)
    assert isinstance(fixture.original.secrets, KimiOAuthSecrets)
    changed = fixture.original.secrets.model_copy(
        update={"access_token": "concurrent-token"}
    )
    async with rdb_session_manager() as session:
        await fixture.query.update_runtime_state_by_id(
            session, fixture.original.id, {"secrets": changed}
        )
    success = await fixture.repository.persist_success(
        integration=fixture.original, tokens=_tokens()
    )
    failure = await fixture.repository.persist_failure(
        integration=fixture.original,
        status=KimiOAuthConnectionStatus.REFRESH_REQUIRED,
        reason="test rejected",
    )
    assert isinstance(success, Success)
    assert success.value.secrets == changed
    assert failure is not None and failure.secrets == changed
    fixture.boundary.closed()


@pytest.mark.parametrize("operation", ["success", "failure"])
@pytest.mark.parametrize("failure", ["error", "cancel"])
async def test_actual_partial_refresh_write_rolls_back_on_error_or_cancel(
    rdb_session_manager: SessionManager[AsyncSession],
    operation: str,
    failure: str,
) -> None:
    fixture = await _fixture(rdb_session_manager)

    class FailingQuery(LLMProviderIntegrationRepository):
        async def update_runtime_state_by_id(
            self,
            session: AsyncSession,
            integration_id: str,
            update: LLMProviderIntegrationUpdate,
        ) -> Never:
            result = await super().update_runtime_state_by_id(
                session, integration_id, update
            )
            assert isinstance(result, Success)
            if failure == "cancel":
                raise asyncio.CancelledError()
            raise ValueError("Injected failure after actual refresh update.")

    query = FailingQuery(CredentialCipher(_TEST_KEY))
    repository = KimiOAuthRuntimeRepository(
        session_manager=fixture.boundary.session_manager, integration_repository=query
    )
    with pytest.raises(asyncio.CancelledError if failure == "cancel" else ValueError):
        if operation == "success":
            await repository.persist_success(
                integration=fixture.original, tokens=_tokens()
            )
        else:
            await repository.persist_failure(
                integration=fixture.original,
                status=KimiOAuthConnectionStatus.TEMPORARILY_UNAVAILABLE,
                reason="test unavailable",
            )
    fixture.boundary.closed()
    async with rdb_session_manager() as session:
        latest = await fixture.query.get_by_id_with_secrets(
            session, fixture.original.id
        )
    assert latest == fixture.original
