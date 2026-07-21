"""Transaction-bound External Channel lifecycle participant operations."""

import dataclasses
import datetime
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
    ExternalChannelPurgeCleanup,
    ExternalChannelPurgePreparation,
    ExternalChannelPurgeVerification,
    ExternalChannelRestoreValidation,
)
from azents.repos.external_channel.lifecycle import (
    ExternalChannelLifecycleRepository,
)

_PARTICIPANT_KEY = "session.external-channel"


@dataclasses.dataclass
class ExternalChannelLifecycleService:
    """Run External Channel lifecycle work inside caller-owned transactions."""

    repository: Annotated[
        ExternalChannelLifecycleRepository,
        Depends(ExternalChannelLifecycleRepository),
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
