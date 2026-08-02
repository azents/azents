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
from azents.services.external_channel.channel_action import (
    ExternalChannelActionService,
)
from azents.services.external_channel.provider_effect import ProviderEffectPlan
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
        cleanup_plans: tuple[ProviderEffectPlan, ...] = ()
        async with self.session_manager() as session:
            if revocation.kind == "app_uninstalled":
                captured_plans = (
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
                if captured_plans is None:
                    await session.commit()
                    return False
                cleanup_plans = captured_plans
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
        for plan in cleanup_plans:
            await self.action_service.execute_terminal_control(plan)
        return True
