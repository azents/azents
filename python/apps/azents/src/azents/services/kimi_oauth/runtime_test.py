"""Kimi OAuth runtime refresh tests."""

import asyncio
import datetime
import uuid
from typing import cast
from unittest.mock import AsyncMock

import pytest
from azcommon.result import Failure, Result, Success
from cryptography.fernet import Fernet
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from azents.core.credentials import KimiOAuthConfig, KimiOAuthSecrets
from azents.core.crypto import CredentialCipher
from azents.core.enums import LLMProvider
from azents.core.kimi_oauth import (
    KimiOAuthConnectionMethod,
    KimiOAuthConnectionStatus,
)
from azents.rdb.session import SessionManager
from azents.repos.llm_provider_integration import LLMProviderIntegrationRepository
from azents.repos.llm_provider_integration.data import LLMProviderIntegrationCreate
from azents.repos.workspace import WorkspaceRepository
from azents.repos.workspace.data import WorkspaceCreate

from .client import KimiOAuthClient
from .data import ProviderRejected, ProviderUnavailable, TokenSet
from .runtime import ensure_runtime_tokens, refresh_runtime_tokens

_TEST_KEY = Fernet.generate_key().decode()


class _SessionManager:
    """Expose single test DB session as context manager."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def __call__(self) -> "_SessionManager":
        return self

    async def __aenter__(self) -> AsyncSession:
        return self._session

    async def __aexit__(self, *_args: object) -> None:
        return None


async def _create_workspace(session: AsyncSession) -> str:
    """Create workspace for tests."""
    suffix = uuid.uuid4().hex[:12]
    handle = f"kimi-runtime-{suffix}"
    repo = WorkspaceRepository()
    result = await repo.create(
        session, WorkspaceCreate(name=f"Kimi Runtime {suffix}", handle=handle)
    )
    assert isinstance(result, Success)
    workspace_id = await repo.resolve_id(session, handle)
    assert workspace_id is not None
    return workspace_id


async def _create_integration(
    session: AsyncSession,
    *,
    expires_at: datetime.datetime,
) -> tuple[LLMProviderIntegrationRepository, str]:
    """Create Kimi OAuth integration for tests."""
    repo = LLMProviderIntegrationRepository(CredentialCipher(_TEST_KEY))
    workspace_id = await _create_workspace(session)
    integration = await repo.create(
        session,
        LLMProviderIntegrationCreate(
            workspace_id=workspace_id,
            provider=LLMProvider.KIMI_OAUTH,
            name="Kimi Grok OAuth",
            secrets=KimiOAuthSecrets(
                access_token="old-access-token",
                refresh_token="old-refresh-token",
                expires_at=expires_at,
                device_id="device-id-123",
            ),
            config=KimiOAuthConfig(
                connection_method=KimiOAuthConnectionMethod.DEVICE.value,
                status=KimiOAuthConnectionStatus.CONNECTED.value,
                connected_at=datetime.datetime.now(datetime.UTC),
                last_refreshed_at=datetime.datetime.now(datetime.UTC),
                last_failed_at=None,
                last_failure_reason=None,
            ),
        ),
    )
    return repo, integration.id


async def _reconnect_integration(
    session: AsyncSession,
    repo: LLMProviderIntegrationRepository,
    integration_id: str,
) -> None:
    """Replace an integration with credentials from a completed reconnect."""
    now = datetime.datetime.now(datetime.UTC)
    result = await repo.update_by_id(
        session,
        integration_id,
        {
            "secrets": KimiOAuthSecrets(
                access_token="reconnected-access-token",
                refresh_token="reconnected-refresh-token",
                expires_at=now + datetime.timedelta(hours=2),
                device_id="reconnected-device-id",
            ),
            "config": KimiOAuthConfig(
                connection_method=KimiOAuthConnectionMethod.DEVICE.value,
                status=KimiOAuthConnectionStatus.CONNECTED.value,
                connected_at=now,
                last_refreshed_at=now,
                last_failed_at=None,
                last_failure_reason=None,
            ),
        },
    )
    assert isinstance(result, Success)


async def _rotate_integration(
    session: AsyncSession,
    repo: LLMProviderIntegrationRepository,
    integration_id: str,
) -> None:
    """Store credentials produced by a concurrent successful refresh."""
    current = await repo.get_by_id_with_secrets(session, integration_id)
    assert current is not None
    assert isinstance(current.config, KimiOAuthConfig)
    assert isinstance(current.secrets, KimiOAuthSecrets)
    now = datetime.datetime.now(datetime.UTC)
    result = await repo.update_by_id(
        session,
        integration_id,
        {
            "secrets": KimiOAuthSecrets(
                access_token="winning-access-token",
                refresh_token="winning-refresh-token",
                expires_at=now + datetime.timedelta(hours=2),
                device_id=current.secrets.device_id,
            ),
            "config": KimiOAuthConfig(
                connection_method=current.config.connection_method,
                status=KimiOAuthConnectionStatus.CONNECTED.value,
                connected_at=current.config.connected_at,
                last_refreshed_at=now,
                last_failed_at=None,
                last_failure_reason=None,
            ),
        },
    )
    assert isinstance(result, Success)


async def _mark_refresh_failure(
    session: AsyncSession,
    repo: LLMProviderIntegrationRepository,
    integration_id: str,
    *,
    status: KimiOAuthConnectionStatus,
    reason: str,
) -> None:
    """Store config-only failure metadata without replacing credentials."""
    current = await repo.get_by_id_with_secrets(session, integration_id)
    assert current is not None
    assert isinstance(current.config, KimiOAuthConfig)
    result = await repo.update_by_id(
        session,
        integration_id,
        {
            "config": KimiOAuthConfig(
                connection_method=current.config.connection_method,
                status=status.value,
                connected_at=current.config.connected_at,
                last_refreshed_at=current.config.last_refreshed_at,
                last_failed_at=datetime.datetime.now(datetime.UTC),
                last_failure_reason=reason,
            )
        },
    )
    assert isinstance(result, Success)


class TestEnsureRuntimeTokens:
    """ensure_runtime_tokens tests."""

    async def test_fresh_token_returns_existing_integration(
        self, rdb_session: AsyncSession
    ) -> None:
        """Sufficiently fresh token is not refreshed."""
        expires_at = datetime.datetime.now(datetime.UTC) + datetime.timedelta(hours=2)
        repo, integration_id = await _create_integration(
            rdb_session,
            expires_at=expires_at,
        )
        integration = await repo.get_by_id_with_secrets(rdb_session, integration_id)
        assert integration is not None

        result = await ensure_runtime_tokens(
            integration=integration,
            integration_repository=repo,
            session_manager=cast(
                SessionManager[AsyncSession], _SessionManager(rdb_session)
            ),
        )

        assert isinstance(result, Success)
        assert result.value.id == integration_id

    async def test_more_than_five_minutes_remaining_skips_refresh(
        self, rdb_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A token outside the five-minute window remains unchanged."""
        expires_at = datetime.datetime.now(datetime.UTC) + datetime.timedelta(
            minutes=10
        )
        repo, integration_id = await _create_integration(
            rdb_session,
            expires_at=expires_at,
        )
        integration = await repo.get_by_id_with_secrets(rdb_session, integration_id)
        assert integration is not None
        refresh = AsyncMock()
        monkeypatch.setattr(
            "azents.services.kimi_oauth.runtime.refresh_runtime_tokens", refresh
        )

        result = await ensure_runtime_tokens(
            integration=integration,
            integration_repository=repo,
            session_manager=cast(
                SessionManager[AsyncSession], _SessionManager(rdb_session)
            ),
        )

        assert isinstance(result, Success)
        assert result.value.id == integration.id
        refresh.assert_not_awaited()

    async def test_within_five_minutes_uses_shared_refresh_path(
        self, rdb_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A token inside the five-minute window delegates to forced refresh."""
        expires_at = datetime.datetime.now(datetime.UTC) + datetime.timedelta(minutes=4)
        repo, integration_id = await _create_integration(
            rdb_session,
            expires_at=expires_at,
        )
        integration = await repo.get_by_id_with_secrets(rdb_session, integration_id)
        assert integration is not None
        refresh = AsyncMock(return_value=Success(integration))
        monkeypatch.setattr(
            "azents.services.kimi_oauth.runtime.refresh_runtime_tokens", refresh
        )

        result = await ensure_runtime_tokens(
            integration=integration,
            integration_repository=repo,
            session_manager=cast(
                SessionManager[AsyncSession], _SessionManager(rdb_session)
            ),
        )

        assert isinstance(result, Success)
        refresh.assert_awaited_once()

    async def test_forced_refresh_rotates_a_fresh_rejected_token(
        self, rdb_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Refresh a still-fresh token after Imagine rejects it with 401."""
        expires_at = datetime.datetime.now(datetime.UTC) + datetime.timedelta(hours=2)
        repo, integration_id = await _create_integration(
            rdb_session,
            expires_at=expires_at,
        )
        integration = await repo.get_by_id_with_secrets(rdb_session, integration_id)
        assert integration is not None

        async def fake_refresh(
            _self: KimiOAuthClient,
            *,
            refresh_token: str,
            device_id: str,
            connection_method: KimiOAuthConnectionMethod,
        ) -> Result[
            TokenSet,
            ProviderRejected | ProviderUnavailable,
        ]:
            assert refresh_token == "old-refresh-token"
            return Success(
                TokenSet(
                    access_token="forced-access-token",
                    refresh_token="forced-refresh-token",
                    expires_at=datetime.datetime.now(datetime.UTC)
                    + datetime.timedelta(hours=1),
                    connection_method=connection_method,
                )
            )

        monkeypatch.setattr(KimiOAuthClient, "refresh_tokens", fake_refresh)

        result = await refresh_runtime_tokens(
            integration=integration,
            integration_repository=repo,
            session_manager=cast(
                SessionManager[AsyncSession], _SessionManager(rdb_session)
            ),
        )

        assert isinstance(result, Success)
        assert isinstance(result.value.secrets, KimiOAuthSecrets)
        assert result.value.secrets.access_token == "forced-access-token"

    async def test_refresh_success_preserves_concurrent_reconnect(
        self, rdb_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A stale refresh success does not replace newer reconnect credentials."""
        expires_at = datetime.datetime.now(datetime.UTC) + datetime.timedelta(minutes=1)
        repo, integration_id = await _create_integration(
            rdb_session,
            expires_at=expires_at,
        )
        integration = await repo.get_by_id_with_secrets(rdb_session, integration_id)
        assert integration is not None

        async def refresh_after_reconnect(
            _self: KimiOAuthClient,
            *,
            refresh_token: str,
            device_id: str,
            connection_method: KimiOAuthConnectionMethod,
        ) -> Result[TokenSet, ProviderRejected | ProviderUnavailable]:
            assert refresh_token == "old-refresh-token"
            await _reconnect_integration(rdb_session, repo, integration_id)
            return Success(
                TokenSet(
                    access_token="stale-access-token",
                    refresh_token="stale-refresh-token",
                    expires_at=datetime.datetime.now(datetime.UTC)
                    + datetime.timedelta(hours=1),
                    connection_method=connection_method,
                )
            )

        monkeypatch.setattr(KimiOAuthClient, "refresh_tokens", refresh_after_reconnect)

        result = await ensure_runtime_tokens(
            integration=integration,
            integration_repository=repo,
            session_manager=cast(
                SessionManager[AsyncSession], _SessionManager(rdb_session)
            ),
        )

        assert isinstance(result, Success)
        assert isinstance(result.value.secrets, KimiOAuthSecrets)
        assert result.value.secrets.access_token == "reconnected-access-token"
        assert result.value.secrets.refresh_token == "reconnected-refresh-token"
        assert result.value.secrets.device_id == "reconnected-device-id"

    async def test_refresh_failure_preserves_concurrent_reconnect(
        self, rdb_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A stale failure does not mark newer reconnect credentials unusable."""
        expires_at = datetime.datetime.now(datetime.UTC) + datetime.timedelta(minutes=1)
        repo, integration_id = await _create_integration(
            rdb_session,
            expires_at=expires_at,
        )
        integration = await repo.get_by_id_with_secrets(rdb_session, integration_id)
        assert integration is not None

        async def fail_after_reconnect(
            _self: KimiOAuthClient,
            *,
            refresh_token: str,
            device_id: str,
            connection_method: KimiOAuthConnectionMethod,
        ) -> Result[TokenSet, ProviderRejected | ProviderUnavailable]:
            await _reconnect_integration(rdb_session, repo, integration_id)
            return Failure(ProviderRejected(reason="stale credentials rejected"))

        monkeypatch.setattr(KimiOAuthClient, "refresh_tokens", fail_after_reconnect)

        result = await ensure_runtime_tokens(
            integration=integration,
            integration_repository=repo,
            session_manager=cast(
                SessionManager[AsyncSession], _SessionManager(rdb_session)
            ),
        )

        assert isinstance(result, Success)
        assert isinstance(result.value.config, KimiOAuthConfig)
        assert isinstance(result.value.secrets, KimiOAuthSecrets)
        assert result.value.config.status == KimiOAuthConnectionStatus.CONNECTED.value
        assert result.value.config.last_failure_reason is None
        assert result.value.secrets.access_token == "reconnected-access-token"

    async def test_success_replaces_concurrent_config_only_failure(
        self, rdb_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A valid refresh success recovers a config-only concurrent failure."""
        expires_at = datetime.datetime.now(datetime.UTC) + datetime.timedelta(minutes=1)
        repo, integration_id = await _create_integration(
            rdb_session,
            expires_at=expires_at,
        )
        integration = await repo.get_by_id_with_secrets(rdb_session, integration_id)
        assert integration is not None

        async def succeed_after_failure(
            _self: KimiOAuthClient,
            *,
            refresh_token: str,
            device_id: str,
            connection_method: KimiOAuthConnectionMethod,
        ) -> Result[TokenSet, ProviderRejected | ProviderUnavailable]:
            await _mark_refresh_failure(
                rdb_session,
                repo,
                integration_id,
                status=KimiOAuthConnectionStatus.TEMPORARILY_UNAVAILABLE,
                reason="first refresh failed",
            )
            return Success(
                TokenSet(
                    access_token="recovered-access-token",
                    refresh_token="recovered-refresh-token",
                    expires_at=datetime.datetime.now(datetime.UTC)
                    + datetime.timedelta(hours=1),
                    connection_method=connection_method,
                )
            )

        monkeypatch.setattr(KimiOAuthClient, "refresh_tokens", succeed_after_failure)

        result = await ensure_runtime_tokens(
            integration=integration,
            integration_repository=repo,
            session_manager=cast(
                SessionManager[AsyncSession], _SessionManager(rdb_session)
            ),
        )

        assert isinstance(result, Success)
        assert isinstance(result.value.config, KimiOAuthConfig)
        assert isinstance(result.value.secrets, KimiOAuthSecrets)
        assert result.value.config.status == KimiOAuthConnectionStatus.CONNECTED.value
        assert result.value.config.last_failure_reason is None
        assert result.value.secrets.access_token == "recovered-access-token"

    async def test_failure_preserves_concurrent_refresh_success(
        self, rdb_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A stale failure preserves credentials rotated by another refresh."""
        expires_at = datetime.datetime.now(datetime.UTC) + datetime.timedelta(minutes=1)
        repo, integration_id = await _create_integration(
            rdb_session,
            expires_at=expires_at,
        )
        integration = await repo.get_by_id_with_secrets(rdb_session, integration_id)
        assert integration is not None

        async def fail_after_success(
            _self: KimiOAuthClient,
            *,
            refresh_token: str,
            device_id: str,
            connection_method: KimiOAuthConnectionMethod,
        ) -> Result[TokenSet, ProviderRejected | ProviderUnavailable]:
            await _rotate_integration(rdb_session, repo, integration_id)
            return Failure(ProviderUnavailable(reason="stale refresh timed out"))

        monkeypatch.setattr(KimiOAuthClient, "refresh_tokens", fail_after_success)

        result = await ensure_runtime_tokens(
            integration=integration,
            integration_repository=repo,
            session_manager=cast(
                SessionManager[AsyncSession], _SessionManager(rdb_session)
            ),
        )

        assert isinstance(result, Success)
        assert isinstance(result.value.config, KimiOAuthConfig)
        assert isinstance(result.value.secrets, KimiOAuthSecrets)
        assert result.value.config.status == KimiOAuthConnectionStatus.CONNECTED.value
        assert result.value.config.last_failure_reason is None
        assert result.value.secrets.access_token == "winning-access-token"

    async def test_second_concurrent_failure_remains_failure(
        self, rdb_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Config-only changes never convert another refresh failure to success."""
        expires_at = datetime.datetime.now(datetime.UTC) + datetime.timedelta(minutes=1)
        repo, integration_id = await _create_integration(
            rdb_session,
            expires_at=expires_at,
        )
        integration = await repo.get_by_id_with_secrets(rdb_session, integration_id)
        assert integration is not None

        async def fail_after_failure(
            _self: KimiOAuthClient,
            *,
            refresh_token: str,
            device_id: str,
            connection_method: KimiOAuthConnectionMethod,
        ) -> Result[TokenSet, ProviderRejected | ProviderUnavailable]:
            await _mark_refresh_failure(
                rdb_session,
                repo,
                integration_id,
                status=KimiOAuthConnectionStatus.TEMPORARILY_UNAVAILABLE,
                reason="first refresh failed",
            )
            return Failure(ProviderUnavailable(reason="second refresh failed"))

        monkeypatch.setattr(KimiOAuthClient, "refresh_tokens", fail_after_failure)

        result = await ensure_runtime_tokens(
            integration=integration,
            integration_repository=repo,
            session_manager=cast(
                SessionManager[AsyncSession], _SessionManager(rdb_session)
            ),
        )
        updated = await repo.get_by_id_with_secrets(rdb_session, integration_id)

        assert isinstance(result, Failure)
        assert result.error.reason == "second refresh failed"
        assert updated is not None
        assert isinstance(updated.config, KimiOAuthConfig)
        assert (
            updated.config.status
            == KimiOAuthConnectionStatus.TEMPORARILY_UNAVAILABLE.value
        )
        assert updated.config.last_failure_reason == "second refresh failed"

    async def test_second_concurrent_success_preserves_first_rotation(
        self, rdb_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A stale success does not overwrite the first committed rotation."""
        expires_at = datetime.datetime.now(datetime.UTC) + datetime.timedelta(minutes=1)
        repo, integration_id = await _create_integration(
            rdb_session,
            expires_at=expires_at,
        )
        integration = await repo.get_by_id_with_secrets(rdb_session, integration_id)
        assert integration is not None

        async def succeed_after_success(
            _self: KimiOAuthClient,
            *,
            refresh_token: str,
            device_id: str,
            connection_method: KimiOAuthConnectionMethod,
        ) -> Result[TokenSet, ProviderRejected | ProviderUnavailable]:
            await _rotate_integration(rdb_session, repo, integration_id)
            return Success(
                TokenSet(
                    access_token="stale-access-token",
                    refresh_token="stale-refresh-token",
                    expires_at=datetime.datetime.now(datetime.UTC)
                    + datetime.timedelta(hours=1),
                    connection_method=connection_method,
                )
            )

        monkeypatch.setattr(KimiOAuthClient, "refresh_tokens", succeed_after_success)

        result = await ensure_runtime_tokens(
            integration=integration,
            integration_repository=repo,
            session_manager=cast(
                SessionManager[AsyncSession], _SessionManager(rdb_session)
            ),
        )

        assert isinstance(result, Success)
        assert isinstance(result.value.secrets, KimiOAuthSecrets)
        assert result.value.secrets.access_token == "winning-access-token"
        assert result.value.secrets.refresh_token == "winning-refresh-token"

    async def test_refresh_persistence_waits_for_existing_row_lock(
        self,
        rdb_engine: AsyncEngine,
        latest_db_schema: None,
    ) -> None:
        """Credential persistence serializes through the integration row lock."""
        session_factory = async_sessionmaker(rdb_engine, expire_on_commit=False)
        async with session_factory() as setup_session:
            repo, integration_id = await _create_integration(
                setup_session,
                expires_at=datetime.datetime.now(datetime.UTC)
                + datetime.timedelta(minutes=1),
            )
            await setup_session.commit()

        async with (
            session_factory() as lock_session,
            session_factory() as waiting_session,
        ):
            lock_transaction = await lock_session.begin()
            locked = await repo.get_by_id_with_secrets_for_update(
                lock_session, integration_id
            )
            assert locked is not None
            waiting_task = asyncio.create_task(
                repo.get_by_id_with_secrets_for_update(
                    waiting_session,
                    integration_id,
                )
            )
            try:
                with pytest.raises(asyncio.TimeoutError):
                    await asyncio.wait_for(asyncio.shield(waiting_task), timeout=0.2)

                await lock_transaction.commit()
                observed = await asyncio.wait_for(waiting_task, timeout=2)
                await waiting_session.commit()

                assert observed is not None
                assert observed.id == integration_id
            finally:
                if lock_transaction.is_active:
                    await lock_transaction.rollback()
                if not waiting_task.done():
                    waiting_task.cancel()
                    with pytest.raises(asyncio.CancelledError):
                        await waiting_task

    async def test_near_expiry_refresh_persists_rotated_tokens(
        self, rdb_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Nearly expired token refreshes and updates encrypted secrets."""
        expires_at = datetime.datetime.now(datetime.UTC) + datetime.timedelta(minutes=1)
        repo, integration_id = await _create_integration(
            rdb_session,
            expires_at=expires_at,
        )
        integration = await repo.get_by_id_with_secrets(rdb_session, integration_id)
        assert integration is not None

        async def fake_refresh(
            _self: KimiOAuthClient,
            *,
            refresh_token: str,
            device_id: str,
            connection_method: KimiOAuthConnectionMethod,
        ) -> Result[
            TokenSet,
            ProviderRejected | ProviderUnavailable,
        ]:
            assert refresh_token == "old-refresh-token"
            return Success(
                TokenSet(
                    access_token="new-access-token",
                    refresh_token="new-refresh-token",
                    expires_at=datetime.datetime.now(datetime.UTC)
                    + datetime.timedelta(hours=1),
                    connection_method=connection_method,
                )
            )

        monkeypatch.setattr(KimiOAuthClient, "refresh_tokens", fake_refresh)

        result = await ensure_runtime_tokens(
            integration=integration,
            integration_repository=repo,
            session_manager=cast(
                SessionManager[AsyncSession], _SessionManager(rdb_session)
            ),
        )

        assert isinstance(result, Success)
        assert isinstance(result.value.secrets, KimiOAuthSecrets)
        assert result.value.secrets.access_token == "new-access-token"
        assert result.value.secrets.refresh_token == "new-refresh-token"

    async def test_permanent_rejection_marks_refresh_required(
        self, rdb_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A permanent refresh rejection requires reconnecting the integration."""
        expires_at = datetime.datetime.now(datetime.UTC) + datetime.timedelta(minutes=1)
        repo, integration_id = await _create_integration(
            rdb_session,
            expires_at=expires_at,
        )
        integration = await repo.get_by_id_with_secrets(rdb_session, integration_id)
        assert integration is not None

        async def fake_refresh(
            _self: KimiOAuthClient,
            *,
            refresh_token: str,
            device_id: str,
            connection_method: KimiOAuthConnectionMethod,
        ) -> Result[TokenSet, ProviderRejected | ProviderUnavailable]:
            assert device_id == "device-id-123"
            return Failure(ProviderRejected(reason="credentials rejected"))

        monkeypatch.setattr(KimiOAuthClient, "refresh_tokens", fake_refresh)

        result = await ensure_runtime_tokens(
            integration=integration,
            integration_repository=repo,
            session_manager=cast(
                SessionManager[AsyncSession], _SessionManager(rdb_session)
            ),
        )
        updated = await repo.get_by_id(rdb_session, integration_id)

        assert isinstance(result, Failure)
        assert updated is not None
        assert isinstance(updated.config, KimiOAuthConfig)
        assert updated.config.status == KimiOAuthConnectionStatus.REFRESH_REQUIRED.value
        assert updated.config.last_failure_reason == "credentials rejected"

    async def test_temporary_failure_remains_retryable(
        self, rdb_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Transient failure state retries refresh on next runtime preflight."""
        expires_at = datetime.datetime.now(datetime.UTC) + datetime.timedelta(minutes=1)
        repo, integration_id = await _create_integration(
            rdb_session,
            expires_at=expires_at,
        )
        integration = await repo.get_by_id_with_secrets(rdb_session, integration_id)
        assert integration is not None

        async def fail_refresh(
            _self: KimiOAuthClient,
            *,
            refresh_token: str,
            device_id: str,
            connection_method: KimiOAuthConnectionMethod,
        ) -> Result[
            TokenSet,
            ProviderRejected | ProviderUnavailable,
        ]:
            return Failure(ProviderUnavailable(reason="rate limited"))

        monkeypatch.setattr(KimiOAuthClient, "refresh_tokens", fail_refresh)
        first = await ensure_runtime_tokens(
            integration=integration,
            integration_repository=repo,
            session_manager=cast(
                SessionManager[AsyncSession], _SessionManager(rdb_session)
            ),
        )
        after_failure = await repo.get_by_id_with_secrets(rdb_session, integration_id)
        assert isinstance(first, Failure)
        assert after_failure is not None
        assert isinstance(after_failure.config, KimiOAuthConfig)
        assert (
            after_failure.config.status
            == KimiOAuthConnectionStatus.TEMPORARILY_UNAVAILABLE.value
        )

        async def success_refresh(
            _self: KimiOAuthClient,
            *,
            refresh_token: str,
            device_id: str,
            connection_method: KimiOAuthConnectionMethod,
        ) -> Result[
            TokenSet,
            ProviderRejected | ProviderUnavailable,
        ]:
            return Success(
                TokenSet(
                    access_token="recovered-access-token",
                    refresh_token="recovered-refresh-token",
                    expires_at=datetime.datetime.now(datetime.UTC)
                    + datetime.timedelta(hours=1),
                    connection_method=connection_method,
                )
            )

        monkeypatch.setattr(KimiOAuthClient, "refresh_tokens", success_refresh)
        second = await ensure_runtime_tokens(
            integration=after_failure,
            integration_repository=repo,
            session_manager=cast(
                SessionManager[AsyncSession], _SessionManager(rdb_session)
            ),
        )

        assert isinstance(second, Success)
        assert isinstance(second.value.secrets, KimiOAuthSecrets)
        assert second.value.secrets.access_token == "recovered-access-token"
