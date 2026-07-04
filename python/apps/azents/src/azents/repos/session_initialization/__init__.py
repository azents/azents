"""Session initialization repository."""

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from azents.rdb.models.session_initialization import (
    RDBSessionInitialization,
    RDBSessionInitializationEvent,
    RDBSessionInitializationStep,
)

from .data import (
    SessionInitialization,
    SessionInitializationCreate,
    SessionInitializationEvent,
    SessionInitializationEventCreate,
    SessionInitializationStep,
    SessionInitializationStepCreate,
)


class SessionInitializationRepository:
    """Session initialization lifecycle repository."""

    async def create_initialization(
        self,
        session: AsyncSession,
        create: SessionInitializationCreate,
    ) -> SessionInitialization:
        """Create an AgentSession initialization lifecycle row."""
        rdb = RDBSessionInitialization(
            session_id=create.session_id,
            status=create.status,
            failure_summary=create.failure_summary,
            started_at=create.started_at,
            completed_at=create.completed_at,
            failed_at=create.failed_at,
            canceled_at=create.canceled_at,
            cleaned_at=create.cleaned_at,
        )
        session.add(rdb)
        await session.flush()
        return self._build_initialization(rdb)

    async def get_by_session_id(
        self,
        session: AsyncSession,
        *,
        session_id: str,
    ) -> SessionInitialization | None:
        """Fetch initialization lifecycle by AgentSession ID."""
        result = await session.execute(
            sa.select(RDBSessionInitialization).where(
                RDBSessionInitialization.session_id == session_id
            )
        )
        rdb = result.scalar_one_or_none()
        if rdb is None:
            return None
        return self._build_initialization(rdb)

    async def create_step(
        self,
        session: AsyncSession,
        create: SessionInitializationStepCreate,
    ) -> SessionInitializationStep:
        """Create an initialization step."""
        rdb = RDBSessionInitializationStep(
            initialization_id=create.initialization_id,
            session_id=create.session_id,
            sequence=create.sequence,
            step_key=create.step_key,
            step_type=create.step_type,
            blocking=create.blocking,
            retryable=create.retryable,
            depends_on_step_keys=create.depends_on_step_keys,
            resource_descriptors=create.resource_descriptors,
        )
        session.add(rdb)
        await session.flush()
        return self._build_step(rdb)

    async def list_steps(
        self,
        session: AsyncSession,
        *,
        initialization_id: str,
    ) -> list[SessionInitializationStep]:
        """List initialization steps in execution order."""
        result = await session.execute(
            sa.select(RDBSessionInitializationStep)
            .where(RDBSessionInitializationStep.initialization_id == initialization_id)
            .order_by(RDBSessionInitializationStep.sequence)
        )
        return [self._build_step(rdb) for rdb in result.scalars()]

    async def append_event(
        self,
        session: AsyncSession,
        create: SessionInitializationEventCreate,
    ) -> SessionInitializationEvent:
        """Append an initialization event with the next monotonic sequence."""
        await session.execute(
            sa.select(RDBSessionInitialization.id)
            .where(RDBSessionInitialization.id == create.initialization_id)
            .with_for_update()
        )
        result = await session.execute(
            sa.select(
                sa.func.coalesce(sa.func.max(RDBSessionInitializationEvent.sequence), 0)
            ).where(
                RDBSessionInitializationEvent.initialization_id
                == create.initialization_id
            )
        )
        next_sequence = int(result.scalar_one()) + 1
        rdb = RDBSessionInitializationEvent(
            initialization_id=create.initialization_id,
            step_id=create.step_id,
            session_id=create.session_id,
            sequence=next_sequence,
            kind=create.kind,
            command_argv=create.command_argv,
            content=create.content,
            exit_code=create.exit_code,
        )
        session.add(rdb)
        await session.flush()
        return self._build_event(rdb)

    async def list_events(
        self,
        session: AsyncSession,
        *,
        initialization_id: str,
    ) -> list[SessionInitializationEvent]:
        """List initialization events in append order."""
        result = await session.execute(
            sa.select(RDBSessionInitializationEvent)
            .where(RDBSessionInitializationEvent.initialization_id == initialization_id)
            .order_by(RDBSessionInitializationEvent.sequence)
        )
        return [self._build_event(rdb) for rdb in result.scalars()]

    def _build_initialization(
        self,
        rdb: RDBSessionInitialization,
    ) -> SessionInitialization:
        """Convert RDB initialization row to domain model."""
        return SessionInitialization(
            id=rdb.id,
            session_id=rdb.session_id,
            status=rdb.status,
            failure_summary=rdb.failure_summary,
            retry_count=rdb.retry_count,
            started_at=rdb.started_at,
            completed_at=rdb.completed_at,
            failed_at=rdb.failed_at,
            canceled_at=rdb.canceled_at,
            cleaned_at=rdb.cleaned_at,
            created_at=rdb.created_at,
            updated_at=rdb.updated_at,
        )

    def _build_step(
        self,
        rdb: RDBSessionInitializationStep,
    ) -> SessionInitializationStep:
        """Convert RDB initialization step row to domain model."""
        return SessionInitializationStep(
            id=rdb.id,
            initialization_id=rdb.initialization_id,
            session_id=rdb.session_id,
            sequence=rdb.sequence,
            step_key=rdb.step_key,
            step_type=rdb.step_type,
            status=rdb.status,
            blocking=rdb.blocking,
            retryable=rdb.retryable,
            attempt=rdb.attempt,
            depends_on_step_keys=list(rdb.depends_on_step_keys),
            resource_descriptors=list(rdb.resource_descriptors),
            failure_reason=rdb.failure_reason,
            started_at=rdb.started_at,
            completed_at=rdb.completed_at,
            failed_at=rdb.failed_at,
            created_at=rdb.created_at,
            updated_at=rdb.updated_at,
        )

    def _build_event(
        self,
        rdb: RDBSessionInitializationEvent,
    ) -> SessionInitializationEvent:
        """Convert RDB initialization event row to domain model."""
        command_argv = None if rdb.command_argv is None else list(rdb.command_argv)
        return SessionInitializationEvent(
            id=rdb.id,
            initialization_id=rdb.initialization_id,
            step_id=rdb.step_id,
            session_id=rdb.session_id,
            sequence=rdb.sequence,
            kind=rdb.kind,
            command_argv=command_argv,
            content=rdb.content,
            exit_code=rdb.exit_code,
            created_at=rdb.created_at,
        )
