"""Orchestrate completed External Channel selector operations."""

import datetime
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends

from azents.core.external_channel_selection import (
    ExternalChannelSelectorCatalog,
    ExternalChannelSelectorSelection,
)
from azents.repos.external_channel.selector_operations import (
    ExternalChannelSelectorOperations,
)


@dataclass
class ExternalChannelSelectorService:
    operations: Annotated[
        ExternalChannelSelectorOperations, Depends(ExternalChannelSelectorOperations)
    ]

    async def project_catalog(
        self,
        *,
        selector_interaction_id: str,
        principal_id: str,
        search: str | None,
        offset: int,
        now: datetime.datetime,
    ) -> ExternalChannelSelectorCatalog:
        """Load one bounded catalog page from trusted selector state."""
        return await self.operations.project_catalog(
            selector_interaction_id=selector_interaction_id,
            principal_id=principal_id,
            search=search,
            offset=offset,
            now=now,
        )

    async def select_route(
        self,
        *,
        selector_interaction_id: str,
        principal_id: str,
        route_id: str,
        now: datetime.datetime,
    ) -> ExternalChannelSelectorSelection:
        """Apply one immutable trusted route choice."""
        return await self.operations.select_route(
            selector_interaction_id=selector_interaction_id,
            principal_id=principal_id,
            route_id=route_id,
            now=now,
        )

    async def validate_discord_component_scope(
        self,
        *,
        selector_interaction_id: str,
        principal_id: str,
        guild_id: str | None,
        channel_id: str | None,
        now: datetime.datetime,
    ) -> None:
        """Revalidate Discord component actor and conversation scope."""
        return await self.operations.validate_discord_component_scope(
            selector_interaction_id=selector_interaction_id,
            principal_id=principal_id,
            guild_id=guild_id,
            channel_id=channel_id,
            now=now,
        )
