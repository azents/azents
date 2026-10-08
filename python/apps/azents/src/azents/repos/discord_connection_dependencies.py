"""Repository composition for completed Discord connection operations."""

from typing import Annotated

from fastapi import Depends

from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import WriteSession
from azents.repos.discord_connection_operations import (
    DiscordConnectionOperationRepository,
)
from azents.repos.external_channel.repository import ExternalChannelRepository


def get_discord_connection_operations(
    session_manager: Annotated[
        SessionManager[WriteSession], Depends(get_session_manager)
    ],
    repository: Annotated[
        ExternalChannelRepository, Depends(ExternalChannelRepository.create)
    ],
) -> DiscordConnectionOperationRepository:
    """Bind database-only connection operations at the dependency boundary."""
    return DiscordConnectionOperationRepository(
        session_manager=session_manager, external_channel_repository=repository
    )
