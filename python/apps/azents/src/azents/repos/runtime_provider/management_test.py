"""Read-lag and atomic Provider administration regression tests."""

import asyncio
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

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
    create_read_only_session_manager,
    create_read_write_session_manager,
)
from azents.repos.runtime_provider.data import RuntimeProviderCreate
from azents.repos.runtime_provider.repository import RuntimeProviderRepository


@pytest.mark.asyncio
async def test_nonblocking_provider_reads_and_atomic_policy_versions(
    rdb_engine: AsyncEngine,
    latest_db_schema: None,
) -> None:
    """Readers tolerate committed lag while actual mutations allocate versions."""
    reads = create_read_only_session_manager(rdb_engine)
    writes = create_read_write_session_manager(rdb_engine)
    repository = RuntimeProviderRepository()
    async with writes() as session:
        provider = await repository.create(
            session,
            RuntimeProviderCreate(
                provider_id=f"read-lag-{uuid4().hex}",
                scope=RuntimeProviderScope.SYSTEM,
                workspace_id=None,
                kind=RuntimeProviderKind.DOCKER,
                display_name="test",
                registration_method=RuntimeProviderRegistrationMethod.ADMIN,
                enabled=True,
                lifecycle_state=RuntimeProviderLifecycleState.ACTIVE,
                availability_mode=RuntimeProviderAvailabilityMode.PLATFORM_WIDE,
                capabilities={},
                config_schema=None,
                metadata=None,
            ),
        )
    locked = asyncio.Event()
    release = asyncio.Event()

    async def holder() -> None:
        async with writes() as session:
            await session.write_session.execute(
                sa.select(RDBRuntimeProvider.id)
                .where(RDBRuntimeProvider.id == provider.id)
                .with_for_update()
            )
            locked.set()
            await release.wait()

    task = asyncio.create_task(holder())
    try:
        await locked.wait()

        async def inspect() -> None:
            async with reads() as session:
                observed = await repository.get_by_id(session, provider_id=provider.id)
                assert observed is not None and observed.admin_version == 0
                available = await repository.list_available(
                    session, workspace_id=None, include_disabled=False
                )
                assert any(item.id == provider.id for item in available)

        await asyncio.wait_for(inspect(), timeout=5)
        assert not release.is_set()
        release.set()
        await task

        async def change(enabled: bool) -> int:
            async with writes() as session:
                updated = await repository.update_administrative_policy(
                    session,
                    provider_id=provider.id,
                    enabled=enabled,
                    lifecycle_state=RuntimeProviderLifecycleState.ACTIVE,
                    availability_mode=RuntimeProviderAvailabilityMode.PLATFORM_WIDE,
                )
                assert updated is not None
                return updated.admin_version

        assert sorted(await asyncio.gather(change(False), change(True))) == [1, 2]
    finally:
        release.set()
        await task
        async with writes() as session:
            await session.write_session.execute(
                sa.delete(RDBRuntimeProvider).where(
                    RDBRuntimeProvider.id == provider.id
                )
            )


@pytest.mark.asyncio
async def test_competing_availability_replacements_publish_one_complete_set(
    rdb_engine: AsyncEngine,
    latest_db_schema: None,
) -> None:
    """Whole availability replacement is transactional, never a merged set."""
    writes = create_read_write_session_manager(rdb_engine)
    reads = create_read_only_session_manager(rdb_engine)
    repository = RuntimeProviderRepository()
    async with writes() as session:
        provider = await repository.create(
            session,
            RuntimeProviderCreate(
                provider_id=f"availability-{uuid4().hex}",
                scope=RuntimeProviderScope.SYSTEM,
                workspace_id=None,
                kind=RuntimeProviderKind.DOCKER,
                display_name="test",
                registration_method=RuntimeProviderRegistrationMethod.ADMIN,
                enabled=True,
                lifecycle_state=RuntimeProviderLifecycleState.ACTIVE,
                availability_mode=RuntimeProviderAvailabilityMode.SELECTED_WORKSPACES,
                capabilities={},
                config_schema=None,
                metadata=None,
            ),
        )
        workspaces = [
            RDBWorkspace(name="test", handle=f"availability-{uuid4().hex}")
            for _ in range(2)
        ]
        session.write_session.add_all(workspaces)
        await session.write_session.flush()
        ids = [workspace.id for workspace in workspaces]

    async def replace(workspace_id: str) -> int:
        async with writes() as session:
            result = await repository.replace_workspace_availability(
                session, provider_id=provider.id, workspace_ids={workspace_id}
            )
            assert result is not None
            return result.admin_version

    try:
        assert sorted(await asyncio.gather(*(replace(id_) for id_ in ids))) == [1, 2]
        async with reads() as session:
            selected = [
                id_
                for id_ in ids
                if await repository.is_available_to_workspace(
                    session, provider_id=provider.id, workspace_id=id_
                )
            ]
            assert len(selected) == 1
    finally:
        async with writes() as session:
            await session.write_session.execute(
                sa.delete(RDBRuntimeProviderWorkspaceAvailability).where(
                    RDBRuntimeProviderWorkspaceAvailability.provider_id == provider.id
                )
            )
            await session.write_session.execute(
                sa.delete(RDBRuntimeProvider).where(
                    RDBRuntimeProvider.id == provider.id
                )
            )
            await session.write_session.execute(
                sa.delete(RDBWorkspace).where(RDBWorkspace.id.in_(ids))
            )
