"""Completed Discord settings origin reads."""

import dataclasses

from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import WriteSession
from azents.repos.external_channel.data import ExternalChannelInteraction
from azents.repos.external_channel.repository import ExternalChannelRepository


@dataclasses.dataclass
class DiscordSettingsReadRepository:
    """Own completed Discord settings control-origin reads."""

    session_manager: SessionManager[WriteSession]
    external_channel_repository: ExternalChannelRepository

    async def get_interaction(
        self,
        interaction_id: str,
    ) -> ExternalChannelInteraction | None:
        """Return one detached origin Interaction after its transaction closes."""
        async with self.session_manager() as session:
            return await self.external_channel_repository.lock_interaction(
                session,
                interaction_id=interaction_id,
            )
