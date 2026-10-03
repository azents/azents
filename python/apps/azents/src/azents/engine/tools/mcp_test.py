"""MCP Toolkit OAuth refresh transaction tests."""

import datetime
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import MCPOAuthConnectionStatus
from azents.core.oauth2 import OAuthTokenResponse
from azents.repos.mcp_oauth_connection import MCPOAuthConnectionRepository
from azents.repos.mcp_oauth_connection.data import MCPOAuthConnection
from azents.repos.mcp_oauth_connection.operations import (
    MCPOAuthRuntimeOperationRepository,
)

from . import mcp as mcp_module


@pytest.mark.parametrize(
    ("auth_type", "header_name", "credentials", "expected"),
    [
        (
            "header",
            "X-Api-Key",
            {"type": "header", "value": "key"},
            {"X-Api-Key": "key"},
        ),
        ("header", None, {"type": "header", "value": "key"}, {"Authorization": "key"}),
        (
            "bearer",
            None,
            {"type": "bearer", "token": "token"},
            {"Authorization": "Bearer token"},
        ),
        ("none", None, {"type": "bearer", "token": "token"}, {}),
        ("header", "X-Api-Key", None, {}),
        ("bearer", None, {"type": "bearer", "token": 7}, {}),
    ],
)
def test_connection_test_headers_match_typed_runtime_credentials(
    auth_type: str,
    header_name: str | None,
    credentials: object,
    expected: dict[str, str],
) -> None:
    """Current header value and bearer token fields use runtime header semantics."""
    config = mcp_module.McpToolkitConfig(
        server_url="https://mcp.example.test",
        auth_type=auth_type,
        header_name=header_name,
    )
    encoded = None if credentials is None else json.dumps(credentials)
    assert mcp_module._build_test_auth_headers(config, encoded) == expected


@pytest.mark.parametrize("encoded", ["{", "[]", "null", '{"token": 7}'])
def test_invalid_connection_credentials_keep_empty_auth_headers(encoded: str) -> None:
    config = mcp_module.McpToolkitConfig(
        server_url="https://mcp.example.test", auth_type="bearer"
    )
    assert mcp_module._build_test_auth_headers(config, encoded) == {}


async def test_header_connection_test_passes_the_configured_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Exercise the public provider method with an entirely local transport seam."""
    seen: list[dict[str, str]] = []

    async def test_transport(
        server_url: str,
        headers: dict[str, str],
        timeout: float,
        *,
        proxy_url: str | None,
    ) -> mcp_module.TestConnectionResult:
        del server_url, timeout, proxy_url
        seen.append(headers)
        return mcp_module.TestConnectionResult(
            success=True,
            message="Local test",
            discovered_auth_url=None,
            discovered_token_url=None,
            supports_dcr=None,
        )

    monkeypatch.setattr(mcp_module, "test_mcp_transport", test_transport)
    result = await mcp_module.McpToolkitProvider().test_connection(
        mcp_module.McpToolkitConfig(
            server_url="https://mcp.example.test",
            auth_type="header",
            header_name="X-Api-Key",
        ),
        '{"type":"header","value":"key"}',
    )
    assert result.success
    assert seen == [{"X-Api-Key": "key"}]


@pytest.mark.parametrize(
    ("status", "body", "expected"),
    [
        (400, '{"error":"invalid_grant","description":"provider extension"}', True),
        (401, '{"error":"invalid_grant"}', True),
        (400, '{"error":"temporarily_unavailable"}', False),
        (401, "{}", False),
        (400, '{"error":null}', False),
        (401, '{"error":7}', False),
        (400, '{"error":["invalid_grant"]}', False),
        (400, "[]", True),
        (401, "null", True),
        (400, "{", True),
        (403, '{"error":"invalid_grant"}', False),
        (500, "{", False),
    ],
)
def test_refresh_reconnect_decoder_preserves_the_decision_table(
    status: int, body: str, expected: bool
) -> None:
    """Malformed/nonobject bodies preserve only the existing status fallback."""
    request = httpx.Request("POST", "https://auth.example.test/token")
    response = httpx.Response(status, request=request, content=body)
    error = httpx.HTTPStatusError("Owned fixture", request=request, response=response)
    assert mcp_module._refresh_failure_requires_reconnect(error) is expected


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
        toolkit_id="toolkit-1",
        proxy_url=None,
        operations=MCPOAuthRuntimeOperationRepository(
            session_manager=session_manager, connection_repository=repository
        ),
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
        toolkit_id="toolkit-1",
        proxy_url=None,
        operations=MCPOAuthRuntimeOperationRepository(
            session_manager=session_manager, connection_repository=repository
        ),
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
        toolkit_id="toolkit-1",
        proxy_url=None,
        operations=MCPOAuthRuntimeOperationRepository(
            session_manager=session_manager, connection_repository=repository
        ),
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
        toolkit_id="toolkit-1",
        proxy_url=None,
        operations=MCPOAuthRuntimeOperationRepository(
            session_manager=session_manager, connection_repository=repository
        ),
    )

    assert connection is not None
    assert connection.status is MCPOAuthConnectionStatus.RECONNECT_REQUIRED
    assert repository.update_calls == 0
    assert repository.reconnect_calls == 1
    assert active[0] == 0
