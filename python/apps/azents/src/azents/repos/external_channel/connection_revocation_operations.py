"""Atomic authenticated connection revocation operations."""

import dataclasses
import datetime
from typing import Annotated, Literal

from fastapi import Depends

from azents.core.enums import ExternalChannelConnectionStatus
from azents.core.external_channel_provider_effect import ProviderEffectPlan
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import WriteSession
from azents.repos.external_channel.repository import ExternalChannelRepository


@dataclasses.dataclass(frozen=True)
class ConnectionRevocationOutcome:
    """Committed lifecycle result and captured post-commit cleanup authority."""

    changed: bool
    cleanup_plans: tuple[ProviderEffectPlan, ...]


@dataclasses.dataclass(frozen=True)
class ExternalChannelConnectionRevocationOperations:
    """Own the conditional lifecycle mutation and provider-state purge together."""

    session_manager: Annotated[
        SessionManager[WriteSession], Depends(get_session_manager)
    ]
    repository: Annotated[
        ExternalChannelRepository, Depends(ExternalChannelRepository.create)
    ]

    async def apply(
        self,
        *,
        connection_id: str,
        kind: Literal["app_uninstalled", "tokens_revoked"],
        required_configuration_generation: int,
        required_socket_lease_owner: str | None,
        now: datetime.datetime,
    ) -> ConnectionRevocationOutcome:
        """Complete one fenced revocation and return only detached cleanup plans."""
        cleanup_plans: tuple[ProviderEffectPlan, ...] = ()
        async with self.session_manager() as session:
            if kind == "app_uninstalled":
                captured_plans = (
                    await self.repository.terminate_connection_for_provider_event(
                        session,
                        connection_id=connection_id,
                        status=ExternalChannelConnectionStatus.DISCONNECTED,
                        reason=kind,
                        now=now,
                        required_configuration_generation=(
                            required_configuration_generation
                        ),
                        required_socket_lease_owner=required_socket_lease_owner,
                        defer_provider_state_purge=True,
                    )
                )
                if captured_plans is None:
                    await session.write_session.commit()
                    return ConnectionRevocationOutcome(changed=False, cleanup_plans=())
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
                    reason=kind,
                    now=now,
                    required_configuration_generation=(
                        required_configuration_generation
                    ),
                    required_socket_lease_owner=required_socket_lease_owner,
                )
                if not changed:
                    await session.write_session.commit()
                    return ConnectionRevocationOutcome(changed=False, cleanup_plans=())
            await session.write_session.commit()
        return ConnectionRevocationOutcome(changed=True, cleanup_plans=cleanup_plans)
