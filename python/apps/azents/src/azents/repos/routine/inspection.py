"""Completed authorized read snapshots for Routine inspection."""

from dataclasses import dataclass
from typing import Annotated, assert_never

from azcommon.result import Failure, Result, Success
from fastapi import Depends

from azents.core.routine import (
    MAX_ROUTINE_WORK_RECORDS,
    RoutineDefinition,
    RoutineScope,
    RoutineWorkRecord,
)
from azents.core.routine_execution import RoutineExecutionState
from azents.rdb.deps import get_read_only_session_manager
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import ReadSession
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.routine.definition import RoutineDefinitionRepository
from azents.repos.routine.records import RoutineWorkRecordRepository
from azents.repos.routine.state import RoutineStateRepository
from azents.repos.session_resource_authority import (
    AuthorizedPublicSessionResource,
    PublicSessionResourceDenied,
    PublicSessionResourceNotFound,
    authorize_public_session_resource,
)
from azents.repos.workspace_user import WorkspaceUserRepository

type RoutineInspectionError = (
    PublicSessionResourceDenied | PublicSessionResourceNotFound
)


@dataclass(frozen=True)
class RoutineInventorySnapshot:
    """Definitions belonging only to the requested concrete Session."""

    items: tuple[RoutineDefinition, ...]


@dataclass(frozen=True)
class RoutineDetailSnapshot:
    """Current definition, most recent occurrence and retained work evidence."""

    definition: RoutineDefinition
    execution: RoutineExecutionState | None
    records: tuple[RoutineWorkRecord, ...]


@dataclass(frozen=True)
class RoutineInspectionRepository:
    """Authorize public Session access and finish reads in one read-only scope."""

    session_manager: Annotated[
        SessionManager[ReadSession], Depends(get_read_only_session_manager)
    ]
    sessions: Annotated[AgentSessionRepository, Depends()]
    members: Annotated[WorkspaceUserRepository, Depends()]
    definitions: Annotated[RoutineDefinitionRepository, Depends()]
    records: Annotated[RoutineWorkRecordRepository, Depends()]
    states: Annotated[RoutineStateRepository, Depends()]

    async def _scope(
        self,
        session: ReadSession,
        *,
        agent_id: str,
        session_id: str,
        user_id: str,
    ) -> Result[RoutineScope, RoutineInspectionError]:
        target = await self.sessions.get_by_id(session, session_id)
        if target is None:
            return Failure(PublicSessionResourceNotFound())
        authority = await authorize_public_session_resource(
            session,
            agent_session=target,
            user_id=user_id,
            require_active=True,
            denied_as_not_found=True,
            expected_workspace_id=None,
            expected_agent_id=agent_id,
            agent_session_repository=self.sessions,
            workspace_user_repository=self.members,
        )
        match authority:
            case AuthorizedPublicSessionResource():
                return Success(
                    RoutineScope(
                        workspace_id=target.workspace_id,
                        agent_id=target.agent_id,
                        session_id=target.id,
                    )
                )
            case PublicSessionResourceDenied() | PublicSessionResourceNotFound():
                return Failure(authority)
            case _:
                assert_never(authority)

    async def list_for_session(
        self, *, agent_id: str, session_id: str, user_id: str
    ) -> Result[RoutineInventorySnapshot, RoutineInspectionError]:
        """Read an inventory without falling back to a root or primary Session."""
        async with self.session_manager() as session:
            authorized = await self._scope(
                session, agent_id=agent_id, session_id=session_id, user_id=user_id
            )
            if isinstance(authorized, Failure):
                return authorized
            definitions = await self.definitions.list_for_session(
                session, scope=authorized.value
            )
            return Success(RoutineInventorySnapshot(items=tuple(definitions)))

    async def detail(
        self, *, agent_id: str, session_id: str, user_id: str, slug: str
    ) -> Result[RoutineDetailSnapshot, RoutineInspectionError]:
        """Read one exact definition, latest occurrence and at most 100 records."""
        async with self.session_manager() as session:
            authorized = await self._scope(
                session, agent_id=agent_id, session_id=session_id, user_id=user_id
            )
            if isinstance(authorized, Failure):
                return authorized
            scope = authorized.value
            definition = await self.definitions.get(session, scope=scope, slug=slug)
            if definition is None:
                return Failure(PublicSessionResourceNotFound())
            records = await self.records.list_recent(
                session,
                scope=scope,
                routine_id=definition.id,
                limit=MAX_ROUTINE_WORK_RECORDS,
            )
            execution = await self.states.get_execution(
                session, scope=scope, routine_id=definition.id
            )
            return Success(
                RoutineDetailSnapshot(
                    definition=definition,
                    execution=None if execution is None else execution.state,
                    records=tuple(records),
                )
            )
