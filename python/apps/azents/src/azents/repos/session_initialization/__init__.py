"""Session initialization repository."""

import datetime

import sqlalchemy as sa
from azcommon.uuid import uuid7
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    SessionInitializationStatus,
    SessionInitializationStepStatus,
    SessionInitializationStepType,
)
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

    async def create_ready_noop_if_absent(
        self,
        session: AsyncSession,
        *,
        session_id: str,
        completed_at: datetime.datetime,
    ) -> SessionInitialization:
        """Create a ready no-op initialization lifecycle if absent."""
        initialization_id = uuid7().hex
        result = await session.execute(
            pg_insert(RDBSessionInitialization)
            .values(
                id=initialization_id,
                session_id=session_id,
                status=SessionInitializationStatus.READY,
                retry_count=0,
                completed_at=completed_at,
            )
            .on_conflict_do_nothing(
                index_elements=[RDBSessionInitialization.session_id]
            )
            .returning(RDBSessionInitialization)
        )
        rdb = result.scalar_one_or_none()
        if rdb is None:
            existing = await self.get_by_session_id(session, session_id=session_id)
            if existing is None:
                raise RuntimeError("SessionInitialization conflict target not found")
            return existing

        await session.execute(
            pg_insert(RDBSessionInitializationStep)
            .values(
                id=uuid7().hex,
                initialization_id=initialization_id,
                session_id=session_id,
                sequence=1,
                step_key=SessionInitializationStepType.NOOP_READY.value,
                step_type=SessionInitializationStepType.NOOP_READY,
                status=SessionInitializationStepStatus.COMPLETED,
                blocking=False,
                retryable=False,
                attempt=1,
                depends_on_step_keys=[],
                resource_descriptors=[],
                completed_at=completed_at,
            )
            .on_conflict_do_nothing(
                index_elements=[
                    RDBSessionInitializationStep.initialization_id,
                    RDBSessionInitializationStep.step_key,
                ]
            )
        )
        await session.flush()
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

    async def update_initialization_status(
        self,
        session: AsyncSession,
        *,
        initialization_id: str,
        status: SessionInitializationStatus,
        failure_summary: str | None,
        started_at: datetime.datetime | None,
        completed_at: datetime.datetime | None,
        failed_at: datetime.datetime | None,
    ) -> SessionInitialization:
        """Update lifecycle status and milestone timestamps."""
        rdb = await session.get(RDBSessionInitialization, initialization_id)
        if rdb is None:
            raise RuntimeError("SessionInitialization row is missing")
        rdb.status = status
        rdb.failure_summary = failure_summary
        if started_at is not None:
            rdb.started_at = started_at
        if completed_at is not None:
            rdb.completed_at = completed_at
        if failed_at is not None:
            rdb.failed_at = failed_at
        await session.flush()
        await session.refresh(rdb)
        return self._build_initialization(rdb)

    async def update_step_status(
        self,
        session: AsyncSession,
        *,
        step_id: str,
        status: SessionInitializationStepStatus,
        failure_reason: str | None,
        resource_descriptors: list[object] | None,
        started_at: datetime.datetime | None,
        completed_at: datetime.datetime | None,
        failed_at: datetime.datetime | None,
    ) -> SessionInitializationStep:
        """Update a step status and optional execution metadata."""
        rdb = await session.get(RDBSessionInitializationStep, step_id)
        if rdb is None:
            raise RuntimeError("SessionInitializationStep row is missing")
        rdb.status = status
        rdb.failure_reason = failure_reason
        if resource_descriptors is not None:
            rdb.resource_descriptors = resource_descriptors
        if started_at is not None:
            rdb.started_at = started_at
        if completed_at is not None:
            rdb.completed_at = completed_at
        if failed_at is not None:
            rdb.failed_at = failed_at
        await session.flush()
        await session.refresh(rdb)
        return self._build_step(rdb)

    async def reset_for_retry(
        self,
        session: AsyncSession,
        *,
        initialization_id: str,
    ) -> SessionInitialization:
        """Reset failed retryable steps and downstream steps for another attempt."""
        initialization = await session.get(RDBSessionInitialization, initialization_id)
        if initialization is None:
            raise RuntimeError("SessionInitialization row is missing")
        initialization.status = SessionInitializationStatus.PENDING
        initialization.failure_summary = None
        initialization.retry_count += 1
        initialization.started_at = None
        initialization.completed_at = None
        initialization.failed_at = None
        initialization.canceled_at = None
        initialization.cleaned_at = None

        result = await session.execute(
            sa.select(RDBSessionInitializationStep)
            .where(RDBSessionInitializationStep.initialization_id == initialization_id)
            .order_by(RDBSessionInitializationStep.sequence)
        )
        steps = list(result.scalars())
        failed_keys = {
            step.step_key
            for step in steps
            if step.status == SessionInitializationStepStatus.FAILED
        }
        reset_keys = set(failed_keys)
        changed = True
        while changed:
            changed = False
            for step in steps:
                if step.step_key in reset_keys:
                    continue
                if any(key in reset_keys for key in step.depends_on_step_keys):
                    reset_keys.add(step.step_key)
                    changed = True

        for step in steps:
            if step.step_key not in reset_keys:
                continue
            if not step.retryable:
                continue
            step.status = SessionInitializationStepStatus.PENDING
            step.failure_reason = None
            step.resource_descriptors = []
            step.attempt += 1
            step.started_at = None
            step.completed_at = None
            step.failed_at = None

        await session.flush()
        await session.refresh(initialization)
        return self._build_initialization(initialization)

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
