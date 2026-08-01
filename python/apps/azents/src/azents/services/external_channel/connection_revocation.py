"""Direct authenticated Slack connection-revocation lifecycle handling."""

import dataclasses
import datetime
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import ExternalChannelConnectionStatus
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.external_channel.repository import ExternalChannelRepository
from azents.repos.external_channel.work_data import ChannelDeliveryTarget
from azents.services.external_channel.channel_action import (
    ExternalChannelActionService,
)
from azents.services.external_channel.slack_events import SlackConnectionRevocation


@dataclasses.dataclass
class ExternalChannelConnectionRevocationService:
    """Commit a signed Slack revocation before provider acknowledgement."""

    session_manager: Annotated[
        SessionManager[AsyncSession],
        Depends(get_session_manager),
    ]
    repository: Annotated[
        ExternalChannelRepository,
        Depends(ExternalChannelRepository),
    ]
    action_service: Annotated[
        ExternalChannelActionService,
        Depends(ExternalChannelActionService),
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
        cleanup_targets: list[ChannelDeliveryTarget] = []
        async with self.session_manager() as session:
            if revocation.kind == "app_uninstalled":
                cleanup_ids = (
                    await self.repository.terminate_connection_for_provider_event(
                        session,
                        connection_id=connection_id,
                        status=ExternalChannelConnectionStatus.DISCONNECTED,
                        reason=revocation.kind,
                        now=now,
                        required_configuration_generation=(
                            required_configuration_generation
                        ),
                        required_socket_lease_owner=required_socket_lease_owner,
                        defer_provider_state_purge=True,
                    )
                )
                if cleanup_ids is None:
                    await session.commit()
                    return False
                for delivery_id in cleanup_ids:
                    target = await self.action_service.prepare_delivery_in_session(
                        session,
                        delivery_id,
                    )
                    if target is not None:
                        cleanup_targets.append(target)
                purged = (
                    await self.repository.purge_disconnected_connection_provider_state(
                        session,
                        connection_id=connection_id,
                    )
                )
                if not purged:
                    raise RuntimeError(
                        "Disconnected External Channel provider state disappeared."
                    )
            else:
                changed = await self.repository.mark_connection_reconnect_required(
                    session,
                    connection_id=connection_id,
                    reason=revocation.kind,
                    now=now,
                    required_configuration_generation=(
                        required_configuration_generation
                    ),
                    required_socket_lease_owner=required_socket_lease_owner,
                )
                if not changed:
                    await session.commit()
                    return False
            await session.commit()
        for target in cleanup_targets:
            await self.action_service.attempt_captured_terminal_delivery(target)
        return True
