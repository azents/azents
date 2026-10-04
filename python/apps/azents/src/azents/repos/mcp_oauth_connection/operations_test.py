"""Completed MCP OAuth runtime operation tests."""

import datetime
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import MCPOAuthConnectionStatus
from azents.rdb.session_capabilities import ReadWriteSession, WriteSession
from azents.repos.mcp_oauth_connection import MCPOAuthConnectionRepository
from azents.repos.mcp_oauth_connection.data import MCPOAuthConnection
from azents.repos.mcp_oauth_connection.operations import (
    MCPOAuthRuntimeOperationRepository,
)


def _connection(
    *,
    access_token: str = "access-1",
    status: MCPOAuthConnectionStatus = MCPOAuthConnectionStatus.CONNECTED,
    updated_second: int = 0,
) -> MCPOAuthConnection:
    """Build one OAuth credential snapshot."""
    now = datetime.datetime(2026, 10, 1, tzinfo=datetime.UTC)
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
        status=status,
        created_at=now,
        updated_at=now + datetime.timedelta(seconds=updated_second),
    )


async def test_oauth_operations_close_transactions_before_returning() -> None:
    """OAuth load and finalization return only after transactions close."""
    _raw_session = AsyncMock(spec=AsyncSession)
    session = ReadWriteSession(_raw_session)
    transaction_active = False

    @asynccontextmanager
    async def session_manager() -> AsyncIterator[WriteSession]:
        nonlocal transaction_active
        assert not transaction_active
        transaction_active = True
        try:
            yield session
        finally:
            transaction_active = False

    stored = _connection()
    repository = AsyncMock(spec=MCPOAuthConnectionRepository)

    async def get_by_toolkit_id(
        current_session: WriteSession,
        toolkit_id: str,
    ) -> MCPOAuthConnection:
        assert transaction_active
        assert current_session is session
        assert toolkit_id == "toolkit-1"
        return stored

    async def get_by_toolkit_id_for_update(
        current_session: WriteSession,
        toolkit_id: str,
    ) -> MCPOAuthConnection:
        return await get_by_toolkit_id(current_session, toolkit_id)

    async def update_tokens(
        current_session: WriteSession,
        *,
        toolkit_id: str,
        access_token: str,
        refresh_token: str | None,
        expires_at: datetime.datetime | None,
    ) -> MCPOAuthConnection:
        assert transaction_active
        assert current_session is session
        assert toolkit_id == "toolkit-1"
        assert refresh_token == "refresh-2"
        return stored.model_copy(
            update={
                "access_token": access_token,
                "refresh_token": refresh_token,
                "expires_at": expires_at,
            }
        )

    repository.get_by_toolkit_id.side_effect = get_by_toolkit_id
    repository.get_by_toolkit_id_for_update.side_effect = get_by_toolkit_id_for_update
    repository.update_tokens.side_effect = update_tokens
    operations = MCPOAuthRuntimeOperationRepository(
        session_manager=session_manager,
        connection_repository=repository,
    )

    loaded = await operations.load(toolkit_id="toolkit-1")
    assert loaded is stored
    assert not transaction_active

    assert stored.expires_at is not None
    expires_at = stored.expires_at + datetime.timedelta(hours=1)
    refreshed = await operations.finalize_refresh(
        before=stored,
        toolkit_id="toolkit-1",
        access_token="access-2",
        refresh_token="refresh-2",
        expires_at=expires_at,
    )
    assert not transaction_active
    assert refreshed is not None
    assert refreshed.access_token == "access-2"
    assert refreshed.expires_at == expires_at


async def test_oauth_operations_preserve_concurrent_credentials_and_failure_state() -> (
    None
):
    """Stale writes yield to newer credentials and current failures persist."""
    _raw_session = AsyncMock(spec=AsyncSession)
    session = ReadWriteSession(_raw_session)
    transaction_active = False

    @asynccontextmanager
    async def session_manager() -> AsyncIterator[WriteSession]:
        nonlocal transaction_active
        assert not transaction_active
        transaction_active = True
        try:
            yield session
        finally:
            transaction_active = False

    before = _connection()
    peer = _connection(access_token="peer-access", updated_second=1)
    repository = AsyncMock(spec=MCPOAuthConnectionRepository)
    repository.get_by_toolkit_id_for_update.return_value = peer
    operations = MCPOAuthRuntimeOperationRepository(
        session_manager=session_manager,
        connection_repository=repository,
    )

    result = await operations.finalize_refresh(
        before=before,
        toolkit_id="toolkit-1",
        access_token="stale-access",
        refresh_token="stale-refresh",
        expires_at=before.expires_at,
    )
    assert result is peer
    assert not transaction_active
    repository.update_tokens.assert_not_awaited()

    current = _connection()
    reconnect = current.model_copy(
        update={"status": MCPOAuthConnectionStatus.RECONNECT_REQUIRED}
    )
    repository.get_by_toolkit_id_for_update.return_value = current
    repository.get_by_toolkit_id.return_value = reconnect

    failed = await operations.finalize_failure(
        before=current,
        toolkit_id="toolkit-1",
        reconnect_required=True,
    )
    assert failed is reconnect
    assert not transaction_active
    repository.mark_reconnect_required.assert_awaited_once_with(
        session,
        toolkit_id="toolkit-1",
    )
