"""MCP Toolkit OAuth refresh transaction tests."""

import datetime
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import MCPOAuthConnectionStatus
from azents.core.oauth2 import OAuthTokenResponse
from azents.repos.mcp_oauth_connection import MCPOAuthConnectionRepository
from azents.repos.mcp_oauth_connection.data import MCPOAuthConnection

from . import mcp as mcp_module


def test_source_identity_exposes_only_mcp_server_origin() -> None:
    """Exclude paths, query parameters, and credentials from catalog identity."""
    identity = mcp_module.McpToolkitProvider.source_identity(
        mcp_module.McpToolkitConfig(
            server_url="https://user:secret@mcp.example.test:8443/private?token=secret",
            auth_type="none",
        )
    )

    assert identity == (("server", "https://mcp.example.test:8443"),)


def _connection(*, access_token: str, updated_second: int = 0) -> MCPOAuthConnection:
    """Build one refreshable OAuth connection snapshot."""
    now = datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)
    return MCPOAuthConnection(
        id="1" * 32,
        toolkit_id="toolkit-1",
        issuer=None,
        resource=None,
        server_url="https://mcp.example.test",
        authorization_endpoint="https://auth.example.test/authorize",
        token_endpoint="https://auth.example.test/token",
        registration_endpoint=None,
        client_id="client-1",
        client_secret="secret-1",
        token_endpoint_auth_method="client_secret_post",
        scope=None,
        access_token=access_token,
        refresh_token="refresh-1",
        expires_at=now,
        status=MCPOAuthConnectionStatus.CONNECTED,
        created_at=now,
        updated_at=now + datetime.timedelta(seconds=updated_second),
    )


class _ConnectionRepository(MCPOAuthConnectionRepository):
    """In-memory repository that verifies every DB call has an open session."""

    def __init__(self, connection: MCPOAuthConnection, active: list[int]) -> None:
        self.connection = connection
        self.active = active
        self.update_calls = 0
        self.reconnect_calls = 0

    def _assert_session(self) -> None:
        assert self.active[0] == 1

    async def get_by_toolkit_id(
        self, session: AsyncSession, toolkit_id: str
    ) -> MCPOAuthConnection:
        del session, toolkit_id
        self._assert_session()
        return self.connection.model_copy(deep=True)

    async def get_by_toolkit_id_for_update(
        self, session: AsyncSession, toolkit_id: str
    ) -> MCPOAuthConnection:
        return await self.get_by_toolkit_id(session, toolkit_id)

    async def update_tokens(
        self,
        session: AsyncSession,
        *,
        toolkit_id: str,
        access_token: str,
        refresh_token: str | None,
        expires_at: datetime.datetime | None,
    ) -> MCPOAuthConnection:
        del session, toolkit_id
        self._assert_session()
        self.update_calls += 1
        self.connection = self.connection.model_copy(
            update={
                "access_token": access_token,
                "refresh_token": refresh_token or self.connection.refresh_token,
                "expires_at": expires_at,
                "updated_at": self.connection.updated_at
                + datetime.timedelta(seconds=1),
            }
        )
        return self.connection.model_copy(deep=True)

    async def mark_reconnect_required(
        self, session: AsyncSession, *, toolkit_id: str
    ) -> None:
        del session, toolkit_id
        self._assert_session()
        self.reconnect_calls += 1
        self.connection = self.connection.model_copy(
            update={"status": MCPOAuthConnectionStatus.RECONNECT_REQUIRED}
        )


@pytest.mark.asyncio
async def test_oauth_fresh_token_returns_without_http_or_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A fresh connected token closes its read and skips refresh I/O."""
    active = [0]

    @asynccontextmanager
    async def session_manager() -> AsyncIterator[AsyncSession]:
        active[0] += 1
        try:
            yield AsyncSession()
        finally:
            active[0] -= 1

    async def unexpected_refresh(*args: object, **kwargs: object) -> OAuthTokenResponse:
        del args, kwargs
        raise AssertionError("Fresh OAuth tokens must not refresh")

    monkeypatch.setattr(mcp_module, "refresh_access_token", unexpected_refresh)
    fresh = _connection(access_token="access-1").model_copy(
        update={
            "expires_at": datetime.datetime.now(datetime.UTC)
            + datetime.timedelta(hours=1)
        }
    )
    repository = _ConnectionRepository(fresh, active)

    connection = await mcp_module._ensure_oauth_connection_token(
        connection_repo=repository,
        session_manager=session_manager,
        toolkit_id="toolkit-1",
        proxy_url=None,
    )

    assert connection is not None
    assert connection.access_token == "access-1"
    assert repository.update_calls == 0
    assert repository.reconnect_calls == 0
    assert active[0] == 0


@pytest.mark.asyncio
async def test_oauth_refresh_closes_db_session_during_http(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Token HTTP I/O runs between the read and conditional-write sessions."""
    active = [0]

    @asynccontextmanager
    async def session_manager() -> AsyncIterator[AsyncSession]:
        active[0] += 1
        try:
            yield AsyncSession()
        finally:
            active[0] -= 1

    async def refresh_access_token(
        token_url: str,
        client_id: str,
        client_secret: str | None,
        refresh_token: str,
        *,
        proxy_url: str | None,
    ) -> OAuthTokenResponse:
        del token_url, client_id, client_secret, refresh_token, proxy_url
        assert active[0] == 0
        return OAuthTokenResponse(
            access_token="access-2",
            refresh_token="refresh-2",
            expires_in=3600,
        )

    monkeypatch.setattr(mcp_module, "refresh_access_token", refresh_access_token)
    repository = _ConnectionRepository(_connection(access_token="access-1"), active)

    refreshed = await mcp_module._ensure_oauth_connection_token(
        connection_repo=repository,
        session_manager=session_manager,
        toolkit_id="toolkit-1",
        proxy_url=None,
    )

    assert refreshed is not None
    assert refreshed.access_token == "access-2"
    assert repository.update_calls == 1
    assert active[0] == 0


@pytest.mark.asyncio
async def test_oauth_refresh_keeps_concurrent_newer_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A stale refresh result cannot overwrite another committed refresh."""
    active = [0]

    @asynccontextmanager
    async def session_manager() -> AsyncIterator[AsyncSession]:
        active[0] += 1
        try:
            yield AsyncSession()
        finally:
            active[0] -= 1

    repository = _ConnectionRepository(_connection(access_token="access-1"), active)

    async def refresh_access_token(
        token_url: str,
        client_id: str,
        client_secret: str | None,
        refresh_token: str,
        *,
        proxy_url: str | None,
    ) -> OAuthTokenResponse:
        del token_url, client_id, client_secret, refresh_token, proxy_url
        assert active[0] == 0
        repository.connection = _connection(
            access_token="access-from-peer",
            updated_second=1,
        )
        return OAuthTokenResponse(
            access_token="stale-local-access",
            refresh_token="stale-local-refresh",
            expires_in=3600,
        )

    monkeypatch.setattr(mcp_module, "refresh_access_token", refresh_access_token)

    refreshed = await mcp_module._ensure_oauth_connection_token(
        connection_repo=repository,
        session_manager=session_manager,
        toolkit_id="toolkit-1",
        proxy_url=None,
    )

    assert refreshed is not None
    assert refreshed.access_token == "access-from-peer"
    assert repository.update_calls == 0
    assert active[0] == 0


@pytest.mark.asyncio
async def test_oauth_missing_refresh_token_marks_reconnect_required() -> None:
    """An expired connection without refresh authority requires reconnect."""
    active = [0]

    @asynccontextmanager
    async def session_manager() -> AsyncIterator[AsyncSession]:
        active[0] += 1
        try:
            yield AsyncSession()
        finally:
            active[0] -= 1

    expired = _connection(access_token="access-1").model_copy(
        update={"refresh_token": None}
    )
    repository = _ConnectionRepository(expired, active)

    connection = await mcp_module._ensure_oauth_connection_token(
        connection_repo=repository,
        session_manager=session_manager,
        toolkit_id="toolkit-1",
        proxy_url=None,
    )

    assert connection is not None
    assert connection.status is MCPOAuthConnectionStatus.RECONNECT_REQUIRED
    assert repository.update_calls == 0
    assert repository.reconnect_calls == 1
    assert active[0] == 0
