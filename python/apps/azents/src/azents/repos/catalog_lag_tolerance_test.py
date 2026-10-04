"""Real PostgreSQL description reads and final guarded capability acceptance."""

import asyncio
from collections.abc import AsyncIterator
from typing import NamedTuple

import pytest
import pytest_asyncio
import sqlalchemy as sa
from azcommon.result import Success
from psycopg.errors import LockNotAvailable
from sqlalchemy import event
from sqlalchemy.engine import Result
from sqlalchemy.exc import OperationalError
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
from azents.rdb.models.llm_provider_integration import RDBLLMProviderIntegration
from azents.rdb.models.model_metadata_source import (
    RDBModelMetadataSource,
    RDBModelMetadataSourceModel,
)
from azents.rdb.models.workspace import RDBWorkspace
from azents.rdb.session_capabilities import (
    create_read_only_session_manager,
    create_read_write_session_manager,
)
from azents.repos.active_model_capabilities import ActiveModelCapabilitiesRepository
from azents.repos.image_generation_catalog_operations import (
    ImageGenerationCatalogOperationsRepository,
)
from azents.repos.llm_catalog import LLMCatalogRepository
from azents.repos.llm_catalog.data import IntegrationCatalogSyncClaim
from azents.repos.llm_catalog.repository_test import (
    _NOW,
    _entry,
    _image,
    _integration,
)
from azents.repos.llm_catalog.repository_test import (
    _publish as _publish_catalog,
)
from azents.repos.model_metadata_source import ModelMetadataSourceRepository
from azents.repos.model_metadata_source_data import ContextModelRequest
from azents.repos.model_metadata_source_test import (
    _fetched,
)
from azents.repos.model_metadata_source_test import (
    _publish as _publish_source,
)
from azents.services.image_generation_catalog import ImageGenerationCatalogService
from azents.services.model_listing.providers import create_listing_client_factories
from azents.testing.model_metadata import make_test_source_payload

pytestmark = pytest.mark.asyncio


class _Published(NamedTuple):
    workspace_id: str
    integration_id: str
    catalog_id: str


@pytest_asyncio.fixture
async def published_catalog(
    rdb_engine: AsyncEngine,
    latest_db_schema: None,
) -> AsyncIterator[_Published]:
    writes = create_read_write_session_manager(rdb_engine)
    catalogs = LLMCatalogRepository()
    source = ModelMetadataSourceRepository()
    async with writes() as session:
        fixture = await _integration(
            session, handle="lag-tolerance", provider=LLMProvider.XAI
        )
        catalog = await catalogs.ensure_integration_catalog(
            session,
            integration_id=fixture.integration_id,
            provider=LLMProvider.XAI,
            purpose=LLMCatalogPurpose.CONVERSATION,
        )
        await _publish_catalog(
            session,
            catalogs,
            fixture=fixture,
            catalog=catalog,
            entries=[
                _entry(integration_id=fixture.integration_id, identifier="literal")
            ],
            finished_at=_NOW,
        )
        await _publish_source(
            session,
            source,
            _fetched(
                make_test_source_payload(
                    {
                        "xai/literal": {
                            "litellm_provider": "xai",
                            "max_input_tokens": 8192,
                        },
                    }
                )
            ),
        )
    try:
        yield _Published(fixture.workspace_id, fixture.integration_id, catalog.id)
    finally:
        async with writes() as session:
            await session.write_session.execute(
                sa.delete(RDBLLMCatalogEntry).where(
                    RDBLLMCatalogEntry.catalog_id == catalog.id
                )
            )
            await session.write_session.execute(
                sa.delete(RDBLLMCatalog).where(RDBLLMCatalog.id == catalog.id)
            )
            await session.write_session.execute(
                sa.delete(RDBLLMProviderIntegration).where(
                    RDBLLMProviderIntegration.id == fixture.integration_id
                )
            )
            await session.write_session.execute(
                sa.delete(RDBWorkspace).where(RDBWorkspace.id == fixture.workspace_id)
            )
            await session.write_session.execute(
                sa.delete(RDBModelMetadataSourceModel).where(
                    RDBModelMetadataSourceModel.source_key == CATALOG_SOURCE_KEY
                )
            )
            await session.write_session.execute(
                sa.delete(RDBModelMetadataSource).where(
                    RDBModelMetadataSource.source_key == CATALOG_SOURCE_KEY
                )
            )


async def test_readonly_capture_maxima_and_picker_finish_while_writer_holds_rows(
    rdb_engine: AsyncEngine,
    published_catalog: _Published,
) -> None:
    fixture = published_catalog
    reads = create_read_only_session_manager(rdb_engine)
    writes = create_read_write_session_manager(rdb_engine)
    catalogs, source = LLMCatalogRepository(), ModelMetadataSourceRepository()
    active = ActiveModelCapabilitiesRepository(reads, catalogs, source)
    identity = ConfiguredModelIdentity(
        fixture.integration_id, LLMProvider.XAI, "literal"
    )
    statements: list[str] = []

    def observe_statement(
        connection: sa.Connection,
        cursor: object,
        statement: str,
        parameters: object,
        context: object,
        many: bool,
    ) -> None:
        statements.append(statement)

    async with writes() as writer:
        await catalogs.lock_integration(
            writer,
            integration_id=fixture.integration_id,
            workspace_id=fixture.workspace_id,
        )
        await source.lock_authority(writer, source_key=CATALOG_SOURCE_KEY)
        await catalogs.lock_catalog(writer, catalog_id=fixture.catalog_id)
        # The lock acquisitions are authoritative synchronization; no sleeps.
        event.listen(rdb_engine.sync_engine, "before_cursor_execute", observe_statement)
        try:
            async with asyncio.timeout(5):
                async with reads() as reader:
                    captured = await active.capture_exact_choices_in_session(
                        reader,
                        workspace_id=fixture.workspace_id,
                        identities=(identity,),
                    )
                    maxima = await source.capture_for_context(
                        reader,
                        requests=(ContextModelRequest(LLMProvider.XAI, "literal"),),
                    )
                    current = await source.get_current(
                        reader, source_key=CATALOG_SOURCE_KEY
                    )
                    page = await catalogs.list_entries_by_integration(
                        reader,
                        integration_id=fixture.integration_id,
                        workspace_id=fixture.workspace_id,
                        purpose=LLMCatalogPurpose.CONVERSATION,
                        search=None,
                        limit=10,
                        offset=0,
                    )
                    assert captured.catalog_choices[0].catalog_id == fixture.catalog_id
                    assert maxima.models[0].max_input_tokens == 8192
                    assert current is not None and current.model_count == 1
                    assert page is not None and len(page.entries) == 1
        finally:
            event.remove(
                rdb_engine.sync_engine, "before_cursor_execute", observe_statement
            )
    assert not any(
        "FOR UPDATE" in statement.upper() or "FOR SHARE" in statement.upper()
        for statement in statements
    )


async def test_final_acceptance_rejects_committed_change_and_holds_ordered_guards(
    rdb_engine: AsyncEngine,
    published_catalog: _Published,
) -> None:
    fixture = published_catalog
    reads = create_read_only_session_manager(rdb_engine)
    writes = create_read_write_session_manager(rdb_engine)
    catalogs, source = LLMCatalogRepository(), ModelMetadataSourceRepository()
    active = ActiveModelCapabilitiesRepository(reads, catalogs, source)
    identity = ConfiguredModelIdentity(
        fixture.integration_id, LLMProvider.XAI, "literal"
    )
    captured = await active.capture_exact_choices(
        workspace_id=fixture.workspace_id, identities=(identity,)
    )
    async with writes() as writer:
        await writer.write_session.execute(
            sa.update(RDBLLMProviderIntegration)
            .where(RDBLLMProviderIntegration.id == fixture.integration_id)
            .values(
                catalog_configuration_version=RDBLLMProviderIntegration.catalog_configuration_version
                + 1
            )
        )
    async with writes() as accepting:
        assert not await active.inputs_match_in_session(accepting, captured=captured)
        # Each guard remains held by the accepting transaction, even on conflict.
        async with writes() as contender:
            for model, condition in [
                (
                    RDBLLMProviderIntegration,
                    RDBLLMProviderIntegration.id == fixture.integration_id,
                ),
                (
                    RDBModelMetadataSource,
                    RDBModelMetadataSource.source_key == CATALOG_SOURCE_KEY,
                ),
                (RDBLLMCatalog, RDBLLMCatalog.id == fixture.catalog_id),
            ]:
                with pytest.raises(OperationalError) as error:
                    async with contender.write_session.begin_nested():
                        await contender.write_session.execute(
                            sa.select(model)
                            .where(condition)
                            .with_for_update(nowait=True)
                        )
                assert isinstance(error.value.orig, LockNotAvailable)


async def test_source_observation_preserves_empty_absent_and_intrinsic_validation(
    rdb_engine: AsyncEngine,
    published_catalog: _Published,
) -> None:
    reads, writes = (
        create_read_only_session_manager(rdb_engine),
        create_read_write_session_manager(rdb_engine),
    )
    source = ModelMetadataSourceRepository()
    async with writes() as writer:
        await _publish_source(
            writer,
            source,
            _fetched(
                make_test_source_payload(
                    {"xai/literal": {"litellm_provider": "xai"}}
                ).model_copy(update={"models": ()})
            ),
        )
    async with reads() as reader:
        empty = await source.get_current(reader, source_key=CATALOG_SOURCE_KEY)
        assert empty is not None and empty.model_count == 0 and empty.models == ()
        maxima = await source.capture_for_context(
            reader, requests=(ContextModelRequest(LLMProvider.XAI, "literal"),)
        )
        assert maxima.models[0].max_input_tokens is None
    async with writes() as writer:
        await writer.write_session.execute(
            sa.update(RDBModelMetadataSource)
            .where(RDBModelMetadataSource.source_key == CATALOG_SOURCE_KEY)
            .values(model_count=1)
        )
    async with reads() as reader:
        with pytest.raises(ValueError, match="counts and model facts disagree"):
            await source.get_current(reader, source_key=CATALOG_SOURCE_KEY)
    async with writes() as writer:
        await writer.write_session.execute(
            sa.delete(RDBModelMetadataSource).where(
                RDBModelMetadataSource.source_key == CATALOG_SOURCE_KEY
            )
        )
    async with reads() as reader:
        assert await source.get_current(reader, source_key=CATALOG_SOURCE_KEY) is None
        maxima = await source.capture_for_context(
            reader, requests=(ContextModelRequest(LLMProvider.XAI, "literal"),)
        )
        assert maxima.models[0].max_input_tokens is None


async def test_source_publication_between_statement_and_decode_cannot_mix_counts(
    rdb_engine: AsyncEngine,
    published_catalog: _Published,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reads = create_read_only_session_manager(rdb_engine)
    writes = create_read_write_session_manager(rdb_engine)
    source = ModelMetadataSourceRepository()
    async with reads() as reader:
        execute = reader.read_session.execute
        observed = 0

        async def interleave(statement: sa.Executable) -> Result:
            nonlocal observed
            result = await execute(statement)
            observed += 1
            if observed == 1:
                async with writes() as writer:
                    await _publish_source(
                        writer,
                        source,
                        _fetched(
                            make_test_source_payload(
                                {
                                    "xai/literal": {
                                        "litellm_provider": "xai",
                                        "max_input_tokens": 16384,
                                    },
                                    "xai/new": {
                                        "litellm_provider": "xai",
                                        "max_input_tokens": 32768,
                                    },
                                }
                            )
                        ),
                    )
            return result

        monkeypatch.setattr(reader.read_session, "execute", interleave)
        before = await source.get_current(reader, source_key=CATALOG_SOURCE_KEY)
        assert observed == 1
        assert (
            before is not None and before.model_count == 1 and len(before.models) == 1
        )
        after = await source.get_current(reader, source_key=CATALOG_SOURCE_KEY)
        assert after is not None and after.model_count == 2 and len(after.models) == 2


async def test_missing_image_owner_readonly_then_actual_sync_initializes_once(
    rdb_engine: AsyncEngine,
    latest_db_schema: None,
) -> None:

    reads, writes = (
        create_read_only_session_manager(rdb_engine),
        create_read_write_session_manager(rdb_engine),
    )
    catalogs = LLMCatalogRepository()
    async with writes() as writer:
        fixture = await _integration(
            writer, handle="lag-image-absence", provider=LLMProvider.OPENAI
        )
    operations = ImageGenerationCatalogOperationsRepository(
        writes, reads, catalogs, fixture.integration_repository
    )
    service = ImageGenerationCatalogService(
        operations, create_listing_client_factories()
    )
    try:
        first = await service.read(
            integration_id=fixture.integration_id, workspace_id=fixture.workspace_id
        )
        assert isinstance(first, Success)
        assert first.value.catalog_id is None
        assert first.value.explicit_selection_supported is True
        assert first.value.usable is False
        async with reads() as reader:
            assert (
                await reader.read_session.scalar(
                    sa.select(sa.func.count())
                    .select_from(RDBLLMCatalog)
                    .where(
                        RDBLLMCatalog.provider_integration_id == fixture.integration_id
                    )
                )
                == 0
            )
        started = await operations.begin_sync(
            integration_id=fixture.integration_id,
            provider=LLMProvider.OPENAI,
            workspace_id=fixture.workspace_id,
            started_at=_NOW,
            trigger=IntegrationCatalogSyncTrigger.EXPLICIT,
        )

        assert isinstance(started.claim, IntegrationCatalogSyncClaim)
        await operations.publish(
            catalog=started.catalog,
            claim=started.claim,
            entries=[
                _image(
                    integration_id=fixture.integration_id, identifier="gpt-image-test"
                )
            ],
            diagnostics=None,
            sync_diagnostics=None,
            fetched_count=1,
            finished_at=_NOW,
            trigger=IntegrationCatalogSyncTrigger.EXPLICIT,
        )
        current = await service.read(
            integration_id=fixture.integration_id, workspace_id=fixture.workspace_id
        )
        assert isinstance(current, Success)
        assert current.value.catalog_id == started.catalog.id
        assert current.value.usable is True
        assert current.value.total == 1
        async with reads() as reader:
            assert (
                await reader.read_session.scalar(
                    sa.select(sa.func.count())
                    .select_from(RDBLLMCatalog)
                    .where(
                        RDBLLMCatalog.provider_integration_id == fixture.integration_id
                    )
                )
                == 1
            )
    finally:
        async with writes() as writer:
            owner_ids = sa.select(RDBLLMCatalog.id).where(
                RDBLLMCatalog.provider_integration_id == fixture.integration_id
            )
            await writer.write_session.execute(
                sa.delete(RDBImageGenerationCatalogEntry).where(
                    RDBImageGenerationCatalogEntry.catalog_id.in_(owner_ids)
                )
            )
            await writer.write_session.execute(
                sa.delete(RDBLLMCatalog).where(
                    RDBLLMCatalog.provider_integration_id == fixture.integration_id
                )
            )
            await writer.write_session.execute(
                sa.delete(RDBLLMProviderIntegration).where(
                    RDBLLMProviderIntegration.id == fixture.integration_id
                )
            )
            await writer.write_session.execute(
                sa.delete(RDBWorkspace).where(RDBWorkspace.id == fixture.workspace_id)
            )
