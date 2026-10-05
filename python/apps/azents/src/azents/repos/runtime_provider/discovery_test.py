"""Read-only, nonblocking Runtime Provider discovery operation tests."""

import asyncio
import dataclasses
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import uuid4

import pytest_asyncio
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from azents.core.enums import (
    RuntimeProviderAvailabilityMode,
    RuntimeProviderKind,
    RuntimeProviderLifecycleState,
    RuntimeProviderRegistrationMethod,
    RuntimeProviderScope,
)
from azents.rdb.models.runtime_provider import RDBRuntimeProvider
from azents.rdb.models.runtime_provider_bootstrap import (
    RDBRuntimeProviderWorkspaceAvailability,
)
from azents.rdb.models.workspace import RDBWorkspace
from azents.rdb.session_capabilities import (
    ReadSession,
    create_read_only_session_manager,
    create_read_write_session_manager,
)
from azents.repos.runtime_provider.data import RuntimeProviderCreate
from azents.repos.runtime_provider.discovery import RuntimeProviderDiscoveryRepository
from azents.repos.runtime_provider.repository import RuntimeProviderRepository


@dataclasses.dataclass(frozen=True)
class _DiscoveryRows:
    workspace_ids: tuple[str, ...]
    provider_ids: tuple[str, ...]
    prefix: str


@pytest_asyncio.fixture
async def discovery_rows(
    rdb_engine: AsyncEngine, latest_db_schema: None
) -> AsyncIterator[_DiscoveryRows]:
    """Commit a mixture of Provider scopes, policies and availability grants."""
    writes = create_read_write_session_manager(rdb_engine)
    repository = RuntimeProviderRepository()
    prefix = uuid4().hex
    async with writes() as session:
        workspaces = [
            RDBWorkspace(name="Discovery", handle=uuid4().hex) for _ in range(2)
        ]
        session.write_session.add_all(workspaces)
        await session.write_session.flush()
        ids: list[str] = []
        for label in [
            "retired",
            "selected-denied",
            "z-global",
            "a-local",
            "selected-allowed",
            "disabled",
            "decommissioning",
            "other-workspace",
        ]:
            workspace_id = (
                workspaces[0].id
                if label == "a-local"
                else workspaces[1].id
                if label == "other-workspace"
                else None
            )
            lifecycle = (
                RuntimeProviderLifecycleState.FORCE_RETIRED
                if label == "retired"
                else RuntimeProviderLifecycleState.DECOMMISSIONING
                if label == "decommissioning"
                else RuntimeProviderLifecycleState.ACTIVE
            )
            provider = await repository.create(
                session,
                RuntimeProviderCreate(
                    provider_id=f"{prefix}-{label}",
                    scope=RuntimeProviderScope.WORKSPACE
                    if workspace_id
                    else RuntimeProviderScope.SYSTEM,
                    workspace_id=workspace_id,
                    kind=RuntimeProviderKind.DOCKER,
                    display_name=label,
                    registration_method=RuntimeProviderRegistrationMethod.ADMIN,
                    enabled=label != "disabled",
                    lifecycle_state=lifecycle,
                    availability_mode=(
                        RuntimeProviderAvailabilityMode.SELECTED_WORKSPACES
                        if label.startswith("selected-")
                        else RuntimeProviderAvailabilityMode.PLATFORM_WIDE
                    ),
                    capabilities={},
                    config_schema=None,
                    metadata=None,
                ),
            )
            ids.append(provider.id)
            if label.startswith("selected-"):
                await repository.replace_workspace_availability(
                    session,
                    provider_id=provider.id,
                    workspace_ids={
                        workspaces[0].id
                        if label == "selected-allowed"
                        else workspaces[1].id
                    },
                )
        rows = _DiscoveryRows(
            tuple(workspace.id for workspace in workspaces), tuple(ids), prefix
        )
    try:
        yield rows
    finally:
        async with writes() as session:
            await session.write_session.execute(
                sa.delete(RDBRuntimeProviderWorkspaceAvailability).where(
                    RDBRuntimeProviderWorkspaceAvailability.provider_id.in_(
                        rows.provider_ids
                    )
                )
            )
            await session.write_session.execute(
                sa.delete(RDBRuntimeProvider).where(
                    RDBRuntimeProvider.id.in_(rows.provider_ids)
                )
            )
            await session.write_session.execute(
                sa.delete(RDBWorkspace).where(RDBWorkspace.id.in_(rows.workspace_ids))
            )


async def test_discovery_preserves_eligibility_order_and_closes_read_scope(
    rdb_engine: AsyncEngine, discovery_rows: _DiscoveryRows
) -> None:
    """Filter disabled, non-active, other-scope and denied selected Providers."""
    reads = create_read_only_session_manager(rdb_engine)
    opened: list[AsyncSession] = []

    @asynccontextmanager
    async def manager() -> AsyncIterator[ReadSession]:
        async with reads() as session:
            opened.append(session.read_session)
            assert (
                await session.read_session.scalar(sa.text("SHOW transaction_read_only"))
                == "on"
            )
            yield session

    repository = RuntimeProviderDiscoveryRepository(
        manager, RuntimeProviderRepository()
    )
    providers = await repository.list_for_workspace(discovery_rows.workspace_ids[0])
    observed = [
        provider for provider in providers if provider.id in discovery_rows.provider_ids
    ]
    assert [provider.provider_id for provider in observed] == [
        f"{discovery_rows.prefix}-{label}"
        for label in ["a-local", "selected-allowed", "z-global"]
    ]
    assert [provider.provider_id for provider in providers] == sorted(
        provider.provider_id for provider in providers
    )
    assert all(provider.model_dump() for provider in observed)
    assert len(opened) == 1 and not opened[0].in_transaction()


async def test_discovery_finishes_while_writer_holds_policy_and_allow_list(
    rdb_engine: AsyncEngine, discovery_rows: _DiscoveryRows
) -> None:
    """Descriptive discovery tolerates committed lag without row-lock waits."""
    reads = create_read_only_session_manager(rdb_engine)
    writes = create_read_write_session_manager(rdb_engine)
    repository = RuntimeProviderDiscoveryRepository(reads, RuntimeProviderRepository())
    locked = asyncio.Event()
    release = asyncio.Event()

    async def holder() -> None:
        async with writes() as session:
            await session.write_session.execute(
                sa.update(RDBRuntimeProvider)
                .where(RDBRuntimeProvider.id.in_(discovery_rows.provider_ids))
                .values(enabled=False)
            )
            await session.write_session.execute(
                sa.delete(RDBRuntimeProviderWorkspaceAvailability).where(
                    RDBRuntimeProviderWorkspaceAvailability.provider_id.in_(
                        discovery_rows.provider_ids
                    )
                )
            )
            locked.set()
            await release.wait()
            await session.write_session.rollback()

    task = asyncio.create_task(holder())
    try:
        await asyncio.wait_for(locked.wait(), timeout=5)
        providers = await asyncio.wait_for(
            repository.list_for_workspace(discovery_rows.workspace_ids[0]), timeout=5
        )
        observed = [
            provider
            for provider in providers
            if provider.id in discovery_rows.provider_ids
        ]
        assert len(observed) == 3
        assert not release.is_set()
    finally:
        release.set()
        await task
