"""Completed catalog operation atomicity, isolation and read-only regressions."""

import asyncio
import dataclasses
import datetime
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import uuid4

import pytest
import pytest_asyncio
import sqlalchemy as sa
from azcommon.result import Success
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from azents.core.enums import AgentProjectCatalogStatus, AgentRuntimeCapability
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.agent_project_catalog import RDBAgentProjectCatalogEntry
from azents.rdb.models.workspace import RDBWorkspace
from azents.rdb.session_capabilities import (
    ReadSession,
    WriteSession,
    create_read_only_session_manager,
    create_read_write_session_manager,
)
from azents.repos.agent_project_catalog import AgentProjectCatalogRepository
from azents.repos.agent_project_catalog.data import (
    AgentProjectCatalogEntry,
    AgentProjectCatalogStatusPatch,
)
from azents.repos.agent_project_catalog.operations import (
    AgentProjectCatalogOperationsRepository,
    ProjectCatalogStatusApplication,
)
from azents.runtime.control_protocol.runner_operations import (
    RuntimeFileStatResult,
    RuntimeRunnerOperationClient,
)
from azents.services.agent_project_catalog import AgentProjectCatalogService
from azents.services.agent_runtime.lifecycle_data import (
    RuntimeOperationAuthority,
    RuntimeOperationTarget,
    RuntimeOperationTargetResolver,
)
from azents.testing.model_selection import (
    make_test_model_selection_dict,
    make_test_selectable_model_option_dicts,
)


@dataclasses.dataclass(frozen=True)
class _CatalogRows:
    workspace_id: str
    agent_ids: tuple[str, ...]


@pytest_asyncio.fixture
async def catalog_rows(
    rdb_engine: AsyncEngine, latest_db_schema: None
) -> AsyncIterator[_CatalogRows]:
    """Commit independent Agent catalog owners for production read scopes."""
    writes = create_read_write_session_manager(rdb_engine)
    async with writes() as session:
        workspace = RDBWorkspace(name="Catalog operations", handle=uuid4().hex)
        session.write_session.add(workspace)
        await session.write_session.flush()
        selection = make_test_model_selection_dict()
        agents = [
            RDBAgent(
                workspace_id=workspace.id,
                name="Catalog owner",
                runtime_capability=AgentRuntimeCapability.NONE,
                model_selection=selection,
                lightweight_model_selection=selection,
                selectable_model_options=make_test_selectable_model_option_dicts(
                    model_selection=selection, lightweight_model_selection=selection
                ),
                main_model_label="default",
                lightweight_model_label="lightweight",
            )
            for _ in range(2)
        ]
        session.write_session.add_all(agents)
        await session.write_session.flush()
        rows = _CatalogRows(workspace.id, tuple(agent.id for agent in agents))
    try:
        yield rows
    finally:
        async with writes() as session:
            await session.write_session.execute(
                sa.delete(RDBAgentProjectCatalogEntry).where(
                    RDBAgentProjectCatalogEntry.agent_id.in_(rows.agent_ids)
                )
            )
            await session.write_session.execute(
                sa.delete(RDBAgent).where(RDBAgent.id.in_(rows.agent_ids))
            )
            await session.write_session.execute(
                sa.delete(RDBWorkspace).where(RDBWorkspace.id == rows.workspace_id)
            )


def _operations(
    engine: AsyncEngine, opened: list[AsyncSession]
) -> AgentProjectCatalogOperationsRepository:
    reads = create_read_only_session_manager(engine)

    @asynccontextmanager
    async def manager() -> AsyncIterator[ReadSession]:
        async with reads() as session:
            opened.append(session.read_session)
            assert (
                await session.read_session.scalar(sa.text("SHOW transaction_read_only"))
                == "on"
            )
            yield session

    return AgentProjectCatalogOperationsRepository(
        catalog_repository=AgentProjectCatalogRepository(),
        session_manager=create_read_write_session_manager(engine),
        read_session_manager=manager,
    )


def _application(path: str) -> ProjectCatalogStatusApplication:
    return ProjectCatalogStatusApplication(
        path=path,
        patch=AgentProjectCatalogStatusPatch(
            status=AgentProjectCatalogStatus.AVAILABLE,
            status_detail=None,
            checked_at=datetime.datetime.now(datetime.UTC),
        ),
    )


async def test_same_path_concurrent_candidates_preserve_identity_and_agent_isolation(
    rdb_engine: AsyncEngine, catalog_rows: _CatalogRows
) -> None:
    """Concurrent candidate upserts retain one ID per exact Agent/path key."""
    opened: list[AsyncSession] = []
    operations = _operations(rdb_engine, opened)
    results = await asyncio.gather(
        *(
            operations.upsert_candidates(
                agent_id=catalog_rows.agent_ids[0], paths=("/workspace/agent/app",)
            )
            for _ in range(3)
        )
    )
    assert len({result[0].id for result in results}) == 1
    other = await operations.upsert_candidates(
        agent_id=catalog_rows.agent_ids[1], paths=("/workspace/agent/app",)
    )
    assert other[0].id != results[0][0].id
    entries = await operations.list_entries(agent_id=catalog_rows.agent_ids[0])
    assert [entry.id for entry in entries] == [results[0][0].id]
    assert entries[0].model_dump()["agent_id"] == catalog_rows.agent_ids[0]
    assert len(opened) == 1 and not opened[0].in_transaction()


@pytest.mark.parametrize("operation", ["candidates", "statuses"])
@pytest.mark.parametrize("error_type", [RuntimeError, asyncio.CancelledError])
async def test_partial_batch_failure_rolls_back_complete_catalog_group(
    rdb_engine: AsyncEngine,
    catalog_rows: _CatalogRows,
    operation: str,
    error_type: type[BaseException],
) -> None:
    """The second failing path cannot leave the first path mutation committed."""
    operations = _operations(rdb_engine, [])

    class FailingCatalog(AgentProjectCatalogRepository):
        async def upsert_entry(
            self, session: WriteSession, *, agent_id: str, path: str
        ) -> AgentProjectCatalogEntry:
            if path.endswith("/fail"):
                raise error_type("catalog interrupted")
            return await super().upsert_entry(session, agent_id=agent_id, path=path)

        async def update_status(
            self,
            session: WriteSession,
            *,
            agent_id: str,
            path: str,
            patch: AgentProjectCatalogStatusPatch,
        ) -> AgentProjectCatalogEntry:
            if path.endswith("/fail"):
                raise error_type("catalog interrupted")
            return await super().update_status(
                session, agent_id=agent_id, path=path, patch=patch
            )

    operations.catalog_repository = FailingCatalog()
    with pytest.raises(error_type, match="catalog interrupted"):
        if operation == "candidates":
            await operations.upsert_candidates(
                agent_id=catalog_rows.agent_ids[0],
                paths=("/workspace/agent/ok", "/workspace/agent/fail"),
            )
        else:
            await operations.apply_statuses(
                agent_id=catalog_rows.agent_ids[0],
                applications=(
                    _application("/workspace/agent/ok"),
                    _application("/workspace/agent/fail"),
                ),
            )
    assert await operations.list_entries(agent_id=catalog_rows.agent_ids[0]) == []


async def test_catalog_reads_finish_while_writer_holds_status_row(
    rdb_engine: AsyncEngine, catalog_rows: _CatalogRows
) -> None:
    """Independent list/exact-path reads tolerate uncommitted status updates."""
    opened: list[AsyncSession] = []
    operations = _operations(rdb_engine, opened)
    entries = await operations.upsert_candidates(
        agent_id=catalog_rows.agent_ids[0],
        paths=("/workspace/agent/z", "/workspace/agent/a"),
    )
    writes = create_read_write_session_manager(rdb_engine)
    locked = asyncio.Event()
    release = asyncio.Event()

    async def holder() -> None:
        async with writes() as session:
            await session.write_session.execute(
                sa.update(RDBAgentProjectCatalogEntry)
                .where(
                    RDBAgentProjectCatalogEntry.id.in_(entry.id for entry in entries)
                )
                .values(status=AgentProjectCatalogStatus.ERROR)
            )
            locked.set()
            await release.wait()
            await session.write_session.rollback()

    task = asyncio.create_task(holder())
    try:
        await asyncio.wait_for(locked.wait(), timeout=5)

        async def inspect() -> None:
            all_entries = await operations.list_entries(
                agent_id=catalog_rows.agent_ids[0]
            )
            exact = await operations.list_entries_by_paths(
                agent_id=catalog_rows.agent_ids[0],
                paths=("/workspace/agent/z", "/workspace/agent/a"),
            )
            assert {entry.id for entry in all_entries} == {
                entry.id for entry in entries
            }
            assert [entry.path for entry in exact] == [
                "/workspace/agent/a",
                "/workspace/agent/z",
            ]
            assert all(
                entry.status is AgentProjectCatalogStatus.UNCHECKED for entry in exact
            )

        await asyncio.wait_for(inspect(), timeout=5)
        assert len(opened) == 2 and all(
            not session.in_transaction() for session in opened
        )
        assert not release.is_set()
    finally:
        release.set()
        await task


async def test_runtime_resolution_and_probes_run_outside_catalog_transactions(
    rdb_engine: AsyncEngine, catalog_rows: _CatalogRows
) -> None:
    """Filesystem evidence is collected between completed database operations."""
    opened: list[AsyncSession] = []
    operations = _operations(rdb_engine, opened)
    writes = create_read_write_session_manager(rdb_engine)

    @asynccontextmanager
    async def manager() -> AsyncIterator[WriteSession]:
        async with writes() as session:
            opened.append(session.write_session)
            yield session

    operations.session_manager = manager
    external_calls: list[str] = []

    class Resolver(RuntimeOperationTargetResolver):
        async def resolve_operation_target(
            self,
            agent_id: str,
            *,
            wait_timeout_seconds: float = 120.0,
            poll_interval_seconds: float = 1.0,
            expected_authority: RuntimeOperationAuthority | None = None,
            start_if_stopped: bool = True,
        ) -> RuntimeOperationTarget:
            assert agent_id == catalog_rows.agent_ids[0]
            assert all(not session.in_transaction() for session in opened)
            external_calls.append("resolve")
            return RuntimeOperationTarget(
                id="runtime",
                runtime_capability_version=1,
                desired_generation=1,
                runner_generation=1,
                configuration_sequence=1,
                configuration_digest="a" * 64,
                workspace_path="/workspace/agent",
            )

    class Runner(RuntimeRunnerOperationClient):
        def __init__(self) -> None:
            """Use only the bounded fake stat implementation without transport."""

        async def stat_file(
            self,
            *,
            runtime_id: str,
            runner_generation: int,
            owner_session_id: str | None = None,
            path: str,
            deadline_at: datetime.datetime,
        ) -> RuntimeFileStatResult:
            assert all(not session.in_transaction() for session in opened)
            external_calls.append(path)
            return RuntimeFileStatResult(
                path=path,
                kind="directory",
                size_bytes=None,
                symlink=False,
                real_path=None,
                resolved_kind="directory",
                modified_at=None,
                final_cursor="0",
            )

    service = AgentProjectCatalogService(
        repository=operations,
        runtime_target_resolver=Resolver(),
        runner_operations=Runner(),
    )
    candidate = await service.upsert_project_candidate(
        agent_id=catalog_rows.agent_ids[0], path="/workspace/agent/a"
    )
    assert isinstance(candidate, Success)
    result = await service.refresh_project_statuses(
        agent_id=catalog_rows.agent_ids[0],
        paths=["/workspace/agent/a", "/workspace/agent/b"],
    )
    assert isinstance(result, Success)
    assert [entry.path for entry in result.value] == [
        "/workspace/agent/a",
        "/workspace/agent/b",
    ]
    assert all(
        entry.status is AgentProjectCatalogStatus.AVAILABLE for entry in result.value
    )
    assert external_calls == [
        "resolve",
        "resolve",
        "/workspace/agent/a",
        "/workspace/agent/b",
    ]
    assert len(opened) == 2 and all(not session.in_transaction() for session in opened)
