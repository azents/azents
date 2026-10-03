"""Semantic catalog contract and new selection diagnostic assertions."""

import ast
import dataclasses
from unittest.mock import AsyncMock

import pytest
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
from azents.core.model_capability_projection import project_capabilities
from azents.core.workspace import WorkspaceCreate
from azents.rdb.session import SessionManager
from azents.repos.llm_catalog import LLMCatalogRepository
from azents.repos.llm_catalog.data import (
    CatalogProjectionProvenance,
    LLMCatalog,
    LLMCatalogEntry,
    LLMCatalogEntryCreate,
)
from azents.repos.llm_catalog_operations import LLMCatalogOperationsRepository
from azents.repos.llm_provider_integration import LLMProviderIntegrationRepository
from azents.repos.llm_provider_integration.data import LLMProviderIntegrationCreate
from azents.repos.workspace import WorkspaceRepository
from azents.services.llm_catalog import ModelCatalogEntryOutput, ModelCatalogReadService

_DESCRIPTORS = {"lowerer_target", "runtime_model_identifier"}


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
    assert capabilities.semantic_contract is not None
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
        snapshot_id = await catalog_repository.create_candidate_snapshot(
            session,
            catalog=catalog,
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
                    source_metadata={"provider_listing_source": "fixture"},
                    projection_metadata={
                        "projection_schema_version": "2",
                        "fixture": True,
                    },
                    hidden_reason=None,
                )
            ],
            diagnostics={"fixture": True},
            provenance=CatalogProjectionProvenance(
                source_snapshot_id=None,
                projection_schema_version="2",
                runtime_profile_resolver_revision="fixture",
                pydantic_ai_version="fixture",
                genai_prices_version=None,
                projection_fingerprint="f" * 64,
            ),
            catalog_configuration_version=1,
        )
        await catalog_repository.publish_candidate_snapshot(
            session,
            catalog_id=catalog.id,
            candidate_snapshot_id=snapshot_id,
            expected_current_snapshot_id=None,
            expected_catalog_configuration_version=1,
            expected_projection_fingerprint="f" * 64,
        )
    result = await ModelCatalogReadService(
        operations=LLMCatalogOperationsRepository(
            session_manager=rdb_session_manager,
            catalog_repository=catalog_repository,
            integration_repository=AsyncMock(spec=LLMProviderIntegrationRepository),
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
    assert selection.model_snapshot["snapshot_id"] == snapshot_id
    assert _DESCRIPTORS.isdisjoint(selection.model_snapshot)
