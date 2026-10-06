"""Common terminal/abandoned Session archival using existing lifecycle policy."""

import dataclasses
import datetime
from typing import Annotated

from azcommon.uuid import uuid7
from fastapi import Depends

from azents.core.enums import AgentSessionRunState, AgentSessionStatus
from azents.core.external_channel_provider_effect import ProviderEffectPlan
from azents.core.session_lifecycle import (
    SessionArchiveMutation,
    SessionLifecycleTransitionContext,
)
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import WriteSession
from azents.repos.agent_execution import AgentRunRepository
from azents.repos.hierarchy_contention import retry_hierarchy_operation
from azents.repos.lifecycle_target import LifecycleTargetRepository
from azents.repos.session_execution import CanonicalExecutionOwnerGenerationStaleError
from azents.repos.session_lifecycle_operations import (
    SessionLifecycleOperationsRepository,
)


@dataclasses.dataclass(frozen=True)
class ArchivedLifecycleTarget:
    """Committed lifecycle identity and external participant plans for the host."""

    root_session_id: str
    session_ids: tuple[str, ...]
    cleanup_plans: tuple[ProviderEffectPlan, ...]


@dataclasses.dataclass(frozen=True)
class SessionArchiveOperations:
    """Archive settled common executions without fabricated Conversation data."""

    session_manager: Annotated[
        SessionManager[WriteSession], Depends(get_session_manager)
    ]
    targets: Annotated[LifecycleTargetRepository, Depends(LifecycleTargetRepository)]
    run_repository: Annotated[AgentRunRepository, Depends(AgentRunRepository)]
    lifecycle: Annotated[
        SessionLifecycleOperationsRepository,
        Depends(SessionLifecycleOperationsRepository),
    ]

    @retry_hierarchy_operation
    async def archive(
        self, *, root_session_id: str, expected_owner_generation: int
    ) -> ArchivedLifecycleTarget | None:
        """Archive a settled target and retain its canonical payload until purge."""
        async with self.session_manager() as session:
            members = await self.targets.lock_target_sessions(
                session, root_session_id=root_session_id
            )
            if not members:
                return None
            root = next(item for item in members if item.id == root_session_id)
            if root.owner_generation != expected_owner_generation:
                raise CanonicalExecutionOwnerGenerationStaleError(
                    "Session owner generation is stale"
                )
            if root.status is AgentSessionStatus.ARCHIVED:
                return None
            ids = tuple(item.id for item in members)
            if any(item.run_state is AgentSessionRunState.RUNNING for item in members):
                raise ValueError("Session execution is still active.")
            if await self.run_repository.has_active_for_session_ids(
                session, session_ids=ids
            ):
                raise ValueError("Session has active AgentRuns.")
            plans = await self.lifecycle.archive(
                session,
                SessionArchiveMutation(
                    context=SessionLifecycleTransitionContext(
                        transition_id=uuid7().hex,
                        root_session_id=root_session_id,
                        subtree_session_ids=ids,
                    ),
                    archived_at=datetime.datetime.now(datetime.UTC),
                ),
            )
            return ArchivedLifecycleTarget(
                root_session_id=root_session_id,
                session_ids=ids,
                cleanup_plans=plans,
            )
