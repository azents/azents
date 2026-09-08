"""Durable Runtime connection-generation authority repository tests."""

import asyncio
import datetime
from datetime import UTC

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from azents.core.enums import RuntimeConnectionAuthorityKind
from azents.rdb.models.runtime_connection_generation import (
    RDBRuntimeConnectionGeneration,
    RDBRuntimeConnectionGenerationCutover,
)

from .data import (
    RuntimeConnectionGenerationExhausted,
    RuntimeConnectionGenerationIntegrityError,
)
from .repository import (
    MAX_CONNECTION_GENERATION,
    RuntimeConnectionGenerationRepository,
)


async def _post_cutover_time(
    repository: RuntimeConnectionGenerationRepository,
    session: AsyncSession,
) -> datetime.datetime:
    cutover = await repository.get_cutover(session)
    if cutover is None:
        cutover_at = datetime.datetime.now(UTC)
        session.add(
            RDBRuntimeConnectionGenerationCutover(
                allocator_version=1,
                cutover_at=cutover_at,
            )
        )
        await session.flush()
    else:
        cutover_at = cutover.cutover_at
    return cutover_at + datetime.timedelta(microseconds=1)


async def _activate_subject(
    repository: RuntimeConnectionGenerationRepository,
    session: AsyncSession,
    *,
    connection_kind: RuntimeConnectionAuthorityKind,
    subject_id: str,
    high_water_generation: int = 0,
    accepted_generation: int = 0,
) -> None:
    """Create the Phase 2 activation state required by repository primitives."""
    await _post_cutover_time(repository, session)
    session.add(
        RDBRuntimeConnectionGeneration(
            connection_kind=connection_kind,
            subject_id=subject_id,
            high_water_generation=high_water_generation,
            accepted_generation=accepted_generation,
        )
    )
    await session.flush()


class TestRuntimeConnectionGenerationRepository:
    """Verify monotonic allocation and acceptance fencing."""

    async def test_allocate_and_accept_generation(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        repository = RuntimeConnectionGenerationRepository()
        await _activate_subject(
            repository,
            rdb_session,
            connection_kind=RuntimeConnectionAuthorityKind.RUNNER,
            subject_id="generation-runtime-1",
        )

        first = await repository.allocate_generation(
            rdb_session,
            connection_kind=RuntimeConnectionAuthorityKind.RUNNER,
            subject_id="generation-runtime-1",
        )
        assert first.high_water_generation == 1
        assert first.accepted_generation == 0
        assert await repository.generation_is_current_high_water(
            rdb_session,
            connection_kind=RuntimeConnectionAuthorityKind.RUNNER,
            subject_id="generation-runtime-1",
            generation=1,
        )

        accepted = await repository.accept_generation(
            rdb_session,
            connection_kind=RuntimeConnectionAuthorityKind.RUNNER,
            subject_id="generation-runtime-1",
            generation=1,
        )
        assert accepted is not None
        assert accepted.accepted_generation == 1
        assert (
            await repository.accept_generation(
                rdb_session,
                connection_kind=RuntimeConnectionAuthorityKind.RUNNER,
                subject_id="generation-runtime-1",
                generation=1,
            )
            is None
        )

        second = await repository.allocate_generation(
            rdb_session,
            connection_kind=RuntimeConnectionAuthorityKind.RUNNER,
            subject_id="generation-runtime-1",
        )
        assert second.high_water_generation == 2
        assert second.accepted_generation == 1
        assert not await repository.generation_is_current_high_water(
            rdb_session,
            connection_kind=RuntimeConnectionAuthorityKind.RUNNER,
            subject_id="generation-runtime-1",
            generation=1,
        )

    async def test_missing_subject_fails_closed(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        repository = RuntimeConnectionGenerationRepository()
        await _post_cutover_time(repository, rdb_session)

        with pytest.raises(
            RuntimeConnectionGenerationIntegrityError,
            match="generation state is missing",
        ):
            await repository.allocate_generation(
                rdb_session,
                connection_kind=RuntimeConnectionAuthorityKind.PROVIDER,
                subject_id="missing-provider",
            )

    async def test_missing_subject_preflight_fails_closed(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        repository = RuntimeConnectionGenerationRepository()
        await _post_cutover_time(repository, rdb_session)

        with pytest.raises(
            RuntimeConnectionGenerationIntegrityError,
            match="generation state is missing",
        ):
            await repository.generation_is_current_high_water(
                rdb_session,
                connection_kind=RuntimeConnectionAuthorityKind.PROVIDER,
                subject_id="missing-preflight-provider",
                generation=1,
            )

    async def test_missing_subject_acceptance_fails_closed(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        repository = RuntimeConnectionGenerationRepository()
        await _post_cutover_time(repository, rdb_session)

        with pytest.raises(
            RuntimeConnectionGenerationIntegrityError,
            match="generation state is missing",
        ):
            await repository.accept_generation(
                rdb_session,
                connection_kind=RuntimeConnectionAuthorityKind.RUNNER,
                subject_id="missing-acceptance-runtime",
                generation=1,
            )

    async def test_exhausted_generation_never_wraps(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        repository = RuntimeConnectionGenerationRepository()
        await _activate_subject(
            repository,
            rdb_session,
            connection_kind=RuntimeConnectionAuthorityKind.RUNNER,
            subject_id="exhausted-runtime",
            high_water_generation=MAX_CONNECTION_GENERATION,
            accepted_generation=MAX_CONNECTION_GENERATION,
        )

        with pytest.raises(
            RuntimeConnectionGenerationExhausted,
            match="authority is exhausted",
        ):
            await repository.allocate_generation(
                rdb_session,
                connection_kind=RuntimeConnectionAuthorityKind.RUNNER,
                subject_id="exhausted-runtime",
            )

    async def test_concurrent_first_allocations_are_serialized(
        self,
        rdb_engine: AsyncEngine,
    ) -> None:
        repository = RuntimeConnectionGenerationRepository()
        subject_id = "concurrent-generation-runtime"
        async with AsyncSession(rdb_engine, expire_on_commit=False) as session:
            async with session.begin():
                await _activate_subject(
                    repository,
                    session,
                    connection_kind=RuntimeConnectionAuthorityKind.RUNNER,
                    subject_id=subject_id,
                )

        async def allocate() -> int:
            async with AsyncSession(rdb_engine, expire_on_commit=False) as session:
                async with session.begin():
                    state = await repository.allocate_generation(
                        session,
                        connection_kind=RuntimeConnectionAuthorityKind.RUNNER,
                        subject_id=subject_id,
                    )
                    return state.high_water_generation

        try:
            generations = await asyncio.gather(allocate(), allocate())
            assert sorted(generations) == [1, 2]
        finally:
            async with AsyncSession(rdb_engine) as session:
                async with session.begin():
                    await session.execute(
                        sa.delete(RDBRuntimeConnectionGeneration).where(
                            RDBRuntimeConnectionGeneration.connection_kind
                            == RuntimeConnectionAuthorityKind.RUNNER,
                            RDBRuntimeConnectionGeneration.subject_id == subject_id,
                        )
                    )
                    await session.execute(
                        sa.delete(RDBRuntimeConnectionGenerationCutover).where(
                            RDBRuntimeConnectionGenerationCutover.allocator_version == 1
                        )
                    )
