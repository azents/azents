"""Session lifecycle orchestration boundaries."""

import dataclasses

from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.session_lifecycle import SessionLifecycleRegistry
from azents.repos.archived_session_retention import ArchivedSessionRetentionRepository
from azents.repos.archived_session_retention.data import (
    ArchivedSessionPurgeParticipantSnapshot,
)


@dataclasses.dataclass(frozen=True)
class SessionLifecycleOrchestrator:
    """Own cross-domain lifecycle checkpoints without owning domain cleanup."""

    registry: SessionLifecycleRegistry

    async def materialize_claimed_purge_participants(
        self,
        session: AsyncSession,
        *,
        retention_repository: ArchivedSessionRetentionRepository,
        purge_job_id: str,
        lease_owner: str,
    ) -> None:
        """Persist the active participant/version set in the claim transaction."""
        await retention_repository.materialize_purge_participant_executions(
            session,
            job_id=purge_job_id,
            lease_owner=lease_owner,
            participants=tuple(
                ArchivedSessionPurgeParticipantSnapshot(
                    participant_key=participant.key,
                    policy_version=participant.policy_version,
                )
                for participant in self.registry.participants
            ),
        )
