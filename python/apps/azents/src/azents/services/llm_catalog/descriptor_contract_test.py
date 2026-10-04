"""Semantic catalog contract and new selection diagnostic assertions."""

import ast
import dataclasses
import datetime
from collections.abc import Sequence
from unittest.mock import AsyncMock

import pytest
import sqlalchemy as sa
from azcommon.result import Success
from cryptography.fernet import Fernet
from sqlalchemy.ext.asyncio import AsyncSession

from azents.consts import PROJECT_ROOT
from azents.core.agent import AgentModelSelectionInput
from azents.core.credentials import ApiKeySecrets
from azents.core.crypto import CredentialCipher
from azents.core.enums import (
    LLMCatalogEntryVisibility,
    LLMCatalogPurpose,
    LLMModelLifecycleStatus,
    LLMProvider,
)
from azents.core.model_capability_projection import (
    CAPABILITY_PROJECTION_REVISION,
    project_capabilities,
)
from azents.core.model_catalog_source import CATALOG_SOURCE_KEY
from azents.core.model_metadata_collection_data import (
    CurrentSourceModel,
    FetchedModelMetadataSource,
)
from azents.core.model_pricing import normalize_model_pricing
from azents.core.workspace import WorkspaceCreate
from azents.rdb.models.llm_catalog import RDBLLMCatalogEntry
from azents.rdb.session import SessionManager
from azents.repos.active_model_capabilities import ActiveModelCapabilitiesRepository
from azents.repos.llm_catalog import LLMCatalogRepository
from azents.repos.llm_catalog.data import (
    LLMCatalog,
    LLMCatalogEntry,
    LLMCatalogEntryCreate,
)
from azents.repos.llm_catalog_operations import LLMCatalogOperationsRepository
from azents.repos.llm_provider_integration import LLMProviderIntegrationRepository
from azents.repos.llm_provider_integration.data import LLMProviderIntegrationCreate
from azents.repos.model_metadata_source import ModelMetadataSourceRepository
from azents.repos.workspace import WorkspaceRepository
from azents.services.llm_catalog import ModelCatalogEntryOutput, ModelCatalogReadService
from azents.testing.model_metadata import make_test_source, make_test_source_payload

_DESCRIPTORS = {"lowerer_target", "runtime_model_identifier"}


class _CountingExactSourceRepository(ModelMetadataSourceRepository):
    """Observe narrow local reads without a remote collection path."""

    def __init__(self) -> None:
        self.requested_keys: list[tuple[tuple[str, str], ...]] = []

    async def get_models(
        self,
        session: AsyncSession,
        *,
        source_key: str,
        keys: Sequence[tuple[str, str]],
    ) -> dict[tuple[str, str], CurrentSourceModel]:
        self.requested_keys.append(tuple(keys))
        return await super().get_models(session, source_key=source_key, keys=keys)


def test_internal_catalog_contract_has_only_semantic_identity() -> None:
    """Repository/service fields do not retain removed executable descriptors."""
    for model in (LLMCatalog, LLMCatalogEntry, LLMCatalogEntryCreate):
        assert _DESCRIPTORS.isdisjoint(
            field.name for field in dataclasses.fields(model)
        )
    assert _DESCRIPTORS.isdisjoint(ModelCatalogEntryOutput.model_fields)


def test_public_catalog_dto_source_does_not_expose_execution_descriptors() -> None:
    """Check DTO/converter structure without importing unrelated application routes."""
    source = PROJECT_ROOT / "src/azents/api/public/llm_provider_integration/v1/data.py"
    module = ast.parse(source.read_text())
    response = next(
        node
        for node in module.body
        if isinstance(node, ast.ClassDef) and node.name == "ModelCatalogEntryResponse"
    )
    fields = {
        node.target.id
        for node in response.body
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)
    }
    arguments = {
        node.arg for node in ast.walk(response) if isinstance(node, ast.keyword)
    }
    assert _DESCRIPTORS.isdisjoint(fields | arguments)


@pytest.mark.asyncio
async def test_new_selection_diagnostics_preserve_raw_identifier_without_descriptors(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """Stored selection remains semantic, with exact publisher-qualified model ID."""
    catalog_repository = LLMCatalogRepository()
    integration_repository = LLMProviderIntegrationRepository(
        CredentialCipher(Fernet.generate_key().decode())
    )
    model_identifier = "publisher/subnamespace/model-with-slashes"
    capabilities = project_capabilities(
        provider=LLMProvider.OPENROUTER,
        exact_model=model_identifier,
        source_model=None,
        evidence=None,
        model_developer=None,
    )
    assert capabilities.capability_schema_version == 3
    async with rdb_session_manager() as session:
        workspace_repository = WorkspaceRepository()
        workspace = await workspace_repository.create(
            session, WorkspaceCreate(name="Contract fixture", handle="contract-fixture")
        )
        assert isinstance(workspace, Success)
        workspace_id = await workspace_repository.resolve_id(
            session, "contract-fixture"
        )
        assert workspace_id is not None
        integration = await integration_repository.create(
            session,
            LLMProviderIntegrationCreate(
                workspace_id=workspace_id,
                provider=LLMProvider.OPENROUTER,
                name="Synthetic integration",
                secrets=ApiKeySecrets(api_key="synthetic-not-real"),
                config=None,
            ),
        )
        catalog = await catalog_repository.ensure_integration_catalog(
            session,
            integration_id=integration.id,
            provider=integration.provider,
            purpose=LLMCatalogPurpose.CONVERSATION,
        )
        owner = await catalog_repository.lock_catalog(session, catalog_id=catalog.id)
        await catalog_repository.replace_current_entries(
            session,
            owner=owner,
            entries=[
                LLMCatalogEntryCreate(
                    provider=integration.provider,
                    provider_model_identifier=model_identifier,
                    display_name="Publisher model",
                    normalized_capabilities=capabilities.model_dump(mode="json"),
                    supported_execution_options=[],
                    lifecycle_status=LLMModelLifecycleStatus.ACTIVE,
                    visibility_status=LLMCatalogEntryVisibility.SELECTABLE,
                    provider_integration_id=integration.id,
                    publisher="other",
                    family=None,
                    pricing=normalize_model_pricing(
                        source_key=None, source_model=None, collected_at=None
                    ),
                    source_metadata={"provider_listing_source": "fixture"},
                    projection_metadata={
                        "projection_schema_version": "2",
                        "capability_compiler_revision": CAPABILITY_PROJECTION_REVISION,
                        "fixture": True,
                    },
                    hidden_reason=None,
                )
            ],
            diagnostics={"fixture": True},
            finished_at=datetime.datetime.now(datetime.UTC),
        )
    result = await ModelCatalogReadService(
        operations=LLMCatalogOperationsRepository(
            session_manager=rdb_session_manager,
            catalog_repository=catalog_repository,
            integration_repository=AsyncMock(spec=LLMProviderIntegrationRepository),
            source_repository=ModelMetadataSourceRepository(),
            active_repository=ActiveModelCapabilitiesRepository(
                session_manager=rdb_session_manager,
                catalog_repository=catalog_repository,
                source_repository=ModelMetadataSourceRepository(),
            ),
        )
    ).resolve_agent_model_selection(
        workspace_id=workspace_id,
        selection_input=AgentModelSelectionInput(
            llm_provider_integration_id=integration.id,
            model_identifier=model_identifier,
        ),
    )
    assert isinstance(result, Success)
    selection = result.value
    assert selection.model_identifier == model_identifier
    assert selection.provider == integration.provider
    assert selection.llm_provider_integration_id == integration.id
    assert selection.normalized_capabilities == capabilities
    assert selection.model_snapshot["catalog_id"] == catalog.id
    assert "snapshot_id" not in selection.model_snapshot
    assert _DESCRIPTORS.isdisjoint(selection.model_snapshot)


async def test_active_picker_recompiles_historical_rows_without_writing_them(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    catalogs = LLMCatalogRepository()
    integrations = LLMProviderIntegrationRepository(
        CredentialCipher(Fernet.generate_key().decode())
    )
    model_id = "publisher/historical-literal"
    legacy_capabilities = {
        "capability_schema_version": 2,
        "tool_calling": {"supported": False},
        "reasoning": {"supported": False, "effort_levels": []},
    }
    raw_declarations = {
        "provider_metadata": {
            "supported_parameters": ["tools", "parallel_tool_calls"],
            "architecture": {
                "input_modalities": ["text"],
                "output_modalities": ["text"],
            },
        }
    }
    price = normalize_model_pricing(
        source_key=None, source_model=None, collected_at=None
    )
    async with rdb_session_manager() as session:
        source = make_test_source(
            make_test_source_payload(
                {
                    f"openrouter/{model_id}": {
                        "litellm_provider": "openrouter",
                        "max_input_tokens": 32000,
                    },
                    "openrouter/unrelated": {
                        "litellm_provider": "openrouter",
                        "supports_function_calling": False,
                    },
                }
            )
        )
        source_writer = ModelMetadataSourceRepository()
        token = await source_writer.begin_sync(
            session, source_key=CATALOG_SOURCE_KEY, started_at=source.collected_at
        )
        source_owner = await source_writer.lock_authority(
            session, source_key=CATALOG_SOURCE_KEY
        )
        assert source_owner is not None
        await source_writer.replace_current(
            session,
            owner=source_owner,
            work_token=token,
            fetched=FetchedModelMetadataSource(
                source_kind=source.source_kind,
                source_schema_version=source.source_schema_version,
                source_url=source.source_url,
                producer_name=source.producer_name,
                producer_version=source.producer_version,
                provider_count=source.provider_count,
                model_count=source.model_count,
                payload=source.payload,
                models=source.models,
                collected_at=source.collected_at,
            ),
            finished_at=source.collected_at,
            diagnostics={"fixture": True},
        )
        workspaces = WorkspaceRepository()
        created = await workspaces.create(
            session, WorkspaceCreate(name="Active read", handle="active-read-fixture")
        )
        assert isinstance(created, Success)
        workspace_id = await workspaces.resolve_id(session, "active-read-fixture")
        assert workspace_id is not None
        integration = await integrations.create(
            session,
            LLMProviderIntegrationCreate(
                workspace_id=workspace_id,
                provider=LLMProvider.OPENROUTER,
                name="Stored declarations",
                secrets=ApiKeySecrets(api_key="fixture-not-real"),
                config=None,
            ),
        )
        catalog = await catalogs.ensure_integration_catalog(
            session,
            integration_id=integration.id,
            provider=integration.provider,
            purpose=LLMCatalogPurpose.CONVERSATION,
        )
        # This is historical persisted data, not a new publication through the
        # current writer (which must reject an obsolete capability generation).
        await session.execute(
            sa.insert(RDBLLMCatalogEntry).values(
                id="b" * 32,
                catalog_id=catalog.id,
                provider=integration.provider,
                provider_model_identifier=model_id,
                display_name="Historical row",
                normalized_capabilities=legacy_capabilities,
                supported_execution_options=[],
                lifecycle_status=LLMModelLifecycleStatus.ACTIVE,
                visibility_status=LLMCatalogEntryVisibility.SELECTABLE,
                provider_integration_id=integration.id,
                publisher="other",
                family=None,
                source_metadata=raw_declarations,
                projection_metadata={"capability_compiler_revision": "old"},
                hidden_reason=None,
                pricing=price.model_dump(mode="json"),
            )
        )
        await session.flush()
        before = (
            (
                await session.execute(
                    sa.select(RDBLLMCatalogEntry.__table__).where(
                        RDBLLMCatalogEntry.id == "b" * 32
                    )
                )
            )
            .mappings()
            .one()
        )
    source_repository = _CountingExactSourceRepository()
    active_repository = ActiveModelCapabilitiesRepository(
        session_manager=rdb_session_manager,
        catalog_repository=catalogs,
        source_repository=source_repository,
    )
    service = ModelCatalogReadService(
        operations=LLMCatalogOperationsRepository(
            session_manager=rdb_session_manager,
            catalog_repository=catalogs,
            integration_repository=integrations,
            source_repository=source_repository,
            active_repository=active_repository,
        )
    )
    page = await service.list_entries_by_integration(
        integration_id=integration.id,
        workspace_id=workspace_id,
        search=None,
        limit=10,
        offset=0,
    )
    assert isinstance(page, Success)
    assert len(page.value.entries) == 1
    active = page.value.entries[0]
    assert active.normalized_capabilities.capability_schema_version == 3
    assert active.normalized_capabilities.tool_calling.supported is True
    assert active.normalized_capabilities.context_window.max_input_tokens == 32000
    assert active.provider_model_identifier == model_id
    assert active.pricing == price
    expected_keys = (("openrouter", f"openrouter/{model_id}"),)
    assert source_repository.requested_keys == [expected_keys]
    selected = await service.resolve_agent_model_selection(
        workspace_id=workspace_id,
        selection_input=AgentModelSelectionInput(
            llm_provider_integration_id=integration.id, model_identifier=model_id
        ),
    )
    assert isinstance(selected, Success)
    assert selected.value.normalized_capabilities == active.normalized_capabilities
    assert selected.value.pricing == price
    assert selected.value.last_refreshed_at == before["updated_at"]
    assert source_repository.requested_keys == [expected_keys, expected_keys]
    async with rdb_session_manager() as session:
        after = (
            (
                await session.execute(
                    sa.select(RDBLLMCatalogEntry.__table__).where(
                        RDBLLMCatalogEntry.id == "b" * 32
                    )
                )
            )
            .mappings()
            .one()
        )
    assert dict(after) == dict(before)
    assert after["normalized_capabilities"] == legacy_capabilities
    assert after["source_metadata"] == raw_declarations
