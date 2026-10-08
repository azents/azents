"""Direct authenticated Slack connection-revocation lifecycle handling."""

import dataclasses
import datetime
from typing import Annotated

from fastapi import Depends

from azents.repos.external_channel.connection_revocation_operations import (
    ExternalChannelConnectionRevocationOperations,
)
from azents.services.external_channel.channel_action import (
    ExternalChannelActionService,
)
from azents.services.external_channel.slack_events import SlackConnectionRevocation


@dataclasses.dataclass
class ExternalChannelConnectionRevocationService:
    """Commit a signed Slack revocation before provider acknowledgement."""

    operations: Annotated[
        ExternalChannelConnectionRevocationOperations,
        Depends(ExternalChannelConnectionRevocationOperations),
    ]
    action_service: Annotated[
        ExternalChannelActionService,
        Depends(ExternalChannelActionService.create),
    ]

    async def apply(
        self,
        *,
        connection_id: str,
        revocation: SlackConnectionRevocation,
        required_configuration_generation: int,
        required_socket_lease_owner: str | None,
        now: datetime.datetime,
    ) -> bool:
        """Apply one idempotent lifecycle transition under optional lease fencing."""
        result = await self.operations.apply(
            connection_id=connection_id,
            kind=revocation.kind,
            required_configuration_generation=required_configuration_generation,
            required_socket_lease_owner=required_socket_lease_owner,
            now=now,
        )
        for plan in result.cleanup_plans:
            await self.action_service.execute_terminal_control(plan)
        return result.changed
