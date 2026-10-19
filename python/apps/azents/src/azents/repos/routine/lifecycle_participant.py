"""Routine participant in the existing Session purge checkpoint protocol."""

from collections.abc import Sequence
from dataclasses import asdict, dataclass
from typing import Annotated

from fastapi import Depends

from azents.core.session_lifecycle import (
    SessionLifecycleParticipantDefinition,
    SessionLifecyclePurgeContext,
)
from azents.rdb.session_capabilities import ReadSession, WriteSession
from azents.repos.routine.lifecycle import (
    RoutineLifecycleCleanup,
    RoutineLifecycleRepository,
    RoutineLifecycleVerification,
)

ROUTINE_PARTICIPANT_KEY = "session.routine"


@dataclass(frozen=True)
class RoutineLifecycleParticipantRepository:
    """Keep all cleanup inside the native database participant transaction."""

    repository: Annotated[RoutineLifecycleRepository, Depends()]

    async def has_started_work(
        self, session: ReadSession, *, session_ids: Sequence[str]
    ) -> bool:
        """Keep preserved work's current owner alive while generic purge waits."""
        return await self.repository.has_preservable_started_work(
            session, session_ids=session_ids
        )

    async def prepare_purge_participant(
        self,
        session: WriteSession,
        definition: SessionLifecycleParticipantDefinition,
        context: SessionLifecyclePurgeContext,
    ) -> RoutineLifecycleVerification | None:
        if definition.key != ROUTINE_PARTICIPANT_KEY:
            return None
        return await self.repository.require_purge_ready(
            session, session_ids=context.subtree_session_ids
        )

    async def cleanup_purge_participant(
        self,
        session: WriteSession,
        definition: SessionLifecycleParticipantDefinition,
        context: SessionLifecyclePurgeContext,
    ) -> RoutineLifecycleCleanup | None:
        if definition.key != ROUTINE_PARTICIPANT_KEY:
            return None
        return await self.repository.purge_session_tree(
            session, session_ids=context.subtree_session_ids
        )

    async def verify_purge_participant(
        self,
        session: WriteSession,
        definition: SessionLifecycleParticipantDefinition,
        context: SessionLifecyclePurgeContext,
    ) -> RoutineLifecycleVerification | None:
        if definition.key != ROUTINE_PARTICIPANT_KEY:
            return None
        result = await self.repository.verify_session_tree(
            session, session_ids=context.subtree_session_ids
        )
        if any(asdict(result).values()):
            raise RuntimeError("Routine purge cleanup is incomplete.")
        return result

    async def finalize_purge_participant(
        self,
        session: WriteSession,
        definition: SessionLifecycleParticipantDefinition,
        context: SessionLifecyclePurgeContext,
    ) -> RoutineLifecycleVerification | None:
        return await self.verify_purge_participant(session, definition, context)

    @staticmethod
    def summary_dict(
        summary: RoutineLifecycleVerification | RoutineLifecycleCleanup,
    ) -> dict[str, object]:
        return asdict(summary)
