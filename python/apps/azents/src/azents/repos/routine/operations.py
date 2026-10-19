"""Completed database-only Routine definition owner operations."""

from dataclasses import dataclass

import sqlalchemy as sa

from azents.core.enums import AgentLifecycleStatus, AgentSessionStatus
from azents.core.routine import (
    MAX_ROUTINES_PER_SESSION,
    RoutineChanges,
    RoutineContent,
    RoutineDefinition,
    RoutineLimitReached,
    RoutineScope,
    RoutineUnavailable,
)
from azents.core.session_resource_authority import SessionExecutionOwner
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.agent_session import RDBAgentSession
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import ReadSession, WriteSession
from azents.repos.routine.definition import RoutineDefinitionRepository
from azents.repos.session_execution.ownership import fence_owned_session_mutation


@dataclass(frozen=True)
class RoutineOperations:
    """Keep transaction handles private to persistence composition."""

    session_manager: SessionManager[WriteSession]
    read_session_manager: SessionManager[ReadSession]
    definitions: RoutineDefinitionRepository

    async def list_routines(self, *, scope: RoutineScope) -> list[RoutineDefinition]:
        """Read the inventory after checking its exact current owners."""
        async with self.read_session_manager() as session:
            await self._require_scope(session, scope=scope)
            return await self.definitions.list_for_session(session, scope=scope)

    async def get(self, *, scope: RoutineScope, slug: str) -> RoutineDefinition | None:
        """Read an exact definition without a write transaction or row gate."""
        async with self.read_session_manager() as session:
            await self._require_scope(session, scope=scope)
            return await self.definitions.get(session, scope=scope, slug=slug)

    async def create(
        self,
        *,
        scope: RoutineScope,
        content: RoutineContent,
        owner: SessionExecutionOwner | None,
    ) -> RoutineDefinition:
        """Serialize the Session limit with archive and competing creation."""
        async with self.session_manager() as session:
            await self._fence_scope(session, scope=scope, owner=owner)
            if (
                await self.definitions.count(session, scope=scope)
                >= MAX_ROUTINES_PER_SESSION
            ):
                raise RoutineLimitReached("The Session already has 20 Routines.")
            return await self.definitions.create(session, scope=scope, content=content)

    async def update(
        self,
        *,
        scope: RoutineScope,
        slug: str,
        expected: RoutineContent,
        changes: RoutineChanges,
        owner: SessionExecutionOwner | None,
    ) -> RoutineDefinition:
        """Commit exact compare-and-update under the current Session owner."""
        async with self.session_manager() as session:
            await self._fence_scope(session, scope=scope, owner=owner)
            return await self.definitions.update(
                session, scope=scope, slug=slug, expected=expected, changes=changes
            )

    async def delete(
        self,
        *,
        scope: RoutineScope,
        slug: str,
        owner: SessionExecutionOwner | None,
    ) -> RoutineDefinition:
        """Commit definition removal without deleting admitted execution state."""
        async with self.session_manager() as session:
            await self._fence_scope(session, scope=scope, owner=owner)
            return await self.definitions.delete(session, scope=scope, slug=slug)

    async def _require_scope(
        self, session: ReadSession, *, scope: RoutineScope
    ) -> None:
        """Fail closed for a wrong Workspace, Agent, or inactive Session."""
        found = await session.read_session.scalar(
            sa.select(RDBAgentSession.id)
            .join(RDBAgent, RDBAgent.id == RDBAgentSession.agent_id)
            .where(
                RDBAgentSession.id == scope.session_id,
                RDBAgentSession.agent_id == scope.agent_id,
                RDBAgentSession.workspace_id == scope.workspace_id,
                RDBAgentSession.status == AgentSessionStatus.ACTIVE,
                RDBAgent.workspace_id == scope.workspace_id,
                RDBAgent.lifecycle_status == AgentLifecycleStatus.ACTIVE,
            )
        )
        if found is None:
            raise RoutineUnavailable("Routine Session is not active or authorized.")

    async def _fence_scope(
        self,
        session: WriteSession,
        *,
        scope: RoutineScope,
        owner: SessionExecutionOwner | None,
    ) -> None:
        """Preserve Agent-to-Session ordering and fence the actual mutation."""
        if owner is not None and owner.session_id != scope.session_id:
            raise RoutineUnavailable("Routine execution owner does not match Session.")
        agent = await session.write_session.scalar(
            sa.select(RDBAgent.id)
            .where(
                RDBAgent.id == scope.agent_id,
                RDBAgent.workspace_id == scope.workspace_id,
                RDBAgent.lifecycle_status == AgentLifecycleStatus.ACTIVE,
            )
            .with_for_update(read=True, key_share=True)
        )
        if agent is None:
            raise RoutineUnavailable("Routine Agent is not active or authorized.")
        target = await session.write_session.scalar(
            sa.select(RDBAgentSession.id)
            .where(
                RDBAgentSession.id == scope.session_id,
                RDBAgentSession.agent_id == scope.agent_id,
                RDBAgentSession.workspace_id == scope.workspace_id,
                RDBAgentSession.status == AgentSessionStatus.ACTIVE,
            )
            .with_for_update()
        )
        if target is None:
            raise RoutineUnavailable("Routine Session is not active or authorized.")
        if owner is not None:
            await fence_owned_session_mutation(session, owner)
