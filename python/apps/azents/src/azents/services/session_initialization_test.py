"""SessionInitializationService tests."""

import datetime
from contextlib import AbstractAsyncContextManager
from typing import cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import SessionInitializationStatus
from azents.rdb.session import SessionManager
from azents.repos.session_initialization import SessionInitializationRepository
from azents.repos.session_initialization.data import SessionInitialization
from azents.services.session_initialization import (
    SessionInitializationRunGate,
    SessionInitializationService,
)


class _SessionScope(AbstractAsyncContextManager[AsyncSession]):
    """DB session context for tests."""

    async def __aenter__(self) -> AsyncSession:
        """Return test session."""
        return cast(AsyncSession, object())

    async def __aexit__(self, *exc_info: object) -> None:
        """No resources to clean up."""


class _SessionManager:
    """Session manager for tests."""

    def __call__(self) -> _SessionScope:
        """Return new session scope."""
        return _SessionScope()


class _InitializationRepository(SessionInitializationRepository):
    """SessionInitializationRepository test double."""

    def __init__(self, status: SessionInitializationStatus) -> None:
        self.status = status

    async def get_by_session_id(
        self,
        session: AsyncSession,
        *,
        session_id: str,
    ) -> SessionInitialization:
        """Return test initialization."""
        del session
        now = datetime.datetime.now(datetime.UTC)
        return SessionInitialization(
            id="initialization-001",
            session_id=session_id,
            status=self.status,
            failure_summary=None,
            retry_count=0,
            started_at=None,
            completed_at=None,
            failed_at=None,
            canceled_at=None,
            cleaned_at=None,
            created_at=now,
            updated_at=now,
        )


async def _gate_for_status(
    status: SessionInitializationStatus,
) -> SessionInitializationRunGate:
    """Return public service run gate for status."""
    service = SessionInitializationService(
        session_initialization_repository=_InitializationRepository(status),
        session_manager=cast(SessionManager[AsyncSession], _SessionManager()),
    )
    result = await service.get_run_gate(session_id="session-001")
    return result.gate


@pytest.mark.asyncio
async def test_ready_initialization_allows_run_dispatch() -> None:
    """Ready initialization allows run dispatch."""
    assert await _gate_for_status(SessionInitializationStatus.READY) == (
        SessionInitializationRunGate.READY
    )


@pytest.mark.asyncio
async def test_in_progress_initialization_waits_before_run_dispatch() -> None:
    """In-progress initialization waits before run dispatch."""
    assert await _gate_for_status(SessionInitializationStatus.PENDING) == (
        SessionInitializationRunGate.WAITING
    )
    assert await _gate_for_status(SessionInitializationStatus.RUNNING) == (
        SessionInitializationRunGate.WAITING
    )


@pytest.mark.asyncio
async def test_failed_initialization_blocks_run_dispatch() -> None:
    """Failed initialization blocks run dispatch."""
    assert await _gate_for_status(SessionInitializationStatus.FAILED) == (
        SessionInitializationRunGate.BLOCKED
    )
    assert await _gate_for_status(SessionInitializationStatus.CLEANUP_REQUIRED) == (
        SessionInitializationRunGate.BLOCKED
    )


@pytest.mark.asyncio
async def test_terminal_initialization_does_not_allow_run_dispatch() -> None:
    """Terminal initialization states do not allow run dispatch."""
    assert await _gate_for_status(SessionInitializationStatus.CANCELED) == (
        SessionInitializationRunGate.TERMINAL
    )
    assert await _gate_for_status(SessionInitializationStatus.CLEANED) == (
        SessionInitializationRunGate.TERMINAL
    )
