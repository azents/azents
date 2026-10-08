"""Explicit common execution validation and exact critical mutation fencing."""

import dataclasses

from azents.core.session_execution_data import SessionExecutionRecord
from azents.core.session_resource_authority import SessionExecutionOwner
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import ReadSession, WriteSession
from azents.repos.session_execution import CanonicalExecutionOwnerGenerationStaleError
from azents.repos.session_execution_record import SessionExecutionRecordRepository


async def validate_session_execution_owner(
    session: ReadSession,
    owner: SessionExecutionOwner,
) -> SessionExecutionRecord:
    """Observe one common execution owner without locking across external I/O."""
    current = await SessionExecutionRecordRepository().get_by_id(
        session, owner.session_id
    )
    if current is None:
        raise ValueError("AgentSession not found")
    if current.owner_generation != owner.owner_generation:
        raise CanonicalExecutionOwnerGenerationStaleError(
            "Session owner generation is stale"
        )
    return current


async def fence_owned_session_mutation(
    session: WriteSession,
    owner: SessionExecutionOwner,
) -> SessionExecutionRecord:
    """Exclude handover through this critical operation's dependent write commit.

    The common record does not require a public Conversation. Only the exact
    owner-row mutation, not a descriptive read or an unrelated INSERT, admits
    dependent writes against ownership handover.
    """
    current = await SessionExecutionRecordRepository().fence_owner(session, owner)
    if current is None:
        await validate_session_execution_owner(session, owner)
        raise CanonicalExecutionOwnerGenerationStaleError(
            "Session owner generation is stale"
        )
    return current


@dataclasses.dataclass(frozen=True)
class SessionExecutionAuthorityRepository:
    """Completed nonlocking admission observation before an external effect."""

    session_manager: SessionManager[ReadSession]
    owner: SessionExecutionOwner

    async def assert_current(self) -> None:
        """Reject an observed stale owner; final result writes fence independently."""
        async with self.session_manager() as session:
            await validate_session_execution_owner(session, self.owner)
