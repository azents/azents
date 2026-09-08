"""Durable Runtime Control connection-generation authority repository."""

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import RuntimeConnectionAuthorityKind
from azents.core.runtime_connection_generation import (
    MAX_RUNTIME_CONNECTION_GENERATION,
)
from azents.rdb.models.runtime_connection_generation import (
    RDBRuntimeConnectionGeneration,
    RDBRuntimeConnectionGenerationCutover,
)

from .data import (
    RuntimeConnectionGeneration,
    RuntimeConnectionGenerationCutover,
    RuntimeConnectionGenerationExhausted,
    RuntimeConnectionGenerationIntegrityError,
)

CURRENT_ALLOCATOR_VERSION = 1
MAX_CONNECTION_GENERATION = MAX_RUNTIME_CONNECTION_GENERATION


class RuntimeConnectionGenerationRepository:
    """Allocate and accept durable Provider and Runner connection generations."""

    async def get_cutover(
        self,
        session: AsyncSession,
    ) -> RuntimeConnectionGenerationCutover | None:
        """Return the current allocator cutover marker."""
        rdb = await session.get(
            RDBRuntimeConnectionGenerationCutover,
            CURRENT_ALLOCATOR_VERSION,
        )
        return self._build_cutover(rdb) if rdb is not None else None

    async def get_generation(
        self,
        session: AsyncSession,
        *,
        connection_kind: RuntimeConnectionAuthorityKind,
        subject_id: str,
    ) -> RuntimeConnectionGeneration | None:
        """Return durable generation state for one connection subject."""
        rdb = await session.get(
            RDBRuntimeConnectionGeneration,
            (connection_kind, subject_id),
        )
        return self._build_generation(rdb) if rdb is not None else None

    async def allocate_generation(
        self,
        session: AsyncSession,
        *,
        connection_kind: RuntimeConnectionAuthorityKind,
        subject_id: str,
    ) -> RuntimeConnectionGeneration:
        """Allocate the next generation while retaining every committed gap."""
        cutover = await self.get_cutover(session)
        if cutover is None:
            raise RuntimeConnectionGenerationIntegrityError(
                "Runtime connection generation cutover marker is missing"
            )

        rdb = await self._get_generation_for_update(
            session,
            connection_kind=connection_kind,
            subject_id=subject_id,
        )
        if rdb is None:
            raise RuntimeConnectionGenerationIntegrityError(
                "Runtime connection generation state is missing"
            )

        if rdb.high_water_generation >= MAX_CONNECTION_GENERATION:
            raise RuntimeConnectionGenerationExhausted(
                "Runtime connection generation authority is exhausted"
            )
        rdb.high_water_generation += 1
        await session.flush()
        await session.refresh(rdb)
        return self._build_generation(rdb)

    async def generation_is_current_high_water(
        self,
        session: AsyncSession,
        *,
        connection_kind: RuntimeConnectionAuthorityKind,
        subject_id: str,
        generation: int,
    ) -> bool:
        """Return whether a publication candidate remains the latest allocation."""
        rdb = await session.get(
            RDBRuntimeConnectionGeneration,
            (connection_kind, subject_id),
        )
        if rdb is None:
            raise RuntimeConnectionGenerationIntegrityError(
                "Runtime connection generation state is missing"
            )
        return rdb.high_water_generation == generation

    async def accept_generation(
        self,
        session: AsyncSession,
        *,
        connection_kind: RuntimeConnectionAuthorityKind,
        subject_id: str,
        generation: int,
    ) -> RuntimeConnectionGeneration | None:
        """Accept a generation only while it remains the latest allocation."""
        result = await session.execute(
            sa.update(RDBRuntimeConnectionGeneration)
            .where(
                RDBRuntimeConnectionGeneration.connection_kind == connection_kind,
                RDBRuntimeConnectionGeneration.subject_id == subject_id,
                RDBRuntimeConnectionGeneration.high_water_generation == generation,
                RDBRuntimeConnectionGeneration.accepted_generation < generation,
            )
            .values(accepted_generation=generation, updated_at=sa.func.now())
            .returning(RDBRuntimeConnectionGeneration)
        )
        rdb = result.scalar_one_or_none()
        if rdb is not None:
            return self._build_generation(rdb)
        existing = await session.get(
            RDBRuntimeConnectionGeneration,
            (connection_kind, subject_id),
        )
        if existing is None:
            raise RuntimeConnectionGenerationIntegrityError(
                "Runtime connection generation state is missing"
            )
        return None

    async def _get_generation_for_update(
        self,
        session: AsyncSession,
        *,
        connection_kind: RuntimeConnectionAuthorityKind,
        subject_id: str,
    ) -> RDBRuntimeConnectionGeneration | None:
        result = await session.execute(
            sa.select(RDBRuntimeConnectionGeneration)
            .where(
                RDBRuntimeConnectionGeneration.connection_kind == connection_kind,
                RDBRuntimeConnectionGeneration.subject_id == subject_id,
            )
            .with_for_update()
        )
        return result.scalar_one_or_none()

    @staticmethod
    def _build_cutover(
        rdb: RDBRuntimeConnectionGenerationCutover,
    ) -> RuntimeConnectionGenerationCutover:
        return RuntimeConnectionGenerationCutover(
            allocator_version=rdb.allocator_version,
            cutover_at=rdb.cutover_at,
        )

    @staticmethod
    def _build_generation(
        rdb: RDBRuntimeConnectionGeneration,
    ) -> RuntimeConnectionGeneration:
        return RuntimeConnectionGeneration(
            connection_kind=rdb.connection_kind,
            subject_id=rdb.subject_id,
            high_water_generation=rdb.high_water_generation,
            accepted_generation=rdb.accepted_generation,
            created_at=rdb.created_at,
            updated_at=rdb.updated_at,
        )
