"""MCP Toolkit OAuth resolution tests."""

import asyncio
import datetime
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import MCPOAuthConnectionStatus
from azents.core.oauth2 import OAuthTokenError, OAuthTokenResponse
from azents.core.tools import McpToolkitConfig, ResolveContext
from azents.repos.mcp_oauth_connection import MCPOAuthConnectionRepository
from azents.repos.mcp_oauth_connection.data import MCPOAuthConnection

from .mcp import (
    McpToolkit,
    McpToolkitProvider,
    _persist_refreshed_tokens_if_unchanged,  # pyright: ignore[reportPrivateUsage]  # Exercise ambiguous commit recovery directly.
)

_NOW = datetime.datetime.now(datetime.UTC)


def _make_connection(**updates: object) -> MCPOAuthConnection:
    """Create an expired connected OAuth snapshot."""
    connection = MCPOAuthConnection(
        id="connection-1",
        toolkit_id="toolkit-1",
        issuer="https://issuer.example",
        resource=None,
        server_url="https://mcp.example",
        authorization_endpoint="https://issuer.example/authorize",
        token_endpoint="https://issuer.example/token",
        registration_endpoint=None,
        client_id="client-1",
        client_secret="secret-1",
        token_endpoint_auth_method="client_secret_post",
        scope="tools",
        access_token="access-old",
        refresh_token="refresh-old",
        expires_at=_NOW - datetime.timedelta(minutes=1),
        status=MCPOAuthConnectionStatus.CONNECTED,
        created_at=_NOW - datetime.timedelta(days=1),
        updated_at=_NOW - datetime.timedelta(hours=1),
    )
    return connection.model_copy(update=updates)


def _make_resolve_context() -> ResolveContext:
    """Create an OAuth Toolkit resolution context."""
    return ResolveContext(
        toolkit_id="toolkit-1",
        toolkit_name="MCP",
        credentials_json=None,
        agent_id="agent-1",
        session_id="session-1",
        user_id="user-1",
        web_url="https://app.example",
        oauth_secret_key="secret",
        workspace_id="workspace-1",
        workspace_handle="workspace",
        mcp_proxy_url=None,
    )


@pytest.mark.parametrize(
    "recovery_state",
    ["exact", "rolled_back", "concurrent", "read_failed", "cancelled"],
)
async def test_refresh_commit_ambiguity_repairs_rollback_without_losing_winner(
    recovery_state: str,
) -> None:
    """A rotated token is retried after rollback but never overwrites a winner."""
    snapshot = _make_connection()
    expires_at = _NOW + datetime.timedelta(hours=1)
    expected = _make_connection(
        access_token="access-new",
        refresh_token="refresh-new",
        expires_at=expires_at,
        updated_at=_NOW,
    )
    concurrent = _make_connection(
        access_token="access-winner",
        refresh_token="refresh-winner",
        expires_at=_NOW + datetime.timedelta(hours=2),
        updated_at=_NOW,
    )
    repository = AsyncMock(spec=MCPOAuthConnectionRepository)
    repository.update_tokens.return_value = expected
    lock_calls = 0
    update_calls = 0
    fresh_cancellation = asyncio.CancelledError("fresh stop")
    reconciliation_error = TimeoutError("reconciliation unavailable")

    async def get_by_toolkit_id_for_update(
        _session: AsyncSession,
        _toolkit_id: str,
    ) -> MCPOAuthConnection:
        nonlocal lock_calls
        lock_calls += 1
        if lock_calls == 1:
            return snapshot
        if recovery_state == "exact":
            return expected
        if recovery_state == "rolled_back":
            return snapshot
        if recovery_state == "concurrent":
            return concurrent
        if recovery_state == "read_failed":
            raise reconciliation_error
        raise fresh_cancellation

    async def update_tokens(
        _session: AsyncSession,
        **_kwargs: object,
    ) -> MCPOAuthConnection:
        nonlocal update_calls
        update_calls += 1
        return expected

    repository.get_by_toolkit_id_for_update.side_effect = get_by_toolkit_id_for_update
    repository.update_tokens.side_effect = update_tokens

    persistence_error = ConnectionError("commit response lost")
    session_calls = 0

    @asynccontextmanager
    async def session_manager() -> AsyncGenerator[AsyncSession, None]:
        nonlocal session_calls
        session_calls += 1
        call_number = session_calls
        yield AsyncMock(spec=AsyncSession)
        if call_number == 1:
            raise persistence_error

    try:
        result = await _persist_refreshed_tokens_if_unchanged(
            connection_repo=repository,
            session_manager=session_manager,
            toolkit_id=snapshot.toolkit_id,
            snapshot=snapshot,
            access_token="access-new",
            refresh_token="refresh-new",
            expires_at=expires_at,
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
        if recovery_state in {"exact", "rolled_back"}:
            assert result == expected
        elif recovery_state == "concurrent":
            assert result == concurrent
        else:
            pytest.fail("ambiguous refresh unexpectedly succeeded")
    assert session_calls == (3 if recovery_state == "read_failed" else 2)
    assert update_calls == (2 if recovery_state == "rolled_back" else 1)


async def test_refresh_repair_ignores_timestamp_only_concurrent_change() -> None:
    """An unrelated row timestamp must not discard provider-rotated tokens."""
    snapshot = _make_connection()
    timestamp_only_change = snapshot.model_copy(
        update={"updated_at": snapshot.updated_at + datetime.timedelta(seconds=1)}
    )
    expected = _make_connection(
        access_token="access-new",
        refresh_token="refresh-new",
        expires_at=_NOW + datetime.timedelta(hours=1),
        updated_at=_NOW,
    )
    repository = AsyncMock(spec=MCPOAuthConnectionRepository)
    repository.get_by_toolkit_id_for_update.return_value = timestamp_only_change
    repository.update_tokens.return_value = expected

    @asynccontextmanager
    async def session_manager() -> AsyncGenerator[AsyncSession, None]:
        yield AsyncMock(spec=AsyncSession)

    result = await _persist_refreshed_tokens_if_unchanged(
        connection_repo=repository,
        session_manager=session_manager,
        toolkit_id=snapshot.toolkit_id,
        snapshot=snapshot,
        access_token="access-new",
        refresh_token="refresh-new",
        expires_at=expected.expires_at,
    )

    assert result == expected
    repository.update_tokens.assert_awaited_once()


@pytest.mark.parametrize(
    "winner",
    [
        _make_connection(
            access_token="access-winner",
            refresh_token="refresh-winner",
            expires_at=_NOW + datetime.timedelta(hours=2),
        ),
        _make_connection(status=MCPOAuthConnectionStatus.RECONNECT_REQUIRED),
        None,
    ],
    ids=["new-token", "reconnect-required", "disconnected"],
)
async def test_refresh_repair_preserves_concurrent_authority_change(
    winner: MCPOAuthConnection | None,
) -> None:
    """A token winner, reconnect, or disconnect is never overwritten."""
    snapshot = _make_connection()
    repository = AsyncMock(spec=MCPOAuthConnectionRepository)
    repository.get_by_toolkit_id_for_update.return_value = winner

    @asynccontextmanager
    async def session_manager() -> AsyncGenerator[AsyncSession, None]:
        yield AsyncMock(spec=AsyncSession)

    result = await _persist_refreshed_tokens_if_unchanged(
        connection_repo=repository,
        session_manager=session_manager,
        toolkit_id=snapshot.toolkit_id,
        snapshot=snapshot,
        access_token="access-new",
        refresh_token="refresh-new",
        expires_at=_NOW + datetime.timedelta(hours=1),
    )

    assert result == winner
    repository.update_tokens.assert_not_awaited()


async def test_fresh_cancel_does_not_abandon_mcp_token_repair() -> None:
    """Caller cancellation is immediate while rollback repair stays retained."""
    snapshot = _make_connection()
    expected = _make_connection(
        access_token="access-new",
        refresh_token="refresh-new",
        expires_at=_NOW + datetime.timedelta(hours=1),
        updated_at=_NOW,
    )
    repository = AsyncMock(spec=MCPOAuthConnectionRepository)
    repair_started = asyncio.Event()
    allow_repair = asyncio.Event()
    repaired = asyncio.Event()
    lock_calls = 0
    update_calls = 0

    async def get_by_toolkit_id_for_update(
        _session: AsyncSession,
        _toolkit_id: str,
    ) -> MCPOAuthConnection:
        nonlocal lock_calls
        lock_calls += 1
        if lock_calls > 1:
            repair_started.set()
            await allow_repair.wait()
        return snapshot

    async def update_tokens(
        _session: AsyncSession,
        **_kwargs: object,
    ) -> MCPOAuthConnection:
        nonlocal update_calls
        update_calls += 1
        if update_calls > 1:
            repaired.set()
        return expected

    repository.get_by_toolkit_id_for_update.side_effect = get_by_toolkit_id_for_update
    repository.update_tokens.side_effect = update_tokens
    session_calls = 0

    @asynccontextmanager
    async def session_manager() -> AsyncGenerator[AsyncSession, None]:
        nonlocal session_calls
        session_calls += 1
        call_number = session_calls
        yield AsyncMock(spec=AsyncSession)
        if call_number == 1:
            raise ConnectionError("commit rolled back after provider rotation")

    task = asyncio.create_task(
        _persist_refreshed_tokens_if_unchanged(
            connection_repo=repository,
            session_manager=session_manager,
            toolkit_id=snapshot.toolkit_id,
            snapshot=snapshot,
            access_token="access-new",
            refresh_token="refresh-new",
            expires_at=expected.expires_at,
        )
    )
    await repair_started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        async with asyncio.timeout(0.5):
            await task

    allow_repair.set()
    await asyncio.wait_for(repaired.wait(), timeout=0.5)
    assert update_calls == 2


class TestMcpOAuthRefreshSessionLifetime:
    """MCP OAuth refresh must not retain DB sessions during network calls."""

    async def test_releases_db_session_before_refresh_request(self) -> None:
        """The token endpoint call runs between short read and write sessions."""
        snapshot = _make_connection()
        refreshed_connection = _make_connection(
            access_token="access-new",
            refresh_token="refresh-new",
            expires_at=_NOW + datetime.timedelta(hours=1),
            updated_at=_NOW,
        )
        repository = AsyncMock(spec=MCPOAuthConnectionRepository)
        repository.get_by_toolkit_id.return_value = snapshot
        repository.get_by_toolkit_id_for_update.return_value = snapshot
        repository.update_tokens.return_value = refreshed_connection
        active_sessions = 0

        @asynccontextmanager
        async def session_manager() -> AsyncGenerator[AsyncSession, None]:
            nonlocal active_sessions
            active_sessions += 1
            try:
                yield AsyncMock(spec=AsyncSession)
            finally:
                active_sessions -= 1

        provider = McpToolkitProvider(
            connection_repo=repository,
            session_manager=session_manager,
        )

        async def refresh_access_token(**_kwargs: object) -> OAuthTokenResponse:
            assert active_sessions == 0
            return OAuthTokenResponse(
                access_token="access-new",
                refresh_token="refresh-new",
                expires_at=_NOW + datetime.timedelta(hours=1),
            )

        with patch(
            "azents.engine.tools.mcp.refresh_access_token",
            side_effect=refresh_access_token,
        ):
            result = await provider.resolve(
                McpToolkitConfig(
                    server_url="https://mcp.example",
                    auth_type="oauth2",
                ),
                _make_resolve_context(),
            )

        assert isinstance(result, McpToolkit)
        assert active_sessions == 0
        repository.update_tokens.assert_awaited_once()

    async def test_concurrent_refresh_wins_before_persistence(self) -> None:
        """A stale refresh result never overwrites a newer committed token."""
        snapshot = _make_connection()
        concurrent = _make_connection(
            access_token="access-concurrent",
            refresh_token="refresh-concurrent",
            expires_at=_NOW + datetime.timedelta(hours=2),
            updated_at=_NOW,
        )
        repository = AsyncMock(spec=MCPOAuthConnectionRepository)
        repository.get_by_toolkit_id.return_value = snapshot
        repository.get_by_toolkit_id_for_update.return_value = concurrent

        @asynccontextmanager
        async def session_manager() -> AsyncGenerator[AsyncSession, None]:
            yield AsyncMock(spec=AsyncSession)

        provider = McpToolkitProvider(
            connection_repo=repository,
            session_manager=session_manager,
        )

        with patch(
            "azents.engine.tools.mcp.refresh_access_token",
            return_value=OAuthTokenResponse(
                access_token="access-stale",
                refresh_token="refresh-stale",
                expires_at=_NOW + datetime.timedelta(hours=1),
            ),
        ):
            result = await provider.resolve(
                McpToolkitConfig(
                    server_url="https://mcp.example",
                    auth_type="oauth2",
                ),
                _make_resolve_context(),
            )

        assert isinstance(result, McpToolkit)
        repository.update_tokens.assert_not_awaited()

    async def test_stale_invalid_grant_does_not_revoke_concurrent_refresh(
        self,
    ) -> None:
        """An invalid result for an old token cannot revoke a newer token."""
        snapshot = _make_connection()
        concurrent = _make_connection(
            access_token="access-concurrent",
            refresh_token="refresh-concurrent",
            expires_at=_NOW + datetime.timedelta(hours=2),
            updated_at=_NOW,
        )
        repository = AsyncMock(spec=MCPOAuthConnectionRepository)
        repository.get_by_toolkit_id.return_value = snapshot
        repository.get_by_toolkit_id_for_update.return_value = concurrent

        @asynccontextmanager
        async def session_manager() -> AsyncGenerator[AsyncSession, None]:
            yield AsyncMock(spec=AsyncSession)

        provider = McpToolkitProvider(
            connection_repo=repository,
            session_manager=session_manager,
        )

        with patch(
            "azents.engine.tools.mcp.refresh_access_token",
            side_effect=OAuthTokenError("invalid_grant"),
        ):
            result = await provider.resolve(
                McpToolkitConfig(
                    server_url="https://mcp.example",
                    auth_type="oauth2",
                ),
                _make_resolve_context(),
            )

        assert isinstance(result, McpToolkit)
        repository.mark_reconnect_required.assert_not_awaited()
