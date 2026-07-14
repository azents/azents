"""Action execution projection service."""

import datetime

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import ActionExecutionEventKind, ActionExecutionStatus
from azents.rdb.deps import get_session_manager
from azents.rdb.models.event import JSONValue
from azents.rdb.session import SessionManager
from azents.repos.action_execution import ActionExecutionRepository
from azents.repos.action_execution.data import (
    ActionExecution,
    ActionExecutionCreate,
    ActionExecutionEvent,
    ActionExecutionEventCreate,
    ActionExecutionProjection,
)

_ACTION_EXECUTION_REPOSITORY_DEP = Depends(ActionExecutionRepository)
_SESSION_MANAGER_DEP = Depends(get_session_manager)


class ActionExecutionService:
    """Service boundary for live TurnAction execution projections."""

    def __init__(
        self,
        session_manager: SessionManager[AsyncSession] = _SESSION_MANAGER_DEP,
        action_execution_repository: ActionExecutionRepository = (
            _ACTION_EXECUTION_REPOSITORY_DEP
        ),
    ) -> None:
        """Initialize service dependencies."""
        self.session_manager = session_manager
        self.action_execution_repository = action_execution_repository

    async def create_for_input_buffer(
        self,
        *,
        session_id: str,
        input_buffer_id: str,
        action_type: str,
        action: dict[str, JSONValue],
        owner_generation: int,
    ) -> ActionExecution:
        """Create or return execution state for one source input buffer."""
        async with self.session_manager() as session:
            return await self.action_execution_repository.create(
                session,
                ActionExecutionCreate(
                    id=None,
                    session_id=session_id,
                    input_buffer_id=input_buffer_id,
                    action_type=action_type,
                    action=action,
                    status=ActionExecutionStatus.PENDING,
                    owner_generation=owner_generation,
                ),
            )

    async def get_projection_by_input_buffer_id(
        self,
        *,
        input_buffer_id: str,
    ) -> ActionExecutionProjection | None:
        """Fetch execution projection by input buffer identity."""
        async with self.session_manager() as session:
            repository = self.action_execution_repository
            return await repository.get_projection_by_input_buffer_id(
                session,
                input_buffer_id=input_buffer_id,
            )

    async def list_by_session_id(
        self,
        *,
        session_id: str,
    ) -> list[ActionExecution]:
        """List live action executions for a session."""
        async with self.session_manager() as session:
            return await self.action_execution_repository.list_by_session_id(
                session,
                session_id=session_id,
            )

    async def append_event(
        self,
        *,
        action_execution_id: str,
        session_id: str,
        kind: ActionExecutionEventKind,
        step_key: str | None,
        command_argv: list[str] | None,
        content: str | None,
        exit_code: int | None,
    ) -> ActionExecutionEvent:
        """Append one live execution progress event."""
        async with self.session_manager() as session:
            return await self.action_execution_repository.append_event(
                session,
                ActionExecutionEventCreate(
                    action_execution_id=action_execution_id,
                    session_id=session_id,
                    kind=kind,
                    step_key=step_key,
                    command_argv=command_argv,
                    content=content,
                    exit_code=exit_code,
                ),
            )

    async def mark_running(
        self,
        *,
        action_execution_id: str,
    ) -> ActionExecution:
        """Mark an execution running with the current UTC time."""
        async with self.session_manager() as session:
            return await self.action_execution_repository.mark_running(
                session,
                action_execution_id=action_execution_id,
                started_at=datetime.datetime.now(datetime.UTC),
            )
