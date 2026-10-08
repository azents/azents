"""Completed MCP OAuth runtime persistence operations."""

import dataclasses
import datetime

from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import WriteSession
from azents.repos.mcp_oauth_connection import MCPOAuthConnectionRepository
from azents.repos.mcp_oauth_connection.data import MCPOAuthConnection


@dataclasses.dataclass
class MCPOAuthRuntimeOperationRepository:
    """Own completed MCP OAuth preflight and conditional finalization."""

    session_manager: SessionManager[WriteSession]
    connection_repository: MCPOAuthConnectionRepository

    async def load(self, *, toolkit_id: str) -> MCPOAuthConnection | None:
        """Load one connection in a completed transaction."""
        async with self.session_manager() as session:
            return await self.connection_repository.get_by_toolkit_id(
                session,
                toolkit_id,
            )

    async def finalize_refresh(
        self,
        *,
        before: MCPOAuthConnection,
        toolkit_id: str,
        access_token: str,
        refresh_token: str | None,
        expires_at: datetime.datetime | None,
    ) -> MCPOAuthConnection | None:
        """Persist refreshed tokens unless another transaction won the race."""
        async with self.session_manager() as session:
            current = await self.connection_repository.get_by_toolkit_id_for_update(
                session,
                toolkit_id,
            )
            if current is None:
                return None
            if _connection_changed(before, current):
                return current
            return await self.connection_repository.update_tokens(
                session,
                toolkit_id=toolkit_id,
                access_token=access_token,
                refresh_token=refresh_token,
                expires_at=expires_at,
            )

    async def finalize_failure(
        self,
        *,
        before: MCPOAuthConnection,
        toolkit_id: str,
        reconnect_required: bool,
    ) -> MCPOAuthConnection | None:
        """Persist refresh failure unless another transaction changed credentials."""
        async with self.session_manager() as session:
            current = await self.connection_repository.get_by_toolkit_id_for_update(
                session,
                toolkit_id,
            )
            if current is None:
                return None
            if _connection_changed(before, current):
                return current
            if reconnect_required:
                await self.connection_repository.mark_reconnect_required(
                    session,
                    toolkit_id=toolkit_id,
                )
            return await self.connection_repository.get_by_toolkit_id(
                session,
                toolkit_id,
            )


def _connection_changed(
    before: MCPOAuthConnection,
    current: MCPOAuthConnection,
) -> bool:
    """Return whether another transaction changed the credential snapshot."""
    return (
        current.updated_at != before.updated_at
        or current.refresh_token != before.refresh_token
        or current.access_token != before.access_token
        or current.status != before.status
    )
