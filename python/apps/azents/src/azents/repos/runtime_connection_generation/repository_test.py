"""Durable Runtime connection-generation authority repository tests."""

import asyncio
import datetime
from datetime import UTC
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from azents.core.enums import RuntimeConnectionAuthorityKind
from azents.rdb.models.runtime_connection_generation import (
    RDBRuntimeConnectionGeneration,
    RDBRuntimeConnectionGenerationCutover,
)
from azents.rdb.session_capabilities import ReadWriteSession, WriteSession

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
    session: WriteSession,
) -> datetime.datetime:
    cutover = await repository.get_cutover(session)
    if cutover is None:
        cutover_at = datetime.datetime.now(UTC)
        session.write_session.add(
            RDBRuntimeConnectionGenerationCutover(
                allocator_version=1,
                cutover_at=cutover_at,
            )
        )
        await session.write_session.flush()
    else:
        cutover_at = cutover.cutover_at
    return cutover_at + datetime.timedelta(microseconds=1)


async def _activate_subject(
    repository: RuntimeConnectionGenerationRepository,
    session: WriteSession,
    *,
    connection_kind: RuntimeConnectionAuthorityKind,
    subject_id: str,
    high_water_generation: int = 0,
    accepted_generation: int = 0,
) -> None:
    """Create the Phase 2 activation state required by repository primitives."""
    await _post_cutover_time(repository, session)
    session.write_session.add(
        RDBRuntimeConnectionGeneration(
            connection_kind=connection_kind,
            subject_id=subject_id,
            high_water_generation=high_water_generation,
            accepted_generation=accepted_generation,
        )
    )
    await session.write_session.flush()


async def _activate_owned_subject(
    repository: RuntimeConnectionGenerationRepository,
    session: WriteSession,
    *,
    subject_id: str,
) -> datetime.datetime | None:
    """Remember whether this fixture created the shared immutable marker."""
    previous = await repository.get_cutover(session)
    await _activate_subject(
        repository,
        session,
        connection_kind=RuntimeConnectionAuthorityKind.RUNNER,
        subject_id=subject_id,
    )
    current = await repository.get_cutover(session)
    assert current is not None
    return current.cutover_at if previous is None else None


async def _cleanup_owned_subject(
    session: WriteSession,
    *,
    subject_id: str,
    created_cutover_at: datetime.datetime | None,
) -> None:
    """Remove fixture-owned state without erasing authority reused by others."""
    await session.write_session.execute(
        sa.delete(RDBRuntimeConnectionGeneration).where(
            RDBRuntimeConnectionGeneration.connection_kind
            == RuntimeConnectionAuthorityKind.RUNNER,
            RDBRuntimeConnectionGeneration.subject_id == subject_id,
        )
    )
    if created_cutover_at is not None:
        await session.write_session.execute(
            sa.delete(RDBRuntimeConnectionGenerationCutover).where(
                RDBRuntimeConnectionGenerationCutover.allocator_version == 1,
                RDBRuntimeConnectionGenerationCutover.cutover_at == created_cutover_at,
                ~sa.exists(sa.select(RDBRuntimeConnectionGeneration.subject_id)),
            )
        )


class TestRuntimeConnectionGenerationRepository:
    """Verify monotonic allocation and acceptance fencing."""

    async def test_allocate_and_accept_generation(
        self,
        rdb_session: WriteSession,
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
        rdb_session: WriteSession,
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
        rdb_session: WriteSession,
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
        rdb_session: WriteSession,
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
        rdb_session: WriteSession,
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
        latest_db_schema: None,
    ) -> None:
        repository = RuntimeConnectionGenerationRepository()
        subject_id = uuid4().hex
        async with AsyncSession(rdb_engine, expire_on_commit=False) as _raw_session:
            session = ReadWriteSession(_raw_session)
            async with session.write_session.begin():
                previous_cutover = await repository.get_cutover(session)
                created_cutover_at = await _activate_owned_subject(
                    repository,
                    session,
                    subject_id=subject_id,
                )

        async def allocate() -> int:
            async with AsyncSession(rdb_engine, expire_on_commit=False) as _raw_session:
                session = ReadWriteSession(_raw_session)
                async with session.write_session.begin():
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
            async with AsyncSession(rdb_engine) as _raw_session:
                session = ReadWriteSession(_raw_session)
                async with session.write_session.begin():
                    await _cleanup_owned_subject(
                        session,
                        subject_id=subject_id,
                        created_cutover_at=created_cutover_at,
                    )
                    if previous_cutover is not None:
                        assert await repository.get_cutover(session) == previous_cutover


@pytest.mark.parametrize("preexisting", [False, True])
async def test_owned_subject_cleanup_restores_cutover_baseline(
    rdb_session: WriteSession, preexisting: bool
) -> None:
    """Absent/preexisting authority is restored inside the rolled-back test scope."""
    repository = RuntimeConnectionGenerationRepository()
    # This fixture rolls back the marker scenario; committed migration state survives.
    await rdb_session.write_session.execute(
        sa.delete(RDBRuntimeConnectionGenerationCutover).where(
            RDBRuntimeConnectionGenerationCutover.allocator_version == 1
        )
    )
    if preexisting:
        await _post_cutover_time(repository, rdb_session)
    previous = await repository.get_cutover(rdb_session)
    subject_id = uuid4().hex
    created_at = await _activate_owned_subject(
        repository, rdb_session, subject_id=subject_id
    )
    assert (created_at is None) is preexisting
    await _cleanup_owned_subject(
        rdb_session, subject_id=subject_id, created_cutover_at=created_at
    )
    assert await repository.get_cutover(rdb_session) == previous
    assert (
        await repository.get_generation(
            rdb_session,
            connection_kind=RuntimeConnectionAuthorityKind.RUNNER,
            subject_id=subject_id,
        )
        is None
    )


async def test_owned_marker_cleanup_preserves_other_subject_authority(
    rdb_session: WriteSession,
) -> None:
    """A marker created by this fixture remains when another subject has reused it."""
    repository = RuntimeConnectionGenerationRepository()
    await rdb_session.write_session.execute(
        sa.delete(RDBRuntimeConnectionGenerationCutover).where(
            RDBRuntimeConnectionGenerationCutover.allocator_version == 1
        )
    )
    own_subject = uuid4().hex
    other_subject = uuid4().hex
    created_at = await _activate_owned_subject(
        repository, rdb_session, subject_id=own_subject
    )
    assert created_at is not None
    await _activate_subject(
        repository,
        rdb_session,
        connection_kind=RuntimeConnectionAuthorityKind.PROVIDER,
        subject_id=other_subject,
    )
    previous = await repository.get_cutover(rdb_session)
    other_state = await repository.get_generation(
        rdb_session,
        connection_kind=RuntimeConnectionAuthorityKind.PROVIDER,
        subject_id=other_subject,
    )
    await _cleanup_owned_subject(
        rdb_session, subject_id=own_subject, created_cutover_at=created_at
    )
    assert await repository.get_cutover(rdb_session) == previous
    assert (
        await repository.get_generation(
            rdb_session,
            connection_kind=RuntimeConnectionAuthorityKind.PROVIDER,
            subject_id=other_subject,
        )
        == other_state
    )
