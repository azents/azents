"""Coherent latest-state reads and server-owned selected price copying."""

import copy
import dataclasses
import datetime
from unittest.mock import AsyncMock

import pytest
from azcommon.result import Success

from azents.core.active_model_capabilities import (
    ActiveModelCapabilitiesUnavailable,
    CapturedStoredChoice,
    ConfiguredModelIdentity,
)
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
from azents.core.llm_catalog_sync import CatalogProjectionVersion
from azents.core.model_catalog_source import CatalogSourceModel
from azents.repos.active_model_capabilities_data import CapturedActiveChoiceInputs
from azents.repos.llm_catalog import CatalogEntryWithCatalog
from azents.repos.llm_catalog.data import (
    LLMCatalog,
    LLMCatalogEntry,
    LLMCatalogEntryList,
    LLMCatalogSyncStatus,
)
from azents.repos.llm_catalog_operations import (
    CapturedSelectableCatalogEntry,
    CatalogReadPage,
    LLMCatalogOperationsRepository,
)
from azents.services.llm_catalog import ModelCatalogReadService
from azents.testing.model_metadata import make_test_source, make_test_source_payload

_NOW = datetime.datetime(2026, 10, 3, tzinfo=datetime.UTC)


def _active_inputs(
    entries: list[LLMCatalogEntry],
    source_models: tuple[CatalogSourceModel, ...] = (),
) -> CapturedActiveChoiceInputs:
    return CapturedActiveChoiceInputs(
        workspace_id="workspace",
        choices=tuple(
            CapturedStoredChoice(
                identity=ConfiguredModelIdentity(
                    integration_id="integration",
                    provider=entry.provider,
                    model_identifier=entry.provider_model_identifier,
                ),
                source_metadata=entry.source_metadata,
                source_models=source_models,
                supported_execution_options=(),
                model_developer=None,
                catalog_id=entry.catalog_id,
            )
            for entry in entries
        ),
        catalog_choices=(),
        source_metadata=None,
        source_expectations=(),
    )


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
        current_projection_version=None,
        active_inputs=_active_inputs([]),
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
    operations.selectable_entry.return_value = CapturedSelectableCatalogEntry(
        selected=CatalogEntryWithCatalog(catalog=catalog, entry=entry),
        active_inputs=_active_inputs([entry], (source.models[0].model,)),
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
    operations.selectable_entry.return_value = CapturedSelectableCatalogEntry(
        selected=CatalogEntryWithCatalog(
            catalog=catalog, entry=dataclasses.replace(entry, pricing=newer)
        ),
        active_inputs=_active_inputs([entry], (source.models[0].model,)),
    )
    reselected = await ModelCatalogReadService(
        operations
    ).resolve_agent_model_selection(workspace_id="workspace", selection_input=selection)
    assert isinstance(reselected, Success)
    assert reselected.value.pricing == newer
    assert result.value.pricing == price
    assert reselected.value.pricing != result.value.pricing


@pytest.mark.parametrize(
    ("version", "stale"),
    [
        (CatalogProjectionVersion("1", "5"), True),
        (CatalogProjectionVersion("2", "4"), True),
        (CatalogProjectionVersion(None, None), True),
        (CatalogProjectionVersion("2", "5"), False),
    ],
)
async def test_read_reports_current_code_drift_without_mutating_successful_page(
    version: CatalogProjectionVersion, stale: bool
) -> None:
    now = datetime.datetime.now(datetime.UTC)
    catalog = dataclasses.replace(
        _catalog(),
        provider=LLMProvider.OPENROUTER,
        last_success_at=now,
        sync_status=None,
    )
    operations = AsyncMock(spec=LLMCatalogOperationsRepository)
    captured = CatalogReadPage(
        page=LLMCatalogEntryList(catalog=catalog, entries=[], total=0),
        latest_workspace_sync=None,
        current_projection_version=version,
        active_inputs=_active_inputs([]),
    )
    operations.read_page.return_value = captured
    result = await ModelCatalogReadService(operations).list_entries_by_integration(
        integration_id="integration",
        workspace_id="workspace",
        search=None,
        limit=20,
        offset=0,
    )
    assert isinstance(result, Success)
    assert result.value.stale is stale
    assert result.value.last_success_at == now
    assert captured.page.catalog is catalog
    assert captured.current_projection_version == version


async def test_picker_and_selection_compile_v2_declarations_not_saved_flags() -> None:
    source = make_test_source(
        make_test_source_payload(
            {
                "unused": {
                    "litellm_provider": "openai",
                    "supports_function_calling": True,
                }
            }
        )
    )
    historical = {
        "capability_schema_version": 2,
        "tool_calling": {"supported": False},
        "reasoning": {"supported": False, "effort_levels": []},
    }
    entry = LLMCatalogEntry(
        id="old-entry",
        catalog_id="catalog",
        created_at=_NOW,
        updated_at=_NOW,
        provider=LLMProvider.OPENROUTER,
        provider_model_identifier="publisher/literal",
        display_name="Provider model",
        normalized_capabilities=historical,
        supported_execution_options=[],
        lifecycle_status=LLMModelLifecycleStatus.ACTIVE,
        visibility_status=LLMCatalogEntryVisibility.SELECTABLE,
        provider_integration_id="integration",
        publisher="other",
        family=None,
        source_metadata={
            "provider_metadata": {
                "supported_parameters": ["tools", "parallel_tool_calls"],
            }
        },
        projection_metadata={"capability_compiler_revision": "old"},
        hidden_reason=None,
        pricing=source.models[0].pricing,
    )
    before = copy.deepcopy(dataclasses.asdict(entry))
    catalog = dataclasses.replace(
        _catalog(), provider=LLMProvider.OPENROUTER, last_success_at=_NOW
    )
    captured = _active_inputs([entry])
    operations = AsyncMock(spec=LLMCatalogOperationsRepository)
    operations.read_page.return_value = CatalogReadPage(
        page=LLMCatalogEntryList(catalog=catalog, entries=[entry], total=1),
        latest_workspace_sync=None,
        current_projection_version=CatalogProjectionVersion("2", "5"),
        active_inputs=captured,
    )
    operations.selectable_entry.return_value = CapturedSelectableCatalogEntry(
        selected=CatalogEntryWithCatalog(catalog=catalog, entry=entry),
        active_inputs=captured,
    )
    service = ModelCatalogReadService(operations)
    page = await service.list_entries_by_integration(
        integration_id="integration",
        workspace_id="workspace",
        search=None,
        limit=20,
        offset=0,
    )
    selected = await service.resolve_agent_model_selection(
        workspace_id="workspace",
        selection_input=AgentModelSelectionInput(
            llm_provider_integration_id="integration",
            model_identifier="publisher/literal",
        ),
    )
    assert isinstance(page, Success)
    assert isinstance(selected, Success)
    active = page.value.entries[0]
    assert active.normalized_capabilities.capability_schema_version == 3
    assert active.normalized_capabilities.tool_calling.supported is True
    assert active.normalized_capabilities == selected.value.normalized_capabilities
    assert active.pricing == entry.pricing == selected.value.pricing
    assert selected.value.last_refreshed_at == entry.updated_at
    assert selected.value.model_identifier == entry.provider_model_identifier
    assert dataclasses.asdict(entry) == before
    operations.read_page.assert_awaited_once()
    operations.selectable_entry.assert_awaited_once()


async def test_exact_source_enrichment_does_not_borrow_other_model_support() -> None:
    source = make_test_source(
        make_test_source_payload(
            {
                "selected": {"litellm_provider": "openai"},
                "other": {
                    "litellm_provider": "openai",
                    "supports_function_calling": True,
                },
            }
        )
    )
    entry = LLMCatalogEntry(
        id="entry",
        catalog_id="catalog",
        created_at=_NOW,
        updated_at=_NOW,
        provider=LLMProvider.OPENAI,
        provider_model_identifier="selected",
        display_name="Exact model",
        normalized_capabilities={"unreadable_legacy_view": "not active authority"},
        supported_execution_options=[],
        lifecycle_status=LLMModelLifecycleStatus.ACTIVE,
        visibility_status=LLMCatalogEntryVisibility.SELECTABLE,
        provider_integration_id=None,
        publisher="openai",
        family=None,
        source_metadata=None,
        projection_metadata=None,
        hidden_reason=None,
        pricing=source.models[0].pricing,
    )
    operations = AsyncMock(spec=LLMCatalogOperationsRepository)
    operations.selectable_entry.return_value = CapturedSelectableCatalogEntry(
        selected=CatalogEntryWithCatalog(catalog=_catalog(), entry=entry),
        active_inputs=_active_inputs(
            [entry], tuple(model.model for model in source.models)
        ),
    )
    result = await ModelCatalogReadService(operations).resolve_agent_model_selection(
        workspace_id="workspace",
        selection_input=AgentModelSelectionInput(
            llm_provider_integration_id="integration", model_identifier="selected"
        ),
    )
    assert isinstance(result, Success)
    assert result.value.normalized_capabilities.tool_calling.supported is False
    assert result.value.normalized_capabilities.capability_schema_version == 3


async def test_invalid_declarations_cannot_be_copied_as_a_new_selection() -> None:
    source = make_test_source(
        make_test_source_payload({"literal": {"litellm_provider": "openai"}})
    )
    entry = LLMCatalogEntry(
        id="entry",
        catalog_id="catalog",
        created_at=_NOW,
        updated_at=_NOW,
        provider=LLMProvider.OPENROUTER,
        provider_model_identifier="publisher/literal",
        display_name="Stored identity",
        normalized_capabilities={"tool_calling": {"supported": True}},
        supported_execution_options=[],
        lifecycle_status=LLMModelLifecycleStatus.ACTIVE,
        visibility_status=LLMCatalogEntryVisibility.SELECTABLE,
        provider_integration_id="integration",
        publisher="other",
        family=None,
        source_metadata={"provider_metadata": {"supported_parameters": "malformed"}},
        projection_metadata=None,
        hidden_reason=None,
        pricing=source.models[0].pricing,
    )
    catalog = dataclasses.replace(_catalog(), provider=LLMProvider.OPENROUTER)
    capture = _active_inputs([entry])
    operations = AsyncMock(spec=LLMCatalogOperationsRepository)
    operations.read_page.return_value = CatalogReadPage(
        page=LLMCatalogEntryList(catalog=catalog, entries=[entry], total=1),
        latest_workspace_sync=None,
        current_projection_version=None,
        active_inputs=capture,
    )
    operations.selectable_entry.return_value = CapturedSelectableCatalogEntry(
        selected=CatalogEntryWithCatalog(catalog=catalog, entry=entry),
        active_inputs=capture,
    )
    service = ModelCatalogReadService(operations)
    result = await service.list_entries_by_integration(
        integration_id="integration",
        workspace_id="workspace",
        search=None,
        limit=10,
        offset=0,
    )
    assert isinstance(result, Success)
    [visible] = result.value.entries
    assert visible.provider_model_identifier == "publisher/literal"
    assert visible.normalized_capabilities.tool_calling.supported is False
    assert visible.source_metadata is not None
    assert visible.source_metadata["active_capabilities"]["status"] == "unavailable"
    with pytest.raises(ActiveModelCapabilitiesUnavailable):
        await service.resolve_agent_model_selection(
            workspace_id="workspace",
            selection_input=AgentModelSelectionInput(
                llm_provider_integration_id="integration",
                model_identifier="publisher/literal",
            ),
        )
    assert entry.normalized_capabilities == {"tool_calling": {"supported": True}}
