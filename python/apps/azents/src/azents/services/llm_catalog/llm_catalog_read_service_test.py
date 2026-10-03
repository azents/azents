"""Coherent latest-state reads and server-owned selected price copying."""

import dataclasses
import datetime
from unittest.mock import AsyncMock

from azcommon.result import Success

from azents.core.agent import AgentModelSelectionInput
from azents.core.enums import (
    LLMCatalogAttemptStatus,
    LLMCatalogEntryVisibility,
    LLMCatalogPurpose,
    LLMCatalogScope,
    LLMModelLifecycleStatus,
    LLMProvider,
)
from azents.core.llm_catalog import ModelCapabilities
from azents.repos.llm_catalog import CatalogEntryWithCatalog
from azents.repos.llm_catalog.data import (
    LLMCatalog,
    LLMCatalogEntry,
    LLMCatalogEntryList,
    LLMCatalogSyncStatus,
)
from azents.repos.llm_catalog_operations import (
    CatalogReadPage,
    LLMCatalogOperationsRepository,
)
from azents.services.llm_catalog import ModelCatalogReadService
from azents.testing.model_metadata import make_test_source, make_test_source_payload

_NOW = datetime.datetime(2026, 10, 3, tzinfo=datetime.UTC)


def _catalog() -> LLMCatalog:
    return LLMCatalog(
        id="catalog",
        scope=LLMCatalogScope.INTEGRATION,
        provider=LLMProvider.AWS_BEDROCK,
        purpose=LLMCatalogPurpose.CONVERSATION,
        provider_integration_id="integration",
        entry_count=0,
        visible_count=0,
        hidden_count=0,
        last_success_at=None,
        image_usable=None,
        diagnostics=None,
        sync_status=LLMCatalogSyncStatus(
            owner_id="catalog",
            work_token=None,
            status=LLMCatalogAttemptStatus.FAILED,
            started_at=_NOW,
            finished_at=_NOW,
            failure_code="AccessDeniedException",
            failure_message="Provider listing failed.",
            action_hint="Check integration credentials and provider permissions.",
            fetched_count=0,
            matched_count=0,
            skipped_count=0,
            hidden_count=0,
            diagnostics={"failure_category": "user_catalog_credentials_or_permissions"},
        ),
    )


async def test_read_returns_latest_failed_state_without_successful_data() -> None:
    operations = AsyncMock(spec=LLMCatalogOperationsRepository)
    operations.read_page.return_value = CatalogReadPage(
        page=LLMCatalogEntryList(catalog=_catalog(), entries=[], total=0),
        latest_workspace_sync=None,
    )
    result = await ModelCatalogReadService(operations).list_entries_by_integration(
        integration_id="integration",
        workspace_id="workspace",
        search=None,
        limit=20,
        offset=0,
    )
    assert isinstance(result, Success)
    assert result.value.last_success_at is None
    assert result.value.latest_sync is not None
    assert result.value.latest_sync.status == "failed"
    assert result.value.latest_sync.failure_code == "AccessDeniedException"
    assert "id" not in result.value.latest_sync.model_dump()
    assert result.value.stale is True


async def test_selection_copies_exact_prices_and_latest_update_time() -> None:
    source = make_test_source(
        make_test_source_payload(
            {
                "gpt-test": {
                    "litellm_provider": "openai",
                    "input_cost_per_token": 0.000001,
                    "output_cost_per_token": 0.000002,
                }
            }
        )
    )
    price = source.models[0].pricing
    entry = LLMCatalogEntry(
        id="entry",
        catalog_id="catalog",
        created_at=_NOW - datetime.timedelta(days=1),
        updated_at=_NOW,
        provider=LLMProvider.OPENAI,
        provider_model_identifier="gpt-test",
        display_name="GPT Test",
        normalized_capabilities=ModelCapabilities().model_dump(mode="json"),
        supported_execution_options=[],
        lifecycle_status=LLMModelLifecycleStatus.ACTIVE,
        visibility_status=LLMCatalogEntryVisibility.SELECTABLE,
        provider_integration_id=None,
        publisher="openai",
        family=None,
        source_metadata=None,
        projection_metadata=None,
        hidden_reason=None,
        pricing=price,
    )
    operations = AsyncMock(spec=LLMCatalogOperationsRepository)
    catalog = dataclasses.replace(
        _catalog(),
        scope=LLMCatalogScope.SYSTEM,
        provider=LLMProvider.OPENAI,
        provider_integration_id=None,
        entry_count=1,
        visible_count=1,
        last_success_at=_NOW,
    )
    operations.selectable_entry.return_value = CatalogEntryWithCatalog(
        catalog=catalog, entry=entry
    )
    selection = AgentModelSelectionInput(
        llm_provider_integration_id="integration", model_identifier="gpt-test"
    )
    result = await ModelCatalogReadService(operations).resolve_agent_model_selection(
        workspace_id="workspace", selection_input=selection
    )
    assert isinstance(result, Success)
    assert result.value.pricing == price
    assert result.value.last_refreshed_at == _NOW
    assert "snapshot_id" not in result.value.model_snapshot
    assert result.value.model_identifier == "gpt-test"
    newer = (
        make_test_source(
            make_test_source_payload(
                {
                    "gpt-test": {
                        "litellm_provider": "openai",
                        "input_cost_per_token": 0.000003,
                        "output_cost_per_token": 0.000004,
                    }
                }
            )
        )
        .models[0]
        .pricing
    )
    operations.selectable_entry.return_value = CatalogEntryWithCatalog(
        catalog=catalog, entry=dataclasses.replace(entry, pricing=newer)
    )
    reselected = await ModelCatalogReadService(
        operations
    ).resolve_agent_model_selection(workspace_id="workspace", selection_input=selection)
    assert isinstance(reselected, Success)
    assert reselected.value.pricing == newer
    assert result.value.pricing == price
    assert reselected.value.pricing != result.value.pricing
