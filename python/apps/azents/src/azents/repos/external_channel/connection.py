"""Completed database operations for External Channel connections."""

import dataclasses
import datetime
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import ExternalChannelConnectionStatus
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.external_channel.data import (
    ExternalChannelConnection,
    ExternalChannelConnectionConfiguration,
    ExternalChannelConnectionCreate,
    ExternalChannelConnectionHealthUpdate,
)
from azents.repos.external_channel.repository import ExternalChannelRepository


@dataclasses.dataclass
class ExternalChannelConnectionRepository:
    """Own completed database-only External Channel connection operations."""

    repository: Annotated[
        ExternalChannelRepository,
        Depends(ExternalChannelRepository.create),
    ]
    session_manager: Annotated[
        SessionManager[AsyncSession],
        Depends(get_session_manager),
    ]

    async def create_connection(
        self,
        *,
        create: ExternalChannelConnectionCreate,
    ) -> ExternalChannelConnection:
        """Atomically persist and return one provider connection."""
        async with self.session_manager() as session:
            return await self.repository.create_connection(session, create)

    async def load_connection_configuration(
        self,
        *,
        workspace_id: str,
        connection_id: str,
    ) -> ExternalChannelConnectionConfiguration | None:
        """Load one Workspace-owned configuration after closing its transaction."""
        async with self.session_manager() as session:
            configuration = await self.repository.get_connection_configuration(
                session,
                connection_id=connection_id,
            )
        if configuration is None or configuration.workspace_id != workspace_id:
            return None
        return configuration

    async def update_connection_health(
        self,
        *,
        connection_id: str,
        status: ExternalChannelConnectionStatus,
        provider_tenant_id: str | None,
        provider_bot_user_id: str | None,
        capabilities: dict[str, object] | None,
        checked_at: datetime.datetime,
        expected_encrypted_credentials: str,
        expected_configuration_generation: int,
    ) -> ExternalChannelConnectionHealthUpdate:
        """Persist one fenced health result and distinguish missing from stale state."""
        async with self.session_manager() as session:
            connection = await self.repository.update_connection_health(
                session,
                connection_id=connection_id,
                status=status,
                provider_tenant_id=provider_tenant_id,
                provider_bot_user_id=provider_bot_user_id,
                capabilities=capabilities,
                checked_at=checked_at,
                expected_encrypted_credentials=expected_encrypted_credentials,
                expected_configuration_generation=expected_configuration_generation,
            )
            if connection is not None:
                return ExternalChannelConnectionHealthUpdate(
                    connection=connection,
                    connection_exists=True,
                )
            current = await self.repository.get_connection(
                session,
                connection_id=connection_id,
            )
            return ExternalChannelConnectionHealthUpdate(
                connection=None,
                connection_exists=current is not None,
            )
