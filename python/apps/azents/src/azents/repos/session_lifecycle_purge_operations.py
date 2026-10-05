"""Completed Session lifecycle purge checkpoint operations."""

import dataclasses
import datetime
from typing import Annotated

from fastapi import Depends

from azents.core.enums import ArchivedSessionPurgeParticipantPhase
from azents.core.session_lifecycle import SessionLifecycleRegistry
from azents.core.session_lifecycle_purge import (
    SessionLifecyclePurgePolicy,
    SessionLifecyclePurgeSnapshotValidationFailure,
)
from azents.core.session_lifecycle_registry import get_session_lifecycle_registry
from azents.rdb.deps import get_read_only_session_manager, get_session_manager
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import ReadSession, WriteSession
from azents.repos.archived_session_retention import (
    ArchivedSessionPurgeParticipantSnapshotInvalid,
    ArchivedSessionRetentionRepository,
)
from azents.repos.archived_session_retention.data import (
    ArchivedSessionPurgeParticipantExecution,
    ArchivedSessionPurgeParticipantSnapshot,
)


@dataclasses.dataclass
class SessionLifecyclePurgeOperations:
    """Own checkpoint scopes, leaving external participant execution to services."""

    session_manager: Annotated[
        SessionManager[WriteSession], Depends(get_session_manager)
    ]
    read_only_session_manager: Annotated[
        SessionManager[ReadSession], Depends(get_read_only_session_manager)
    ]
    retention_repository: Annotated[
        ArchivedSessionRetentionRepository, Depends(ArchivedSessionRetentionRepository)
    ]
    registry: Annotated[
        SessionLifecycleRegistry, Depends(get_session_lifecycle_registry)
    ]

    async def materialize_claimed_purge_participants(
        self,
        session: WriteSession,
        *,
        retention_repository: ArchivedSessionRetentionRepository,
        purge_job_id: str,
        lease_owner: str,
    ) -> None:
        """Materialize once or validate the existing immutable participant snapshot."""
        try:
            executions = (
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
            )
        except ArchivedSessionPurgeParticipantSnapshotInvalid as error:
            raise SessionLifecyclePurgeSnapshotValidationFailure(
                participant_key=error.participant_key,
                error=error,
            ) from error
        SessionLifecyclePurgePolicy(self.registry)._require_purge_snapshot_participants(
            executions
        )

    async def list_executions(
        self, *, job_id: str
    ) -> list[ArchivedSessionPurgeParticipantExecution]:
        """Complete the list_executions participant checkpoint operation."""
        async with self.read_only_session_manager() as session:
            return await self.retention_repository.list_purge_participant_executions(
                session, job_id=job_id
            )

    async def block(
        self,
        *,
        job_id: str,
        lease_owner: str,
        participant_key: str,
        blocked_by_participant_key: str,
        now: datetime.datetime,
    ) -> bool:
        """Complete the block participant checkpoint operation."""
        async with self.session_manager() as session:
            return await self.retention_repository.mark_purge_participant_blocked(
                session,
                job_id=job_id,
                lease_owner=lease_owner,
                participant_key=participant_key,
                blocked_by_participant_key=blocked_by_participant_key,
                now=now,
            )

    async def start(
        self,
        *,
        job_id: str,
        lease_owner: str,
        participant_key: str,
        now: datetime.datetime,
    ) -> bool:
        """Complete the start participant checkpoint operation."""
        async with self.session_manager() as session:
            return await self.retention_repository.start_purge_participant_attempt(
                session,
                job_id=job_id,
                lease_owner=lease_owner,
                participant_key=participant_key,
                now=now,
            )

    async def fail(
        self,
        *,
        job_id: str,
        lease_owner: str,
        participant_key: str,
        phase: ArchivedSessionPurgeParticipantPhase,
        error_kind: str,
        error_summary: str,
        now: datetime.datetime,
    ) -> bool:
        """Complete the fail participant checkpoint operation."""
        async with self.session_manager() as session:
            return await self.retention_repository.record_purge_participant_failure(
                session,
                job_id=job_id,
                lease_owner=lease_owner,
                participant_key=participant_key,
                phase=phase,
                error_kind=error_kind,
                error_summary=error_summary,
                now=now,
            )

    async def checkpoint(
        self,
        *,
        job_id: str,
        lease_owner: str,
        participant_key: str,
        phase: ArchivedSessionPurgeParticipantPhase,
        operational_summary: dict[str, object] | None,
        now: datetime.datetime,
    ) -> bool:
        """Complete the checkpoint participant checkpoint operation."""
        async with self.session_manager() as session:
            return await self.retention_repository.checkpoint_purge_participant(
                session,
                job_id=job_id,
                lease_owner=lease_owner,
                participant_key=participant_key,
                phase=phase,
                operational_summary=operational_summary,
                now=now,
            )
