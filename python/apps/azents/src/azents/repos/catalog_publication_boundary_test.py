"""Exact owner publication exclusion without redundant key enumeration locks."""

import asyncio
import dataclasses
import datetime

import pytest
import sqlalchemy as sa
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine

from azents.core.active_model_capabilities import ConfiguredModelIdentity
from azents.core.enums import LLMCatalogPurpose, LLMProvider
from azents.core.llm_catalog_sync import IntegrationCatalogSyncTrigger
from azents.core.model_catalog_source import CATALOG_SOURCE_KEY
from azents.rdb.models.llm_catalog import (
    RDBImageGenerationCatalogEntry,
    RDBLLMCatalog,
    RDBLLMCatalogEntry,
)
from azents.rdb.models.model_metadata_source import RDBModelMetadataSourceModel
from azents.rdb.session_capabilities import (
    WriteSession,
    create_read_only_session_manager,
    create_read_write_session_manager,
)
from azents.repos.active_model_capabilities import ActiveModelCapabilitiesRepository
from azents.repos.catalog_lag_tolerance_test import _Published
from azents.repos.catalog_lag_tolerance_test import (
    published_catalog as published_catalog,  # noqa: PLC0414 - Register shared pytest fixture.
)
from azents.repos.llm_catalog import LLMCatalogRepository
from azents.repos.llm_catalog.data import IntegrationCatalogSyncClaim
from azents.repos.llm_catalog.repository_test import _NOW, _entry, _image
from azents.repos.model_candidate_health.operation_boundary_test import (
    _wait_for_candidate_blocker,
)
from azents.repos.model_metadata_source import ModelMetadataSourceRepository
from azents.repos.model_metadata_source_test import _fetched, _publish
from azents.testing.model_metadata import make_test_source_payload


@pytest.mark.parametrize("kind", ["conversation", "image", "source"])
async def test_publication_owner_serializes_competitors_without_key_read_locks(
    rdb_engine: AsyncEngine,
    published_catalog: _Published,
    kind: str,
) -> None:
    """Owner exclusion keeps whole-set replacement and exact acceptance guards."""
    fixture = published_catalog
    writes = create_read_write_session_manager(rdb_engine)
    reads = create_read_only_session_manager(rdb_engine)
    catalogs, source = LLMCatalogRepository(), ModelMetadataSourceRepository()
    active = ActiveModelCapabilitiesRepository(reads, catalogs, source)
    captured = await active.capture_exact_choices(
        workspace_id=fixture.workspace_id,
        identities=(
            ConfiguredModelIdentity(fixture.integration_id, LLMProvider.XAI, "literal"),
        ),
    )
    catalog_id = fixture.catalog_id
    if kind == "image":
        async with writes() as setup:
            image_catalog = await catalogs.ensure_integration_catalog(
                setup,
                integration_id=fixture.integration_id,
                provider=LLMProvider.XAI,
                purpose=LLMCatalogPurpose.IMAGE_GENERATION,
            )
            catalog_id = image_catalog.id

    async def replace(session: WriteSession, *, identifier: str, sequence: int) -> None:
        finished_at = _NOW + datetime.timedelta(minutes=sequence)
        if kind == "source":
            await _publish(
                session,
                source,
                _fetched(
                    make_test_source_payload(
                        {f"xai/{identifier}": {"litellm_provider": "xai"}}
                    ),
                    collected_at=finished_at,
                ),
            )
            return
        claim = await catalogs.begin_integration_sync(
            session,
            catalog_id=catalog_id,
            workspace_id=fixture.workspace_id,
            started_at=finished_at,
            trigger=IntegrationCatalogSyncTrigger.CONFIG_UPDATE,
            required_projection_version=None,
        )
        assert isinstance(claim, IntegrationCatalogSyncClaim)
        owner = await catalogs.lock_catalog(session, catalog_id=catalog_id)
        if kind == "conversation":
            await catalogs.replace_current_entries(
                session,
                owner=owner,
                entries=[
                    _entry(integration_id=fixture.integration_id, identifier=identifier)
                ],
                diagnostics=None,
                finished_at=finished_at,
            )
        else:
            await catalogs.replace_current_image_entries(
                session,
                owner=owner,
                entries=[
                    dataclasses.replace(
                        _image(
                            integration_id=fixture.integration_id,
                            identifier=identifier,
                        ),
                        provider=LLMProvider.XAI,
                    )
                ],
                diagnostics=None,
                finished_at=finished_at,
            )
        await catalogs.complete_sync(
            session,
            catalog_id=catalog_id,
            work_token=claim.work_token,
            finished_at=finished_at,
            fetched_count=1,
            matched_count=1,
            skipped_count=0,
            hidden_count=0,
            diagnostics=None,
        )

    statements: list[str] = []

    def observe(
        connection: sa.Connection,
        cursor: object,
        statement: str,
        parameters: object,
        context: object,
        executemany: bool,
    ) -> None:
        statements.append(statement)

    competitor_pids: asyncio.Queue[int] = asyncio.Queue()
    competitor_task: asyncio.Task[None] | None = None
    event.listen(rdb_engine.sync_engine, "before_cursor_execute", observe)
    try:
        async with writes() as winner:
            winner_pid = await winner.read_session.scalar(
                sa.select(sa.func.pg_backend_pid())
            )
            assert isinstance(winner_pid, int)
            await replace(winner, identifier="first", sequence=1)

            async def compete() -> None:
                async with writes() as competitor:
                    pid = await competitor.read_session.scalar(
                        sa.select(sa.func.pg_backend_pid())
                    )
                    assert isinstance(pid, int)
                    assert pid != winner_pid
                    await competitor_pids.put(pid)
                    await replace(competitor, identifier="second", sequence=2)

            competitor_task = asyncio.create_task(compete())
            competitor_pid = await asyncio.wait_for(competitor_pids.get(), timeout=5)
            await asyncio.wait_for(
                _wait_for_candidate_blocker(
                    rdb_engine, blocked_pid=competitor_pid, blocker_pid=winner_pid
                ),
                timeout=5,
            )
            assert not competitor_task.done()
            await winner.write_session.commit()
            await asyncio.wait_for(competitor_task, timeout=5)

        if kind == "source":
            async with reads() as observer:
                current = await source.get_current(
                    observer, source_key=CATALOG_SOURCE_KEY
                )
                assert current is not None
                assert current.model_count == 1
                assert current.models[0].model.source_key == "xai/second"
                status = await source.get_sync_status(
                    observer, source_key=CATALOG_SOURCE_KEY
                )
                assert status is not None and status.work_token is None
        else:
            async with reads() as observer:
                model = (
                    RDBLLMCatalogEntry
                    if kind == "conversation"
                    else RDBImageGenerationCatalogEntry
                )
                identifiers = list(
                    (
                        await observer.read_session.scalars(
                            sa.select(model.provider_model_identifier).where(
                                model.catalog_id == catalog_id
                            )
                        )
                    ).all()
                )
                assert identifiers == ["second"]
                owner = await observer.read_session.get(
                    RDBLLMCatalog,
                    catalog_id,
                )
                assert owner is not None
                assert owner.sync_work_token is None
        if kind != "image":
            async with writes() as accepting:
                assert not await active.inputs_match_in_session(
                    accepting, captured=captured
                )
        enumeration_tables = (
            RDBLLMCatalogEntry.__tablename__,
            RDBImageGenerationCatalogEntry.__tablename__,
            RDBModelMetadataSourceModel.__tablename__,
        )
        enumerations = [
            statement
            for statement in statements
            if statement.lstrip().upper().startswith("SELECT")
            and any(f"FROM {table}" in statement for table in enumeration_tables)
        ]
        assert enumerations
        assert all("FOR UPDATE" not in statement.upper() for statement in enumerations)
    finally:
        if competitor_task is not None and not competitor_task.done():
            competitor_task.cancel()
            await asyncio.gather(competitor_task, return_exceptions=True)
        event.remove(rdb_engine.sync_engine, "before_cursor_execute", observe)
        if kind == "image":
            async with writes() as cleanup:
                await cleanup.write_session.execute(
                    sa.delete(RDBImageGenerationCatalogEntry).where(
                        RDBImageGenerationCatalogEntry.catalog_id == catalog_id
                    )
                )
                await cleanup.write_session.execute(
                    sa.delete(RDBLLMCatalog).where(RDBLLMCatalog.id == catalog_id)
                )
