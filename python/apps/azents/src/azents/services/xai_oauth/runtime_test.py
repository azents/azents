"""xAI OAuth runtime refresh tests."""

import asyncio
import datetime
import uuid
from typing import cast
from unittest.mock import AsyncMock

import pytest
from azcommon.result import Failure, Result, Success
from cryptography.fernet import Fernet
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.credentials import XaiOAuthConfig, XaiOAuthSecrets
from azents.core.crypto import CredentialCipher
from azents.core.enums import LLMProvider
from azents.core.xai_oauth import (
    XaiOAuthConnectionMethod,
    XaiOAuthConnectionStatus,
)
from azents.rdb.session import SessionManager
from azents.repos.llm_provider_integration import LLMProviderIntegrationRepository
from azents.repos.llm_provider_integration.data import (
    LLMProviderIntegrationCreate,
    LLMProviderIntegrationWithSecrets,
)
from azents.repos.workspace import WorkspaceRepository
from azents.repos.workspace.data import WorkspaceCreate

from .client import XaiOAuthClient
from .data import (
    ProviderEntitlementDenied,
    ProviderRejected,
    ProviderUnavailable,
    TokenSet,
)
from .runtime import (
    _persist_refresh_success,  # pyright: ignore[reportPrivateUsage]  # Exercise ambiguous commit recovery directly.
    ensure_runtime_tokens,
)

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


class _CommitResponseLostContext:
    """Raise the configured commit-response error from the first context."""

    def __init__(
        self,
        manager: "_CommitResponseLostSessionManager",
        call_number: int,
    ) -> None:
        self._manager = manager
        self._call_number = call_number

    async def __aenter__(self) -> AsyncSession:
        return cast(AsyncSession, AsyncMock(spec=AsyncSession))

    async def __aexit__(self, *_args: object) -> None:
        if self._call_number == 1:
            raise self._manager.persistence_error
        self._manager.successful_exit.set()


class _CommitResponseLostSessionManager:
    """Simulate a successful first transaction whose response is lost."""

    def __init__(self, persistence_error: Exception) -> None:
        self.persistence_error = persistence_error
        self.calls = 0
        self.successful_exit = asyncio.Event()

    def __call__(self) -> _CommitResponseLostContext:
        self.calls += 1
        return _CommitResponseLostContext(self, self.calls)


def _make_runtime_integration() -> LLMProviderIntegrationWithSecrets:
    """Create a detached xAI OAuth integration snapshot."""
    now = datetime.datetime.now(datetime.UTC)
    return LLMProviderIntegrationWithSecrets(
        id="integration-1",
        workspace_id="workspace-1",
        provider=LLMProvider.XAI_OAUTH,
        name="xAI Grok OAuth",
        enabled=True,
        secrets=XaiOAuthSecrets(
            access_token="access-old",
            refresh_token="refresh-old",
            expires_at=now + datetime.timedelta(minutes=1),
        ),
        config=XaiOAuthConfig(
            connection_method=XaiOAuthConnectionMethod.DEVICE.value,
            status=XaiOAuthConnectionStatus.CONNECTED.value,
            connected_at=now - datetime.timedelta(days=1),
            last_refreshed_at=now - datetime.timedelta(hours=1),
        ),
        created_at=now - datetime.timedelta(days=1),
        updated_at=now - datetime.timedelta(hours=1),
    )


@pytest.mark.parametrize(
    "recovery_state",
    ["exact", "rolled_back", "concurrent", "read_failed", "cancelled"],
)
async def test_refresh_commit_ambiguity_repairs_rollback_without_losing_winner(
    recovery_state: str,
) -> None:
    """A rotated token is retried after rollback but never overwrites a winner."""
    integration = _make_runtime_integration()
    repository = AsyncMock(spec=LLMProviderIntegrationRepository)
    persisted: LLMProviderIntegrationWithSecrets | None = None
    lock_calls = 0
    update_calls = 0
    concurrent = integration.model_copy(
        update={
            "secrets": XaiOAuthSecrets(
                access_token="access-winner",
                refresh_token="refresh-winner",
                expires_at=datetime.datetime.now(datetime.UTC)
                + datetime.timedelta(hours=3),
            )
        }
    )
    fresh_cancellation = asyncio.CancelledError("fresh stop")
    reconciliation_error = TimeoutError("reconciliation unavailable")

    async def lock_by_id_with_secrets(
        _session: AsyncSession,
        _integration_id: str,
    ) -> LLMProviderIntegrationWithSecrets:
        nonlocal lock_calls
        lock_calls += 1
        if lock_calls == 1:
            return integration
        if recovery_state == "exact":
            assert persisted is not None
            return persisted
        if recovery_state == "rolled_back":
            return integration
        if recovery_state == "concurrent":
            return concurrent
        if recovery_state == "read_failed":
            raise reconciliation_error
        raise fresh_cancellation

    async def update_by_id(
        _session: AsyncSession,
        _integration_id: str,
        update: dict[str, object],
    ) -> Success[LLMProviderIntegrationWithSecrets]:
        nonlocal persisted, update_calls
        update_calls += 1
        persisted = integration.model_copy(update=update)
        return Success(persisted)

    async def get_by_id_with_secrets(
        _session: AsyncSession,
        _integration_id: str,
    ) -> LLMProviderIntegrationWithSecrets | None:
        assert persisted is not None
        return persisted

    repository.lock_by_id_with_secrets.side_effect = lock_by_id_with_secrets
    repository.update_by_id.side_effect = update_by_id
    repository.get_by_id_with_secrets.side_effect = get_by_id_with_secrets
    persistence_error = ConnectionError("commit response lost")
    manager = _CommitResponseLostSessionManager(persistence_error)
    tokens = TokenSet(
        access_token="access-new",
        refresh_token="refresh-new",
        expires_at=datetime.datetime.now(datetime.UTC) + datetime.timedelta(hours=2),
        connection_method=XaiOAuthConnectionMethod.DEVICE,
    )

    try:
        result = await _persist_refresh_success(
            integration=integration,
            integration_repository=repository,
            session_manager=cast(SessionManager[AsyncSession], manager),
            tokens=tokens,
        )
    except BaseException as error:
        if recovery_state == "read_failed":
            assert error is persistence_error
            assert error.__cause__ is reconciliation_error
        elif recovery_state == "cancelled":
            assert error is persistence_error
            assert error.__cause__ is fresh_cancellation
        else:
            raise
    else:
        assert isinstance(result, Success)
        if recovery_state in {"exact", "rolled_back"}:
            assert result.value == persisted
        elif recovery_state == "concurrent":
            assert result.value == concurrent
        else:
            pytest.fail("ambiguous refresh unexpectedly succeeded")
    assert manager.calls == (3 if recovery_state == "read_failed" else 2)
    assert update_calls == (2 if recovery_state == "rolled_back" else 1)


async def test_fresh_cancel_does_not_abandon_rotated_token_repair() -> None:
    """Caller cancellation is immediate while rollback repair stays retained."""
    integration = _make_runtime_integration()
    repository = AsyncMock(spec=LLMProviderIntegrationRepository)
    repair_started = asyncio.Event()
    allow_repair = asyncio.Event()
    lock_calls = 0
    update_calls = 0
    persisted: LLMProviderIntegrationWithSecrets | None = None

    async def lock_by_id_with_secrets(
        _session: AsyncSession,
        _integration_id: str,
    ) -> LLMProviderIntegrationWithSecrets:
        nonlocal lock_calls
        lock_calls += 1
        if lock_calls > 1:
            repair_started.set()
            await allow_repair.wait()
        return integration

    async def update_by_id(
        _session: AsyncSession,
        _integration_id: str,
        update: dict[str, object],
    ) -> Success[LLMProviderIntegrationWithSecrets]:
        nonlocal persisted, update_calls
        update_calls += 1
        persisted = integration.model_copy(update=update)
        return Success(persisted)

    async def get_by_id_with_secrets(
        _session: AsyncSession,
        _integration_id: str,
    ) -> LLMProviderIntegrationWithSecrets | None:
        return persisted

    repository.lock_by_id_with_secrets.side_effect = lock_by_id_with_secrets
    repository.update_by_id.side_effect = update_by_id
    repository.get_by_id_with_secrets.side_effect = get_by_id_with_secrets
    manager = _CommitResponseLostSessionManager(
        ConnectionError("commit rolled back after provider rotation")
    )
    tokens = TokenSet(
        access_token="access-new",
        refresh_token="refresh-new",
        expires_at=datetime.datetime.now(datetime.UTC) + datetime.timedelta(hours=2),
        connection_method=XaiOAuthConnectionMethod.DEVICE,
    )

    task = asyncio.create_task(
        _persist_refresh_success(
            integration=integration,
            integration_repository=repository,
            session_manager=cast(SessionManager[AsyncSession], manager),
            tokens=tokens,
        )
    )
    await repair_started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        async with asyncio.timeout(0.5):
            await task

    allow_repair.set()
    await asyncio.wait_for(manager.successful_exit.wait(), timeout=0.5)
    assert update_calls == 2
    assert persisted is not None
    assert isinstance(persisted.secrets, XaiOAuthSecrets)
    assert persisted.secrets.refresh_token == "refresh-new"


async def _create_workspace(session: AsyncSession) -> str:
    """Create workspace for tests."""
    suffix = uuid.uuid4().hex[:12]
    handle = f"xai-runtime-{suffix}"
    repo = WorkspaceRepository()
    result = await repo.create(
        session, WorkspaceCreate(name=f"xAI Runtime {suffix}", handle=handle)
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
    """Create xAI OAuth integration for tests."""
    repo = LLMProviderIntegrationRepository(CredentialCipher(_TEST_KEY))
    workspace_id = await _create_workspace(session)
    integration = await repo.create(
        session,
        LLMProviderIntegrationCreate(
            workspace_id=workspace_id,
            provider=LLMProvider.XAI_OAUTH,
            name="xAI Grok OAuth",
            secrets=XaiOAuthSecrets(
                access_token="old-access-token",
                refresh_token="old-refresh-token",
                expires_at=expires_at,
            ),
            config=XaiOAuthConfig(
                connection_method=XaiOAuthConnectionMethod.DEVICE.value,
                status=XaiOAuthConnectionStatus.CONNECTED.value,
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
            _self: XaiOAuthClient,
            *,
            refresh_token: str,
            connection_method: XaiOAuthConnectionMethod,
        ) -> Result[
            TokenSet,
            ProviderRejected | ProviderEntitlementDenied | ProviderUnavailable,
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

        monkeypatch.setattr(XaiOAuthClient, "refresh_tokens", fake_refresh)

        result = await ensure_runtime_tokens(
            integration=integration,
            integration_repository=repo,
            session_manager=cast(
                SessionManager[AsyncSession], _SessionManager(rdb_session)
            ),
        )

        assert isinstance(result, Success)
        assert isinstance(result.value.secrets, XaiOAuthSecrets)
        assert result.value.secrets.access_token == "new-access-token"
        assert result.value.secrets.refresh_token == "new-refresh-token"

    @pytest.mark.parametrize("authority_change", ["disabled", "status"])
    async def test_reloads_runtime_authority_before_provider_call(
        self,
        rdb_session: AsyncSession,
        monkeypatch: pytest.MonkeyPatch,
        authority_change: str,
    ) -> None:
        """A stale caller cannot refresh after the integration becomes unusable."""
        expires_at = datetime.datetime.now(datetime.UTC) + datetime.timedelta(minutes=1)
        repo, integration_id = await _create_integration(
            rdb_session,
            expires_at=expires_at,
        )
        integration = await repo.get_by_id_with_secrets(rdb_session, integration_id)
        assert integration is not None
        config = integration.config
        assert isinstance(config, XaiOAuthConfig)
        if authority_change == "disabled":
            update = await repo.update_by_id(
                rdb_session,
                integration_id,
                {"enabled": False},
            )
            expected_reason = "disabled"
        else:
            update = await repo.update_by_id(
                rdb_session,
                integration_id,
                {
                    "config": config.model_copy(
                        update={
                            "status": XaiOAuthConnectionStatus.REFRESH_REQUIRED.value
                        }
                    )
                },
            )
            expected_reason = "reconnect"
        assert isinstance(update, Success)

        async def unexpected_refresh(
            _self: XaiOAuthClient,
            *,
            refresh_token: str,
            connection_method: XaiOAuthConnectionMethod,
        ) -> Result[
            TokenSet,
            ProviderRejected | ProviderEntitlementDenied | ProviderUnavailable,
        ]:
            del refresh_token, connection_method
            raise AssertionError("provider refresh must not start")

        monkeypatch.setattr(XaiOAuthClient, "refresh_tokens", unexpected_refresh)

        result = await ensure_runtime_tokens(
            integration=integration,
            integration_repository=repo,
            session_manager=cast(
                SessionManager[AsyncSession], _SessionManager(rdb_session)
            ),
        )

        assert isinstance(result, Failure)
        assert isinstance(result.error, ProviderRejected)
        assert expected_reason in result.error.reason

    @pytest.mark.parametrize("authority_change", ["disabled", "status"])
    async def test_revalidates_runtime_authority_after_provider_call(
        self,
        rdb_session: AsyncSession,
        monkeypatch: pytest.MonkeyPatch,
        authority_change: str,
    ) -> None:
        """Refresh results cannot overwrite disable or reconnect decisions."""
        expires_at = datetime.datetime.now(datetime.UTC) + datetime.timedelta(minutes=1)
        repo, integration_id = await _create_integration(
            rdb_session,
            expires_at=expires_at,
        )
        integration = await repo.get_by_id_with_secrets(rdb_session, integration_id)
        assert integration is not None
        config = integration.config
        assert isinstance(config, XaiOAuthConfig)

        async def stale_refresh(
            _self: XaiOAuthClient,
            *,
            refresh_token: str,
            connection_method: XaiOAuthConnectionMethod,
        ) -> Result[
            TokenSet,
            ProviderRejected | ProviderEntitlementDenied | ProviderUnavailable,
        ]:
            assert refresh_token == "old-refresh-token"
            if authority_change == "disabled":
                update = await repo.update_by_id(
                    rdb_session,
                    integration_id,
                    {"enabled": False},
                )
            else:
                update = await repo.update_by_id(
                    rdb_session,
                    integration_id,
                    {
                        "config": config.model_copy(
                            update={
                                "status": (
                                    XaiOAuthConnectionStatus.REFRESH_REQUIRED.value
                                )
                            }
                        )
                    },
                )
            assert isinstance(update, Success)
            return Success(
                TokenSet(
                    access_token="stale-access-token",
                    refresh_token="stale-refresh-token",
                    expires_at=datetime.datetime.now(datetime.UTC)
                    + datetime.timedelta(hours=2),
                    connection_method=connection_method,
                )
            )

        monkeypatch.setattr(XaiOAuthClient, "refresh_tokens", stale_refresh)

        result = await ensure_runtime_tokens(
            integration=integration,
            integration_repository=repo,
            session_manager=cast(
                SessionManager[AsyncSession], _SessionManager(rdb_session)
            ),
        )
        stored = await repo.get_by_id_with_secrets(rdb_session, integration_id)

        assert isinstance(result, Failure)
        assert isinstance(result.error, ProviderRejected)
        assert stored is not None
        assert isinstance(stored.secrets, XaiOAuthSecrets)
        assert stored.secrets.refresh_token == "old-refresh-token"
        if authority_change == "disabled":
            assert not stored.enabled
        else:
            assert isinstance(stored.config, XaiOAuthConfig)
            assert (
                stored.config.status == XaiOAuthConnectionStatus.REFRESH_REQUIRED.value
            )

    async def test_entitlement_denied_marks_entitlement_state(
        self, rdb_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """HTTP 403 refresh failure is stored as entitlement denial."""
        expires_at = datetime.datetime.now(datetime.UTC) + datetime.timedelta(minutes=1)
        repo, integration_id = await _create_integration(
            rdb_session,
            expires_at=expires_at,
        )
        integration = await repo.get_by_id_with_secrets(rdb_session, integration_id)
        assert integration is not None

        async def fake_refresh(
            _self: XaiOAuthClient,
            *,
            refresh_token: str,
            connection_method: XaiOAuthConnectionMethod,
        ) -> Result[
            TokenSet,
            ProviderRejected | ProviderEntitlementDenied | ProviderUnavailable,
        ]:
            return Failure(ProviderEntitlementDenied(reason="entitlement denied"))

        monkeypatch.setattr(XaiOAuthClient, "refresh_tokens", fake_refresh)

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
        assert isinstance(updated.config, XaiOAuthConfig)
        assert (
            updated.config.status == XaiOAuthConnectionStatus.ENTITLEMENT_DENIED.value
        )
        assert updated.config.entitlement_status == "denied"

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
            _self: XaiOAuthClient,
            *,
            refresh_token: str,
            connection_method: XaiOAuthConnectionMethod,
        ) -> Result[
            TokenSet,
            ProviderRejected | ProviderEntitlementDenied | ProviderUnavailable,
        ]:
            return Failure(ProviderUnavailable(reason="rate limited"))

        monkeypatch.setattr(XaiOAuthClient, "refresh_tokens", fail_refresh)
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
        assert isinstance(after_failure.config, XaiOAuthConfig)
        assert (
            after_failure.config.status
            == XaiOAuthConnectionStatus.TEMPORARILY_UNAVAILABLE.value
        )

        async def success_refresh(
            _self: XaiOAuthClient,
            *,
            refresh_token: str,
            connection_method: XaiOAuthConnectionMethod,
        ) -> Result[
            TokenSet,
            ProviderRejected | ProviderEntitlementDenied | ProviderUnavailable,
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

        monkeypatch.setattr(XaiOAuthClient, "refresh_tokens", success_refresh)
        second = await ensure_runtime_tokens(
            integration=after_failure,
            integration_repository=repo,
            session_manager=cast(
                SessionManager[AsyncSession], _SessionManager(rdb_session)
            ),
        )

        assert isinstance(second, Success)
        assert isinstance(second.value.secrets, XaiOAuthSecrets)
        assert second.value.secrets.access_token == "recovered-access-token"

    @pytest.mark.parametrize("provider_result", ["success", "failure"])
    async def test_concurrent_failure_metadata_does_not_claim_token_generation(
        self,
        rdb_session: AsyncSession,
        monkeypatch: pytest.MonkeyPatch,
        provider_result: str,
    ) -> None:
        """Failure status alone cannot masquerade as a completed token refresh."""
        expires_at = datetime.datetime.now(datetime.UTC) + datetime.timedelta(minutes=1)
        repo, integration_id = await _create_integration(
            rdb_session,
            expires_at=expires_at,
        )
        stale_integration = await repo.get_by_id_with_secrets(
            rdb_session,
            integration_id,
        )
        assert stale_integration is not None
        stale_config = stale_integration.config
        assert isinstance(stale_config, XaiOAuthConfig)

        async def refresh_after_other_failure(
            _self: XaiOAuthClient,
            *,
            refresh_token: str,
            connection_method: XaiOAuthConnectionMethod,
        ) -> Result[
            TokenSet,
            ProviderRejected | ProviderEntitlementDenied | ProviderUnavailable,
        ]:
            update = await repo.update_by_id(
                rdb_session,
                integration_id,
                {
                    "config": stale_config.model_copy(
                        update={
                            "status": (
                                XaiOAuthConnectionStatus.TEMPORARILY_UNAVAILABLE.value
                            ),
                            "last_failed_at": datetime.datetime.now(datetime.UTC),
                            "last_failure_reason": "concurrent failure",
                        }
                    )
                },
            )
            assert isinstance(update, Success)
            if provider_result == "failure":
                return Failure(ProviderUnavailable(reason="current failure"))
            return Success(
                TokenSet(
                    access_token="fresh-access-token",
                    refresh_token="fresh-refresh-token",
                    expires_at=datetime.datetime.now(datetime.UTC)
                    + datetime.timedelta(hours=2),
                    connection_method=connection_method,
                )
            )

        monkeypatch.setattr(
            XaiOAuthClient,
            "refresh_tokens",
            refresh_after_other_failure,
        )

        result = await ensure_runtime_tokens(
            integration=stale_integration,
            integration_repository=repo,
            session_manager=cast(
                SessionManager[AsyncSession],
                _SessionManager(rdb_session),
            ),
        )
        stored = await repo.get_by_id_with_secrets(rdb_session, integration_id)
        assert stored is not None
        assert isinstance(stored.config, XaiOAuthConfig)
        if provider_result == "success":
            assert isinstance(result, Success)
            assert isinstance(result.value.secrets, XaiOAuthSecrets)
            assert result.value.secrets.refresh_token == "fresh-refresh-token"
            assert stored.config.status == XaiOAuthConnectionStatus.CONNECTED.value
        else:
            assert isinstance(result, Failure)
            assert stored.config.last_failure_reason == "current failure"

    @pytest.mark.parametrize("provider_result", ["success", "failure"])
    async def test_concurrent_success_wins_refresh_race(
        self,
        rdb_session: AsyncSession,
        monkeypatch: pytest.MonkeyPatch,
        provider_result: str,
    ) -> None:
        """A slower refresh cannot replace or reject a newer token generation."""
        expires_at = datetime.datetime.now(datetime.UTC) + datetime.timedelta(minutes=1)
        repo, integration_id = await _create_integration(
            rdb_session,
            expires_at=expires_at,
        )
        stale_integration = await repo.get_by_id_with_secrets(
            rdb_session, integration_id
        )
        assert stale_integration is not None
        stale_config = stale_integration.config
        assert isinstance(stale_config, XaiOAuthConfig)

        async def stale_refresh(
            _self: XaiOAuthClient,
            *,
            refresh_token: str,
            connection_method: XaiOAuthConnectionMethod,
        ) -> Result[
            TokenSet,
            ProviderRejected | ProviderEntitlementDenied | ProviderUnavailable,
        ]:
            assert refresh_token == "old-refresh-token"
            update = await repo.update_by_id(
                rdb_session,
                integration_id,
                {
                    "secrets": XaiOAuthSecrets(
                        access_token="winner-access-token",
                        refresh_token="winner-refresh-token",
                        expires_at=datetime.datetime.now(datetime.UTC)
                        + datetime.timedelta(hours=3),
                    ),
                    "config": stale_config.model_copy(
                        update={
                            "status": XaiOAuthConnectionStatus.CONNECTED.value,
                            "last_refreshed_at": datetime.datetime.now(datetime.UTC),
                        }
                    ),
                },
            )
            assert isinstance(update, Success)
            if provider_result == "failure":
                return Failure(ProviderRejected(reason="invalid_grant"))
            return Success(
                TokenSet(
                    access_token="stale-access-token",
                    refresh_token="stale-refresh-token",
                    expires_at=datetime.datetime.now(datetime.UTC)
                    + datetime.timedelta(hours=2),
                    connection_method=connection_method,
                )
            )

        monkeypatch.setattr(XaiOAuthClient, "refresh_tokens", stale_refresh)

        result = await ensure_runtime_tokens(
            integration=stale_integration,
            integration_repository=repo,
            session_manager=cast(
                SessionManager[AsyncSession], _SessionManager(rdb_session)
            ),
        )

        assert isinstance(result, Success)
        assert isinstance(result.value.secrets, XaiOAuthSecrets)
        assert result.value.secrets.refresh_token == "winner-refresh-token"
        assert isinstance(result.value.config, XaiOAuthConfig)
        assert result.value.config.status == XaiOAuthConnectionStatus.CONNECTED.value
