"""MCP OAuth connection repository."""

import datetime

import sqlalchemy as sa
from azcommon.uuid import uuid7
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.crypto import CredentialCipher
from azents.core.enums import MCPOAuthConnectionStatus
from azents.rdb.models.toolkit import RDBMCPOAuthConnection

from .data import MCPOAuthConnection, MCPOAuthConnectionSummary


class MCPOAuthConnectionRepository:
    """MCP OAuth connection CRUD repository."""

    def __init__(self, cipher: CredentialCipher) -> None:
        """
        :param cipher: Credential encryption/decryption object
        """
        self._cipher = cipher

    async def get_by_toolkit_id(
        self, session: AsyncSession, toolkit_id: str
    ) -> MCPOAuthConnection | None:
        """Fetch an OAuth connection by Toolkit ID.

        :param session: Database session
        :param toolkit_id: Toolkit ID
        :return: Decrypted OAuth connection or None
        """
        result = await session.execute(
            sa.select(RDBMCPOAuthConnection).where(
                RDBMCPOAuthConnection.toolkit_id == toolkit_id
            )
        )
        rdb = result.scalar_one_or_none()
        if rdb is None:
            return None
        return self._build(rdb)

    async def get_by_toolkit_id_for_update(
        self, session: AsyncSession, toolkit_id: str
    ) -> MCPOAuthConnection | None:
        """Fetch an OAuth connection by Toolkit ID with row lock.

        :param session: Database session
        :param toolkit_id: Toolkit ID
        :return: Decrypted OAuth connection or None
        """
        result = await session.execute(
            sa.select(RDBMCPOAuthConnection)
            .where(RDBMCPOAuthConnection.toolkit_id == toolkit_id)
            .with_for_update()
        )
        rdb = result.scalar_one_or_none()
        if rdb is None:
            return None
        return self._build(rdb)

    async def get_summary_by_toolkit_id(
        self, session: AsyncSession, toolkit_id: str
    ) -> MCPOAuthConnectionSummary | None:
        """Fetch a public connection summary by Toolkit ID.

        :param session: Database session
        :param toolkit_id: Toolkit ID
        :return: Public OAuth connection summary or None
        """
        result = await session.execute(
            sa.select(
                RDBMCPOAuthConnection.status,
                RDBMCPOAuthConnection.issuer,
                RDBMCPOAuthConnection.resource,
                RDBMCPOAuthConnection.scope,
                RDBMCPOAuthConnection.expires_at,
            ).where(RDBMCPOAuthConnection.toolkit_id == toolkit_id)
        )
        row = result.one_or_none()
        if row is None:
            return None
        return MCPOAuthConnectionSummary(
            status=row.status,
            issuer=row.issuer,
            resource=row.resource,
            scope=row.scope,
            expires_at=row.expires_at,
        )

    async def upsert_connected(
        self,
        session: AsyncSession,
        *,
        toolkit_id: str,
        issuer: str | None,
        resource: str | None,
        server_url: str,
        authorization_endpoint: str,
        token_endpoint: str,
        registration_endpoint: str | None,
        client_id: str,
        client_secret: str | None,
        token_endpoint_auth_method: str,
        scope: str | None,
        access_token: str | None,
        refresh_token: str | None,
        expires_at: datetime.datetime | None,
    ) -> MCPOAuthConnection:
        """Create or update a connected OAuth connection.

        :param session: Database session
        :param toolkit_id: Toolkit ID
        :param issuer: OAuth issuer
        :param resource: OAuth resource
        :param server_url: MCP server URL
        :param authorization_endpoint: OAuth authorization endpoint
        :param token_endpoint: OAuth token endpoint
        :param registration_endpoint: OAuth DCR registration endpoint
        :param client_id: OAuth client ID
        :param client_secret: OAuth client secret
        :param token_endpoint_auth_method: Token endpoint auth method
        :param scope: OAuth scope string
        :param access_token: OAuth access token
        :param refresh_token: OAuth refresh token
        :param expires_at: Access token expiration timestamp
        :return: Stored OAuth connection
        """
        encrypted_client_id = self._cipher.encrypt(client_id)
        encrypted_client_secret = (
            self._cipher.encrypt(client_secret) if client_secret is not None else None
        )
        encrypted_access_token = (
            self._cipher.encrypt(access_token) if access_token is not None else None
        )
        encrypted_refresh_token = (
            self._cipher.encrypt(refresh_token) if refresh_token is not None else None
        )
        values = {
            "id": uuid7().hex,
            "toolkit_id": toolkit_id,
            "issuer": issuer,
            "resource": resource,
            "server_url": server_url,
            "authorization_endpoint": authorization_endpoint,
            "token_endpoint": token_endpoint,
            "registration_endpoint": registration_endpoint,
            "encrypted_client_id": encrypted_client_id,
            "encrypted_client_secret": encrypted_client_secret,
            "token_endpoint_auth_method": token_endpoint_auth_method,
            "scope": scope,
            "encrypted_access_token": encrypted_access_token,
            "encrypted_refresh_token": encrypted_refresh_token,
            "expires_at": expires_at,
            "status": MCPOAuthConnectionStatus.CONNECTED,
        }
        stmt = (
            pg_insert(RDBMCPOAuthConnection)
            .values(**values)
            .on_conflict_do_update(
                constraint="uq_mcp_oauth_connections_toolkit_id",
                set_={
                    "issuer": issuer,
                    "resource": resource,
                    "server_url": server_url,
                    "authorization_endpoint": authorization_endpoint,
                    "token_endpoint": token_endpoint,
                    "registration_endpoint": registration_endpoint,
                    "encrypted_client_id": encrypted_client_id,
                    "encrypted_client_secret": encrypted_client_secret,
                    "token_endpoint_auth_method": token_endpoint_auth_method,
                    "scope": scope,
                    "encrypted_access_token": encrypted_access_token,
                    "encrypted_refresh_token": encrypted_refresh_token,
                    "expires_at": expires_at,
                    "status": MCPOAuthConnectionStatus.CONNECTED,
                    "updated_at": sa.func.now(),
                },
            )
            .returning(RDBMCPOAuthConnection)
        )
        result = await session.execute(stmt)
        return self._build(result.scalar_one())

    async def update_tokens(
        self,
        session: AsyncSession,
        *,
        toolkit_id: str,
        access_token: str,
        refresh_token: str | None,
        expires_at: datetime.datetime | None,
    ) -> MCPOAuthConnection | None:
        """Update OAuth token fields for a connection.

        :param session: Database session
        :param toolkit_id: Toolkit ID
        :param access_token: OAuth access token
        :param refresh_token: OAuth refresh token; keep old token when None
        :param expires_at: Access token expiration timestamp
        :return: Updated OAuth connection or None
        """
        values: dict[str, object] = {
            "encrypted_access_token": self._cipher.encrypt(access_token),
            "expires_at": expires_at,
            "status": MCPOAuthConnectionStatus.CONNECTED,
            "updated_at": sa.func.now(),
        }
        if refresh_token is not None:
            values["encrypted_refresh_token"] = self._cipher.encrypt(refresh_token)
        stmt = (
            sa.update(RDBMCPOAuthConnection)
            .where(RDBMCPOAuthConnection.toolkit_id == toolkit_id)
            .values(**values)
            .returning(RDBMCPOAuthConnection)
        )
        result = await session.execute(stmt)
        rdb = result.scalar_one_or_none()
        if rdb is None:
            return None
        return self._build(rdb)

    async def mark_reconnect_required(
        self, session: AsyncSession, *, toolkit_id: str
    ) -> None:
        """Mark an OAuth connection as requiring reconnection.

        :param session: Database session
        :param toolkit_id: Toolkit ID
        """
        await session.execute(
            sa.update(RDBMCPOAuthConnection)
            .where(RDBMCPOAuthConnection.toolkit_id == toolkit_id)
            .values(
                status=MCPOAuthConnectionStatus.RECONNECT_REQUIRED,
                updated_at=sa.func.now(),
            )
        )

    async def delete_by_toolkit_id(
        self, session: AsyncSession, toolkit_id: str
    ) -> None:
        """Delete an OAuth connection by Toolkit ID.

        :param session: Database session
        :param toolkit_id: Toolkit ID
        """
        await session.execute(
            sa.delete(RDBMCPOAuthConnection).where(
                RDBMCPOAuthConnection.toolkit_id == toolkit_id
            )
        )

    def _build(self, rdb: RDBMCPOAuthConnection) -> MCPOAuthConnection:
        """Convert RDB model to domain model."""
        return MCPOAuthConnection(
            id=rdb.id,
            toolkit_id=rdb.toolkit_id,
            issuer=rdb.issuer,
            resource=rdb.resource,
            server_url=rdb.server_url,
            authorization_endpoint=rdb.authorization_endpoint,
            token_endpoint=rdb.token_endpoint,
            registration_endpoint=rdb.registration_endpoint,
            client_id=self._cipher.decrypt(rdb.encrypted_client_id),
            client_secret=(
                self._cipher.decrypt(rdb.encrypted_client_secret)
                if rdb.encrypted_client_secret is not None
                else None
            ),
            token_endpoint_auth_method=rdb.token_endpoint_auth_method,
            scope=rdb.scope,
            access_token=(
                self._cipher.decrypt(rdb.encrypted_access_token)
                if rdb.encrypted_access_token is not None
                else None
            ),
            refresh_token=(
                self._cipher.decrypt(rdb.encrypted_refresh_token)
                if rdb.encrypted_refresh_token is not None
                else None
            ),
            expires_at=rdb.expires_at,
            status=rdb.status,
            created_at=rdb.created_at,
            updated_at=rdb.updated_at,
        )
