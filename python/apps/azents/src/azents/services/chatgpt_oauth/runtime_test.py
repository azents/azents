"""ChatGPT OAuth runtime refresh tests."""

import datetime
import uuid
from typing import cast

import pytest
from azcommon.result import Failure, Result, Success
from cryptography.fernet import Fernet
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.chatgpt_oauth import (
    ChatGPTOAuthConnectionMethod,
    ChatGPTOAuthConnectionStatus,
)
from azents.core.credentials import ChatGPTOAuthConfig, ChatGPTOAuthSecrets
from azents.core.crypto import CredentialCipher
from azents.core.enums import LLMProvider
from azents.rdb.session import SessionManager
from azents.repos.llm_provider_integration import LLMProviderIntegrationRepository
from azents.repos.llm_provider_integration.data import LLMProviderIntegrationCreate
from azents.repos.workspace import WorkspaceRepository
from azents.repos.workspace.data import WorkspaceCreate

from .client import ChatGPTOAuthClient
from .data import ProviderRejected, ProviderUnavailable, TokenSet
from .runtime import ensure_runtime_tokens

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
    handle = f"cgpt-runtime-{suffix}"
    repo = WorkspaceRepository()
    result = await repo.create(
        session, WorkspaceCreate(name=f"ChatGPT Runtime {suffix}", handle=handle)
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
    """Create ChatGPT OAuth integration for tests."""
    repo = LLMProviderIntegrationRepository(CredentialCipher(_TEST_KEY))
    workspace_id = await _create_workspace(session)
    integration = await repo.create(
        session,
        LLMProviderIntegrationCreate(
            workspace_id=workspace_id,
            provider=LLMProvider.CHATGPT_OAUTH,
            name="ChatGPT Subscription",
            secrets=ChatGPTOAuthSecrets(
                access_token="old-access-token",
                refresh_token="old-refresh-token",
                expires_at=expires_at,
            ),
            config=ChatGPTOAuthConfig(
                connection_method=ChatGPTOAuthConnectionMethod.CALLBACK.value,
                status=ChatGPTOAuthConnectionStatus.CONNECTED.value,
                connected_at=datetime.datetime.now(datetime.UTC),
                last_refreshed_at=datetime.datetime.now(datetime.UTC),
            ),
        ),
    )
    return repo, integration.id


class TestEnsureRuntimeTokens:
    """ensure_runtime_tokens tests."""

    async def test_fresh_token_returns_existing_integration(
        self, rdb_session: AsyncSession
    ) -> None:
        """Sufficiently fresh token is not refreshed."""
        expires_at = datetime.datetime.now(datetime.UTC) + datetime.timedelta(hours=1)
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
            _self: ChatGPTOAuthClient,
            *,
            refresh_token: str,
            connection_method: ChatGPTOAuthConnectionMethod,
        ) -> Result[TokenSet, ProviderRejected | ProviderUnavailable]:
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

        monkeypatch.setattr(ChatGPTOAuthClient, "refresh_tokens", fake_refresh)

        result = await ensure_runtime_tokens(
            integration=integration,
            integration_repository=repo,
            session_manager=cast(
                SessionManager[AsyncSession], _SessionManager(rdb_session)
            ),
        )

        assert isinstance(result, Success)
        assert isinstance(result.value.secrets, ChatGPTOAuthSecrets)
        assert result.value.secrets.access_token == "new-access-token"
        assert result.value.secrets.refresh_token == "new-refresh-token"

    async def test_refresh_rejected_marks_refresh_required(
        self, rdb_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Permanent refresh failure is stored as reconnect-required state."""
        expires_at = datetime.datetime.now(datetime.UTC) + datetime.timedelta(minutes=1)
        repo, integration_id = await _create_integration(
            rdb_session,
            expires_at=expires_at,
        )
        integration = await repo.get_by_id_with_secrets(rdb_session, integration_id)
        assert integration is not None

        async def fake_refresh(
            _self: ChatGPTOAuthClient,
            *,
            refresh_token: str,
            connection_method: ChatGPTOAuthConnectionMethod,
        ) -> Result[TokenSet, ProviderRejected | ProviderUnavailable]:
            return Failure(ProviderRejected(reason="invalid_grant"))

        monkeypatch.setattr(ChatGPTOAuthClient, "refresh_tokens", fake_refresh)

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
        assert isinstance(updated.config, ChatGPTOAuthConfig)
        assert (
            updated.config.status == ChatGPTOAuthConnectionStatus.REFRESH_REQUIRED.value
        )

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
            _self: ChatGPTOAuthClient,
            *,
            refresh_token: str,
            connection_method: ChatGPTOAuthConnectionMethod,
        ) -> Result[TokenSet, ProviderRejected | ProviderUnavailable]:
            return Failure(ProviderUnavailable(reason="rate limited"))

        monkeypatch.setattr(ChatGPTOAuthClient, "refresh_tokens", fail_refresh)
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
        assert isinstance(after_failure.config, ChatGPTOAuthConfig)
        assert (
            after_failure.config.status
            == ChatGPTOAuthConnectionStatus.TEMPORARILY_UNAVAILABLE.value
        )

        async def success_refresh(
            _self: ChatGPTOAuthClient,
            *,
            refresh_token: str,
            connection_method: ChatGPTOAuthConnectionMethod,
        ) -> Result[TokenSet, ProviderRejected | ProviderUnavailable]:
            return Success(
                TokenSet(
                    access_token="recovered-access-token",
                    refresh_token="recovered-refresh-token",
                    expires_at=datetime.datetime.now(datetime.UTC)
                    + datetime.timedelta(hours=1),
                    connection_method=connection_method,
                )
            )

        monkeypatch.setattr(ChatGPTOAuthClient, "refresh_tokens", success_refresh)
        second = await ensure_runtime_tokens(
            integration=after_failure,
            integration_repository=repo,
            session_manager=cast(
                SessionManager[AsyncSession], _SessionManager(rdb_session)
            ),
        )

        assert isinstance(second, Success)
        assert isinstance(second.value.secrets, ChatGPTOAuthSecrets)
        assert second.value.secrets.access_token == "recovered-access-token"

    async def test_concurrent_success_prevents_rejected_failure_state(
        self, rdb_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Old token failure after concurrent refresh success preserves state."""
        expires_at = datetime.datetime.now(datetime.UTC) + datetime.timedelta(minutes=1)
        repo, integration_id = await _create_integration(
            rdb_session,
            expires_at=expires_at,
        )
        stale_integration = await repo.get_by_id_with_secrets(
            rdb_session, integration_id
        )
        assert stale_integration is not None

        update = await repo.update_by_id(
            rdb_session,
            integration_id,
            {
                "secrets": ChatGPTOAuthSecrets(
                    access_token="concurrent-access-token",
                    refresh_token="concurrent-refresh-token",
                    expires_at=datetime.datetime.now(datetime.UTC)
                    + datetime.timedelta(hours=1),
                ),
                "config": ChatGPTOAuthConfig(
                    connection_method=ChatGPTOAuthConnectionMethod.CALLBACK.value,
                    status=ChatGPTOAuthConnectionStatus.CONNECTED.value,
                    connected_at=cast(
                        ChatGPTOAuthConfig, stale_integration.config
                    ).connected_at,
                    last_refreshed_at=datetime.datetime.now(datetime.UTC),
                ),
            },
        )
        assert isinstance(update, Success)

        async def stale_refresh(
            _self: ChatGPTOAuthClient,
            *,
            refresh_token: str,
            connection_method: ChatGPTOAuthConnectionMethod,
        ) -> Result[TokenSet, ProviderRejected | ProviderUnavailable]:
            assert refresh_token == "old-refresh-token"
            return Failure(ProviderRejected(reason="invalid_grant"))

        monkeypatch.setattr(ChatGPTOAuthClient, "refresh_tokens", stale_refresh)

        result = await ensure_runtime_tokens(
            integration=stale_integration,
            integration_repository=repo,
            session_manager=cast(
                SessionManager[AsyncSession], _SessionManager(rdb_session)
            ),
        )

        assert isinstance(result, Success)
        assert isinstance(result.value.secrets, ChatGPTOAuthSecrets)
        assert result.value.secrets.refresh_token == "concurrent-refresh-token"
        assert isinstance(result.value.config, ChatGPTOAuthConfig)
        assert (
            result.value.config.status == ChatGPTOAuthConnectionStatus.CONNECTED.value
        )
