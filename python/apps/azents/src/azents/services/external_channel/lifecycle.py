"""Transaction-bound External Channel lifecycle participant operations."""

import dataclasses
import datetime
from collections.abc import Sequence
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.session_lifecycle import (
    SessionLifecycleParticipantDefinition,
    SessionLifecyclePurgeContext,
    SessionLifecycleTransitionContext,
)
from azents.repos.external_channel.data import (
    ExternalChannelAgentDecommissionCleanup,
    ExternalChannelArchiveTermination,
    ExternalChannelMultiConnectionDisconnect,
    ExternalChannelMultiRouteImpact,
    ExternalChannelMultiRouteRemoval,
    ExternalChannelPurgeCleanup,
    ExternalChannelPurgePreparation,
    ExternalChannelPurgeVerification,
    ExternalChannelRestoreValidation,
)
from azents.repos.external_channel.lifecycle import (
    ExternalChannelLifecycleRepository,
)
from azents.repos.external_channel.work_data import ChannelDeliveryTarget
from azents.services.external_channel.channel_action import (
    ExternalChannelActionService,
)

_PARTICIPANT_KEY = "session.external-channel"


@dataclasses.dataclass
class ExternalChannelLifecycleService:
    """Run External Channel lifecycle work inside caller-owned transactions."""

    repository: Annotated[
        ExternalChannelLifecycleRepository,
        Depends(ExternalChannelLifecycleRepository),
    ]
    action_service: Annotated[
        ExternalChannelActionService,
        Depends(ExternalChannelActionService),
    ]

    async def archive_participant(
        self,
        session: AsyncSession,
        definition: SessionLifecycleParticipantDefinition,
        context: SessionLifecycleTransitionContext,
    ) -> ExternalChannelArchiveTermination | None:
        """Terminate only the External Channel archive participant."""
        if definition.key != _PARTICIPANT_KEY:
            return None
        return await self.repository.terminate_session_tree(
            session,
            session_ids=context.subtree_session_ids,
            now=datetime.datetime.now(datetime.UTC),
        )

    async def restore_participant(
        self,
        session: AsyncSession,
        definition: SessionLifecycleParticipantDefinition,
        context: SessionLifecycleTransitionContext,
    ) -> ExternalChannelRestoreValidation | None:
        """Validate restore without reactivating External Channel state."""
        if definition.key != _PARTICIPANT_KEY:
            return None
        return await self.repository.validate_restore_session_tree(
            session,
            session_ids=context.subtree_session_ids,
        )

    async def prepare_purge_participant(
        self,
        session: AsyncSession,
        definition: SessionLifecycleParticipantDefinition,
        context: SessionLifecyclePurgeContext,
    ) -> ExternalChannelPurgePreparation | None:
        """Prepare durable delivery state without a provider operation."""
        if definition.key != _PARTICIPANT_KEY:
            return None
        return await self.repository.prepare_session_tree_purge(
            session,
            session_ids=context.subtree_session_ids,
            now=datetime.datetime.now(datetime.UTC),
        )

    async def cleanup_purge_participant(
        self,
        session: AsyncSession,
        definition: SessionLifecycleParticipantDefinition,
        context: SessionLifecyclePurgeContext,
    ) -> ExternalChannelPurgeCleanup | None:
        """Remove Session-owned External Channel rows in restrictive order."""
        if definition.key != _PARTICIPANT_KEY:
            return None
        return await self.repository.purge_session_tree(
            session,
            session_ids=context.subtree_session_ids,
        )

    async def verify_purge_participant(
        self,
        session: AsyncSession,
        definition: SessionLifecycleParticipantDefinition,
        context: SessionLifecyclePurgeContext,
    ) -> ExternalChannelPurgeVerification | None:
        """Verify the External Channel purge boundary is empty."""
        if definition.key != _PARTICIPANT_KEY:
            return None
        return await self.repository.verify_session_tree_purged(
            session,
            session_ids=context.subtree_session_ids,
        )

    async def finalize_purge_participant(
        self,
        session: AsyncSession,
        definition: SessionLifecycleParticipantDefinition,
        context: SessionLifecyclePurgeContext,
    ) -> ExternalChannelPurgeVerification | None:
        """Recheck absence immediately before root-tree finalization."""
        return await self.verify_purge_participant(session, definition, context)

    async def cleanup_decommissioned_agent(
        self,
        session: AsyncSession,
        *,
        agent_id: str,
        now: datetime.datetime,
    ) -> ExternalChannelAgentDecommissionCleanup:
        """Remove direct Agent-owned route and authorization state."""
        return await self.repository.cleanup_decommissioned_agent(
            session,
            agent_id=agent_id,
            now=now,
        )

    async def project_multi_route_impact(
        self,
        session: AsyncSession,
        *,
        connection_id: str,
        route_id: str,
    ) -> ExternalChannelMultiRouteImpact | None:
        """Return one internal, sanitized Multi route removal projection."""
        return await self.repository.project_multi_route_impact(
            session,
            connection_id=connection_id,
            route_id=route_id,
        )

    async def remove_multi_route(
        self,
        session: AsyncSession,
        *,
        connection_id: str,
        route_id: str,
        removed_by_user_id: str | None,
        now: datetime.datetime,
    ) -> ExternalChannelMultiRouteRemoval | None:
        """Remove one internal Multi association inside the caller transaction."""
        return await self.repository.remove_multi_route(
            session,
            connection_id=connection_id,
            route_id=route_id,
            removed_by_user_id=removed_by_user_id,
            now=now,
        )

    async def reenable_multi_route(
        self,
        session: AsyncSession,
        *,
        connection_id: str,
        route_id: str,
    ) -> bool:
        """Re-enable one preserved internal Multi association."""
        return await self.repository.reenable_multi_route(
            session,
            connection_id=connection_id,
            route_id=route_id,
        )

    async def disconnect_multi_connection(
        self,
        session: AsyncSession,
        *,
        connection_id: str,
        now: datetime.datetime,
        reason: str,
        defer_provider_state_purge: bool = False,
    ) -> ExternalChannelMultiConnectionDisconnect | None:
        """Disconnect an internal Multi App inside the caller transaction."""
        return await self.repository.disconnect_multi_connection(
            session,
            connection_id=connection_id,
            now=now,
            reason=reason,
            defer_provider_state_purge=defer_provider_state_purge,
        )

    async def consume_archive_cleanup(
        self,
        delivery_ids: Sequence[str],
    ) -> int:
        """Attempt every committed archive provider cleanup once."""
        return await self.action_service.drain_archive_cleanup(delivery_ids)

    async def prepare_cleanup(
        self,
        session: AsyncSession,
        delivery_ids: Sequence[str],
    ) -> tuple[ChannelDeliveryTarget, ...]:
        """Capture provider targets before a terminal transaction purges secrets."""
        targets: list[ChannelDeliveryTarget] = []
        for delivery_id in delivery_ids:
            target = await self.action_service.prepare_delivery_in_session(
                session,
                delivery_id,
            )
            if target is not None:
                targets.append(target)
        return tuple(targets)

    async def purge_decommissioned_provider_state(
        self,
        session: AsyncSession,
        connection_ids: Sequence[str],
    ) -> int:
        """Purge deferred Single-App credentials after target capture."""
        return await self.repository.purge_disconnected_connection_provider_state(
            session,
            connection_ids=connection_ids,
        )

    async def consume_prepared_cleanup(
        self,
        targets: Sequence[ChannelDeliveryTarget],
        purged_connection_ids: Sequence[str],
    ) -> int:
        """Attempt every target once after its terminal transaction commits."""
        purged = frozenset(purged_connection_ids)
        for target in targets:
            if target.connection_id in purged:
                await self.action_service.attempt_captured_terminal_delivery(target)
            else:
                await self.action_service.attempt_prepared_delivery(target)
        return len(targets)
