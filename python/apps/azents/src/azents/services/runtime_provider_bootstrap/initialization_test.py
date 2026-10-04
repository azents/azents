"""Deterministic optional Platform Runtime initialization races."""

import asyncio
import datetime
from uuid import uuid4

import pytest
import sqlalchemy as sa
from azcommon.datetime import tznow
from sqlalchemy.ext.asyncio import AsyncEngine

from azents.core.enums import (
    RuntimeProviderAvailabilityMode,
    RuntimeProviderBootstrapAdapterKind,
    RuntimeProviderKind,
)
from azents.core.runtime_provider_bootstrap import (
    RuntimeProviderBootstrapDeclarationInput,
    RuntimeProviderBootstrapSnapshot,
)
from azents.core.system_setting import (
    SystemSettingSection,
    SystemSettingValidationStatus,
    SystemSettingVersionConflict,
)
from azents.core.system_setting_data import (
    StoredSystemSetting,
    SystemSettingCandidateCreate,
    SystemSettingCurrentWrite,
)
from azents.rdb.models.runtime_provider import RDBRuntimeProvider
from azents.rdb.models.runtime_provider_bootstrap import (
    RDBRuntimeProviderAuditEvent,
    RDBRuntimeProviderBootstrapDeclaration,
    RDBRuntimeProviderBootstrapSource,
)
from azents.rdb.models.system_setting import (
    RDBSystemSetting,
    RDBSystemSettingAuditEvent,
    RDBSystemSettingCandidate,
)
from azents.rdb.session_capabilities import (
    WriteSession,
    create_read_only_session_manager,
    create_read_write_session_manager,
)
from azents.repos.runtime_provider.repository import RuntimeProviderRepository
from azents.repos.runtime_provider_binding.repository import (
    RuntimeProviderAuthBindingRepository,
)
from azents.repos.runtime_provider_bootstrap_operations import (
    RuntimeProviderBootstrapOperations,
)
from azents.repos.system_setting.repository import SystemSettingRepository
from azents.services.runtime_provider_bootstrap.service import (
    RuntimeProviderBootstrapService,
)


def _write(provider_id: str) -> SystemSettingCurrentWrite:
    return SystemSettingCurrentWrite(
        section=SystemSettingSection.PLATFORM_RUNTIME,
        schema_version=1,
        version=1,
        config={"default_provider_id": provider_id},
        encrypted_secrets=None,
        secret_metadata={},
        validation_status=None,
        validated_generation=None,
        validation_metadata=None,
        validated_at=None,
        updated_by_user_id=None,
    )


def _candidate() -> SystemSettingCandidateCreate:
    now = tznow()
    return SystemSettingCandidateCreate(
        id=uuid4().hex,
        section=SystemSettingSection.PLATFORM_RUNTIME,
        schema_version=1,
        base_version=0,
        config={"default_provider_id": "admin-provider"},
        encrypted_secrets=None,
        secret_metadata={},
        validation_status=SystemSettingValidationStatus.PENDING,
        created_by_user_id=None,
        created_at=now,
        updated_at=now,
        expires_at=now + datetime.timedelta(minutes=15),
    )


async def _cleanup(session: WriteSession) -> None:
    for model in (
        RDBSystemSettingCandidate,
        RDBSystemSettingAuditEvent,
        RDBSystemSetting,
    ):
        await session.write_session.execute(
            sa.delete(model).where(
                model.section == SystemSettingSection.PLATFORM_RUNTIME
            )
        )


class _PausedInitializationRepository(SystemSettingRepository):
    def __init__(self, reached: asyncio.Event, proceed: asyncio.Event) -> None:
        self.reached = reached
        self.proceed = proceed

    async def initialize_current_if_unchanged(
        self,
        session: WriteSession,
        *,
        write: SystemSettingCurrentWrite,
    ) -> StoredSystemSetting | None:
        self.reached.set()
        await self.proceed.wait()
        return await super().initialize_current_if_unchanged(session, write=write)


@pytest.mark.asyncio
async def test_admin_winner_does_not_roll_back_bootstrap_provider(
    rdb_engine: AsyncEngine, latest_db_schema: None
) -> None:
    """An exact CAS loss skips the optional seed but commits the Provider."""
    writes = create_read_write_session_manager(rdb_engine)
    reads = create_read_only_session_manager(rdb_engine)
    reached, proceed = asyncio.Event(), asyncio.Event()
    providers = RuntimeProviderRepository()
    provider_id = f"bootstrap-{uuid4().hex}"
    source_key = f"helm/default/{uuid4().hex}"
    service = RuntimeProviderBootstrapService(
        operations=RuntimeProviderBootstrapOperations(
            session_manager=writes,
            repository=providers,
            system_setting_repository=_PausedInitializationRepository(reached, proceed),
            binding_repository=RuntimeProviderAuthBindingRepository(),
        )
    )
    snapshot = RuntimeProviderBootstrapSnapshot(
        source_key=source_key,
        adapter_kind=RuntimeProviderBootstrapAdapterKind.HELM_FILE,
        source_revision="r1",
        source_digest="digest-r1",
        declarations=(
            RuntimeProviderBootstrapDeclarationInput(
                declaration_key="provider",
                provider_logical_id=provider_id,
                kind=RuntimeProviderKind.DOCKER,
                display_name="Bootstrap",
                enabled=True,
                availability_mode=RuntimeProviderAvailabilityMode.PLATFORM_WIDE,
                capabilities={},
                config_schema=None,
                metadata=None,
                creation_seeds={"set_as_platform_default_when_unset": True},
                authentication=None,
            ),
        ),
    )
    task = asyncio.create_task(service.reconcile(snapshot))
    try:
        await asyncio.wait_for(reached.wait(), timeout=5)
        async with writes() as session:
            await SystemSettingRepository().write_current(
                session, write=_write("admin")
            )
        proceed.set()
        result = await asyncio.wait_for(task, timeout=5)
        assert len(result.created_provider_ids) == 1
        async with reads() as session:
            provider = await providers.get_by_provider_id(
                session, provider_logical_id=provider_id
            )
            current = await SystemSettingRepository().get_current(
                session, section=SystemSettingSection.PLATFORM_RUNTIME
            )
            assert provider is not None
            assert current is not None and current.config == {
                "default_provider_id": "admin"
            }
            audit = await session.read_session.scalar(
                sa.select(sa.func.count())
                .select_from(RDBSystemSettingAuditEvent)
                .where(
                    RDBSystemSettingAuditEvent.section
                    == SystemSettingSection.PLATFORM_RUNTIME
                )
            )
            assert audit == 0
    finally:
        proceed.set()
        await task
        async with writes() as session:
            await _cleanup(session)
            await session.write_session.execute(
                sa.delete(RDBRuntimeProviderBootstrapDeclaration).where(
                    RDBRuntimeProviderBootstrapDeclaration.source_id
                    == sa.select(RDBRuntimeProviderBootstrapSource.id)
                    .where(RDBRuntimeProviderBootstrapSource.source_key == source_key)
                    .scalar_subquery()
                )
            )
            await session.write_session.execute(
                sa.delete(RDBRuntimeProviderBootstrapSource).where(
                    RDBRuntimeProviderBootstrapSource.source_key == source_key
                )
            )
            await session.write_session.execute(
                sa.delete(RDBRuntimeProviderAuditEvent).where(
                    RDBRuntimeProviderAuditEvent.provider_id
                    == sa.select(RDBRuntimeProvider.id)
                    .where(RDBRuntimeProvider.provider_id == provider_id)
                    .scalar_subquery()
                )
            )
            await session.write_session.execute(
                sa.delete(RDBRuntimeProvider).where(
                    RDBRuntimeProvider.provider_id == provider_id
                )
            )


@pytest.mark.asyncio
@pytest.mark.parametrize("candidate_wins", [True, False])
async def test_candidate_and_seed_order_at_exact_initialization_claim(
    rdb_engine: AsyncEngine, latest_db_schema: None, candidate_wins: bool
) -> None:
    """The losing seed skips; a losing stale candidate gets version conflict."""
    writes = create_read_write_session_manager(rdb_engine)
    reads = create_read_only_session_manager(rdb_engine)
    repository = SystemSettingRepository()
    held, attempted, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
    candidate = _candidate()

    async def winner() -> None:
        async with writes() as session:
            if candidate_wins:
                await repository.replace_candidate(session, create=candidate)
            else:
                assert (
                    await repository.initialize_current_if_unchanged(
                        session, write=_write("bootstrap")
                    )
                    is not None
                )
            held.set()
            await release.wait()

    async def loser() -> None:
        await held.wait()
        async with writes() as session:
            attempted.set()
            if candidate_wins:
                assert (
                    await repository.initialize_current_if_unchanged(
                        session, write=_write("bootstrap")
                    )
                    is None
                )
            else:
                with pytest.raises(SystemSettingVersionConflict) as raised:
                    await repository.replace_candidate(session, create=candidate)
                assert raised.value.expected_version == 0
                assert raised.value.current_version == 1

    first, second = asyncio.create_task(winner()), asyncio.create_task(loser())
    try:
        await asyncio.wait_for(attempted.wait(), timeout=5)
        release.set()
        await asyncio.wait_for(asyncio.gather(first, second), timeout=5)
        async with reads() as session:
            current = await repository.get_current(
                session, section=SystemSettingSection.PLATFORM_RUNTIME
            )
            pending = await repository.get_candidate(
                session, section=SystemSettingSection.PLATFORM_RUNTIME
            )
            assert (pending is not None) is candidate_wins
            assert (current is None) is candidate_wins
    finally:
        release.set()
        await asyncio.gather(first, second)
        async with writes() as session:
            await _cleanup(session)


@pytest.mark.asyncio
async def test_bootstrap_winner_preserves_admin_expected_version_conflict(
    rdb_engine: AsyncEngine, latest_db_schema: None
) -> None:
    """A stale Admin write cannot replace a committed winning initialization."""
    writes = create_read_write_session_manager(rdb_engine)
    repository = SystemSettingRepository()
    held, attempted, release = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def initialize() -> None:
        async with writes() as session:
            assert (
                await repository.initialize_current_if_unchanged(
                    session, write=_write("bootstrap")
                )
                is not None
            )
            held.set()
            await release.wait()

    async def administer() -> None:
        await held.wait()
        async with writes() as session:
            attempted.set()
            with pytest.raises(SystemSettingVersionConflict) as raised:
                await repository.write_current(session, write=_write("admin"))
            assert raised.value.expected_version == 0
            assert raised.value.current_version == 1

    seed, admin = asyncio.create_task(initialize()), asyncio.create_task(administer())
    try:
        await asyncio.wait_for(attempted.wait(), timeout=5)
        release.set()
        await asyncio.wait_for(asyncio.gather(seed, admin), timeout=5)
    finally:
        release.set()
        await asyncio.gather(seed, admin)
        async with writes() as session:
            await _cleanup(session)
