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


class TestRuntimeConnectionGenerationRepository:
    """Verify monotonic allocation and acceptance fencing."""

    async def test_allocate_and_accept_generation(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        repository = RuntimeConnectionGenerationRepository()
        subject_created_at = await _post_cutover_time(repository, rdb_session)

        first = await repository.allocate_generation(
            rdb_session,
            connection_kind=RuntimeConnectionAuthorityKind.RUNNER,
            subject_id="generation-runtime-1",
            subject_created_at=subject_created_at,
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
            subject_created_at=subject_created_at,
        )
        assert second.high_water_generation == 2
        assert second.accepted_generation == 1
        assert not await repository.generation_is_current_high_water(
            rdb_session,
            connection_kind=RuntimeConnectionAuthorityKind.RUNNER,
            subject_id="generation-runtime-1",
            generation=1,
        )

    async def test_missing_pre_cutover_subject_fails_closed(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        repository = RuntimeConnectionGenerationRepository()
        await _post_cutover_time(repository, rdb_session)
        cutover = await repository.get_cutover(rdb_session)
        assert cutover is not None

        with pytest.raises(
            RuntimeConnectionGenerationIntegrityError,
            match="Pre-cutover Runtime connection subject",
        ):
            await repository.allocate_generation(
                rdb_session,
                connection_kind=RuntimeConnectionAuthorityKind.PROVIDER,
                subject_id="missing-pre-cutover-provider",
                subject_created_at=cutover.cutover_at,
            )

    async def test_exhausted_generation_never_wraps(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        repository = RuntimeConnectionGenerationRepository()
        subject_created_at = await _post_cutover_time(repository, rdb_session)
        rdb_session.add(
            RDBRuntimeConnectionGeneration(
                connection_kind=RuntimeConnectionAuthorityKind.RUNNER,
                subject_id="exhausted-runtime",
                high_water_generation=MAX_CONNECTION_GENERATION,
                accepted_generation=MAX_CONNECTION_GENERATION,
            )
        )
        await rdb_session.flush()

        with pytest.raises(
            RuntimeConnectionGenerationExhausted,
            match="authority is exhausted",
        ):
            await repository.allocate_generation(
                rdb_session,
                connection_kind=RuntimeConnectionAuthorityKind.RUNNER,
                subject_id="exhausted-runtime",
                subject_created_at=subject_created_at,
            )

    async def test_concurrent_first_allocations_are_serialized(
        self,
        rdb_engine: AsyncEngine,
    ) -> None:
        repository = RuntimeConnectionGenerationRepository()
        subject_id = "concurrent-generation-runtime"
        async with AsyncSession(rdb_engine, expire_on_commit=False) as session:
            async with session.begin():
                subject_created_at = await _post_cutover_time(repository, session)

        async def allocate() -> int:
            async with AsyncSession(rdb_engine, expire_on_commit=False) as session:
                async with session.begin():
                    state = await repository.allocate_generation(
                        session,
                        connection_kind=RuntimeConnectionAuthorityKind.RUNNER,
                        subject_id=subject_id,
                        subject_created_at=subject_created_at,
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
