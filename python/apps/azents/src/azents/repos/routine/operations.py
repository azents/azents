"""Completed database-only Routine definition owner operations."""

from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends

from azents.core.routine import (
    MAX_ROUTINES_PER_SESSION,
    RoutineChanges,
    RoutineContent,
    RoutineDefinition,
    RoutineLimitReached,
    RoutineScope,
    RoutineWorkRecord,
)
from azents.core.session_resource_authority import SessionExecutionOwner
from azents.rdb.deps import get_read_only_session_manager, get_session_manager
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import ReadSession, WriteSession
from azents.repos.routine.definition import RoutineDefinitionRepository
from azents.repos.routine.records import RoutineWorkRecordRepository
from azents.repos.routine.scope import fence_routine_scope, require_routine_scope


@dataclass(frozen=True)
class RoutineInspection:
    """Current exact content and a bounded recent work-record page."""

    definition: RoutineDefinition
    records: tuple[RoutineWorkRecord, ...]


@dataclass(frozen=True)
class RoutineOperations:
    """Keep transaction handles private to persistence composition."""

    session_manager: Annotated[
        SessionManager[WriteSession], Depends(get_session_manager)
    ]
    read_session_manager: Annotated[
        SessionManager[ReadSession], Depends(get_read_only_session_manager)
    ]
    definitions: Annotated[RoutineDefinitionRepository, Depends()]
    records: Annotated[RoutineWorkRecordRepository, Depends()]

    async def list_routines(self, *, scope: RoutineScope) -> list[RoutineDefinition]:
        """Read the inventory after checking its exact current owners."""
        async with self.read_session_manager() as session:
            await require_routine_scope(session, scope=scope)
            return await self.definitions.list_for_session(session, scope=scope)

    async def get(self, *, scope: RoutineScope, slug: str) -> RoutineDefinition | None:
        """Read an exact definition without a write transaction or row gate."""
        async with self.read_session_manager() as session:
            await require_routine_scope(session, scope=scope)
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
            await fence_routine_scope(session, scope=scope, owner=owner)
            if (
                await self.definitions.count(session, scope=scope)
                >= MAX_ROUTINES_PER_SESSION
            ):
                raise RoutineLimitReached("The Session already has 20 Routines.")
            return await self.definitions.create(session, scope=scope, content=content)

    async def inspect(
        self, *, scope: RoutineScope, slug: str, record_limit: int
    ) -> RoutineInspection | None:
        """Read current content and records without exporting a transaction handle."""
        async with self.read_session_manager() as session:
            await require_routine_scope(session, scope=scope)
            definition = await self.definitions.get(session, scope=scope, slug=slug)
            if definition is None:
                return None
            records = await self.records.list_recent(
                session, scope=scope, routine_id=definition.id, limit=record_limit
            )
            return RoutineInspection(definition=definition, records=tuple(records))

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
            await fence_routine_scope(session, scope=scope, owner=owner)
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
            await fence_routine_scope(session, scope=scope, owner=owner)
            return await self.definitions.delete(session, scope=scope, slug=slug)
