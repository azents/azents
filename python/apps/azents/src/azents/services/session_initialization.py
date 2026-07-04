"""Session initialization lifecycle service."""

import dataclasses
import datetime
import enum
from typing import Annotated, assert_never

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import SessionInitializationStatus
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.session_initialization import SessionInitializationRepository
from azents.repos.session_initialization.data import (
    SessionInitialization,
    SessionInitializationEvent,
    SessionInitializationStep,
)


class SessionInitializationRunGate(enum.StrEnum):
    """Run dispatch decision from session initialization state."""

    READY = "ready"
    WAITING = "waiting"
    BLOCKED = "blocked"
    TERMINAL = "terminal"


@dataclasses.dataclass(frozen=True)
class SessionInitializationRunGateResult:
    """Session initialization gate decision for run dispatch."""

    gate: SessionInitializationRunGate
    initialization: SessionInitialization


@dataclasses.dataclass(frozen=True)
class SessionInitializationProjection:
    """Compact initialization state for live chat projections."""

    initialization: SessionInitialization
    steps: list[SessionInitializationStep]


@dataclasses.dataclass(frozen=True)
class SessionInitializationDetail:
    """Durable initialization detail for the session panel."""

    initialization: SessionInitialization
    steps: list[SessionInitializationStep]
    events: list[SessionInitializationEvent]


@dataclasses.dataclass(frozen=True)
class SessionInitializationService:
    """Own AgentSession initialization lifecycle orchestration."""

    session_initialization_repository: Annotated[
        SessionInitializationRepository, Depends(SessionInitializationRepository)
    ]
    session_manager: Annotated[
        SessionManager[AsyncSession], Depends(get_session_manager)
    ]

    async def ensure_ready_noop_initialization(
        self,
        session: AsyncSession,
        *,
        session_id: str,
    ) -> SessionInitialization:
        """Ensure an ordinary session has a ready no-op initialization row."""
        return await self.session_initialization_repository.create_ready_noop_if_absent(
            session,
            session_id=session_id,
            completed_at=datetime.datetime.now(datetime.UTC),
        )

    async def get_run_gate(
        self,
        *,
        session_id: str,
    ) -> SessionInitializationRunGateResult:
        """Return whether initialization allows run dispatch."""
        async with self.session_manager() as session:
            get_initialization = (
                self.session_initialization_repository.get_by_session_id
            )
            initialization = await get_initialization(
                session,
                session_id=session_id,
            )
        if initialization is None:
            raise RuntimeError("SessionInitialization row is missing")
        return SessionInitializationRunGateResult(
            gate=_gate_for_status(initialization.status),
            initialization=initialization,
        )

    async def get_projection(
        self,
        session: AsyncSession,
        *,
        session_id: str,
    ) -> SessionInitializationProjection:
        """Return compact initialization state for live surfaces."""
        get_initialization = self.session_initialization_repository.get_by_session_id
        initialization = await get_initialization(
            session,
            session_id=session_id,
        )
        if initialization is None:
            raise RuntimeError("SessionInitialization row is missing")
        steps = await self.session_initialization_repository.list_steps(
            session,
            initialization_id=initialization.id,
        )
        return SessionInitializationProjection(
            initialization=initialization,
            steps=steps,
        )

    async def get_detail(
        self,
        session: AsyncSession,
        *,
        session_id: str,
    ) -> SessionInitializationDetail:
        """Return durable initialization detail for an AgentSession."""
        projection = await self.get_projection(session, session_id=session_id)
        events = await self.session_initialization_repository.list_events(
            session,
            initialization_id=projection.initialization.id,
        )
        return SessionInitializationDetail(
            initialization=projection.initialization,
            steps=projection.steps,
            events=events,
        )


def _gate_for_status(
    status: SessionInitializationStatus,
) -> SessionInitializationRunGate:
    """Map durable initialization status to run dispatch gate."""
    match status:
        case SessionInitializationStatus.READY:
            return SessionInitializationRunGate.READY
        case SessionInitializationStatus.PENDING | SessionInitializationStatus.RUNNING:
            return SessionInitializationRunGate.WAITING
        case (
            SessionInitializationStatus.FAILED
            | SessionInitializationStatus.CLEANUP_REQUIRED
        ):
            return SessionInitializationRunGate.BLOCKED
        case SessionInitializationStatus.CANCELED | SessionInitializationStatus.CLEANED:
            return SessionInitializationRunGate.TERMINAL
        case _:
            assert_never(status)
