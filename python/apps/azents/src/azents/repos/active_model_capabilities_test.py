"""Exact local adoption, historical readability and coherent input revalidation."""

import copy
import dataclasses
import datetime
import json
from collections.abc import AsyncIterator, Mapping, Sequence
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.active_model_capabilities import (
    ActiveModelCapabilitiesUnavailable,
    ActiveModelMetadataUnavailable,
    CapturedStoredChoice,
    CompiledActiveChoice,
    CompiledActiveChoices,
    ConfiguredModelIdentity,
    apply_to_options,
    compile_capture,
    identities_for_options,
    require_selection,
)
from azents.core.agent import AgentModelSelection
from azents.core.enums import (
    LLMCatalogEntryVisibility,
    LLMCatalogPurpose,
    LLMCatalogScope,
    LLMModelDeveloper,
    LLMModelLifecycleStatus,
    LLMProvider,
)
from azents.core.llm_catalog import ModelCapabilities
from azents.core.model_capability_contract import ModelCapabilityFeature
from azents.core.model_capability_contract_test import _legacy_contract, _legacy_support
from azents.core.model_capability_evidence import ProviderCapabilityEvidence
from azents.core.model_catalog_source import (
    CatalogFact,
    ModelMetadataSourceKind,
    decode_catalog_source,
)
from azents.core.model_pricing import (
    ModelPricingDefinition,
    ModelPricingUnavailableReason,
)
from azents.rdb.models.llm_provider_integration import RDBLLMProviderIntegration
from azents.rdb.session_capabilities import ReadWriteSession, WriteSession
from azents.repos.active_model_capabilities import ActiveModelCapabilitiesRepository
from azents.repos.active_model_capabilities_data import CapturedActiveChoiceInputs
from azents.repos.agent.data import Agent
from azents.repos.llm_catalog import CatalogEntryWithCatalog, LLMCatalogRepository
from azents.repos.llm_catalog.data import LLMCatalog, LLMCatalogEntry
from azents.repos.model_metadata_source import ModelMetadataSourceRepository
from azents.repos.model_metadata_source_data import SourceProjectionMetadata
from azents.repos.workspace_model_settings.data import WorkspaceModelSettings
from azents.services.active_model_capabilities import (
    apply_to_agent_read,
    apply_to_workspace_read,
)
from azents.testing.model_selection import (
    make_test_model_selection,
    make_test_selectable_model_options,
)

_NOW = datetime.datetime(2026, 10, 4, tzinfo=datetime.UTC)


class _Manager:
    def __init__(self) -> None:
        self.raw_session = AsyncMock(spec=AsyncSession)
        self.session = ReadWriteSession(self.raw_session)
        self.active = False

    @asynccontextmanager
    async def __call__(self) -> AsyncIterator[WriteSession]:
        self.active = True
        try:
            yield self.session
        finally:
            self.active = False


def _integration(
    provider: LLMProvider = LLMProvider.OPENROUTER,
) -> RDBLLMProviderIntegration:
    return RDBLLMProviderIntegration(
        workspace_id="workspace",
        provider=provider,
        name="test",
        encrypted_credentials="unused",
        config=None,
        enabled=False,
    )


def _entry() -> CatalogEntryWithCatalog:
    catalog = LLMCatalog(
        id="catalog",
        scope=LLMCatalogScope.INTEGRATION,
        provider=LLMProvider.OPENROUTER,
        purpose=LLMCatalogPurpose.CONVERSATION,
        provider_integration_id="integration",
        entry_count=1,
        visible_count=1,
        hidden_count=0,
        last_success_at=_NOW,
        image_usable=None,
        diagnostics=None,
        sync_status=None,
    )
    entry = LLMCatalogEntry(
        id="entry",
        catalog_id=catalog.id,
        provider=LLMProvider.OPENROUTER,
        provider_model_identifier="openai/model",
        display_name="Saved display",
        normalized_capabilities={
            "capability_schema_version": 2,
            "tool_calling": {"supported": False},
        },
        supported_execution_options=[],
        lifecycle_status=LLMModelLifecycleStatus.ACTIVE,
        visibility_status=LLMCatalogEntryVisibility.SELECTABLE,
        provider_integration_id="integration",
        publisher=LLMModelDeveloper.OPENAI.value,
        family=None,
        source_metadata={
            "provider_metadata": {
                "architecture": {
                    "input_modalities": ["text", "image"],
                    "output_modalities": ["text"],
                },
                "supported_parameters": [
                    "tools",
                    "parallel_tool_calls",
                    "temperature",
                    "max_tokens",
                ],
            }
        },
        projection_metadata=None,
        hidden_reason=None,
        pricing=ModelPricingDefinition(
            rules=None,
            unavailable_reason=ModelPricingUnavailableReason.MODEL_UNMATCHED,
            source_key=None,
            source_model_key=None,
            collected_at=None,
        ),
        created_at=_NOW,
        updated_at=_NOW,
    )
    return CatalogEntryWithCatalog(catalog, entry)


def _selection() -> AgentModelSelection:
    return make_test_model_selection(
        integration_id="integration",
        provider=LLMProvider.OPENROUTER,
        model_identifier="openai/model",
    )


def _repository() -> tuple[
    ActiveModelCapabilitiesRepository, _Manager, AsyncMock, AsyncMock
]:
    manager = _Manager()
    catalogs = AsyncMock(spec=LLMCatalogRepository)
    source = AsyncMock(spec=ModelMetadataSourceRepository)
    catalogs.lock_integration.return_value = _integration()
    source.get_projection_metadata.return_value = SourceProjectionMetadata(
        source_key="litellm_catalog",
        source_kind=ModelMetadataSourceKind.LITELLM_JSON,
        collected_at=_NOW,
    )
    source.get_models.return_value = {}
    identity = ConfiguredModelIdentity.from_selection(_selection())
    catalogs.get_selectable_entries_for_identities.return_value = {identity: _entry()}
    return (
        ActiveModelCapabilitiesRepository(manager, catalogs, source),
        manager,
        catalogs,
        source,
    )


async def test_capture_recompiles_old_current_row_without_remote_or_writes() -> None:
    repository, manager, catalogs, source = _repository()
    selection = _selection()
    captured = await repository.capture_exact_choices(
        workspace_id="workspace",
        identities=[ConfiguredModelIdentity.from_selection(selection)],
    )
    assert not manager.active
    compiled = compile_capture(captured, selections=[selection])
    actual = require_selection(compiled, selection)
    assert actual.capabilities.supports(ModelCapabilityFeature.FUNCTION_CALLING)
    assert actual.capabilities.supports(ModelCapabilityFeature.INPUT_IMAGE)
    assert actual.capabilities.supports(ModelCapabilityFeature.TEMPERATURE)
    assert selection.normalized_capabilities == ModelCapabilities()
    assert actual.capabilities.capability_schema_version == 3
    assert catalogs.get_selectable_entries_for_identities.await_args.kwargs[
        "identities"
    ] == (ConfiguredModelIdentity.from_selection(selection),)
    assert source.get_models.await_args.kwargs["keys"] == (
        ("openrouter", "openrouter/openai/model"),
    )
    manager.raw_session.execute.assert_not_awaited()


async def test_exact_capture_deduplicates_but_keeps_user_order_and_lock_hierarchy() -> (
    None
):
    repository, manager, catalogs, source = _repository()
    order: list[str] = []

    async def integration(*args: object, **kwargs: object) -> RDBLLMProviderIntegration:
        order.append(f"integration:{kwargs['integration_id']}")
        return _integration()

    async def metadata(*args: object, **kwargs: object) -> SourceProjectionMetadata:
        order.append("source")
        return SourceProjectionMetadata(
            "litellm_catalog", ModelMetadataSourceKind.LITELLM_JSON, _NOW
        )

    async def entries(
        session: WriteSession,
        *,
        workspace_id: str,
        identities: Sequence[ConfiguredModelIdentity],
    ) -> dict[ConfiguredModelIdentity, CatalogEntryWithCatalog]:
        order.append("catalog")
        return {identity: _entry() for identity in identities}

    catalogs.lock_integration.side_effect = integration
    source.get_projection_metadata.side_effect = metadata
    catalogs.get_selectable_entries_for_identities.side_effect = entries
    a = ConfiguredModelIdentity("a", LLMProvider.OPENROUTER, "openai/model")
    b = ConfiguredModelIdentity("b", LLMProvider.OPENROUTER, "openai/model")
    captured = await repository.capture_exact_choices_in_session(
        manager.session, workspace_id="workspace", identities=[b, a, b]
    )
    assert [choice.identity for choice in captured.choices] == [b, a]
    assert order == ["integration:a", "integration:b", "source", "catalog"]


@pytest.mark.parametrize(
    "reason",
    [
        "integration_scope_unavailable",
        "provider_scope_mismatch",
        "exact_entry_unavailable",
    ],
)
async def test_scope_and_exact_missing_failures_keep_identity(reason: str) -> None:
    repository, manager, catalogs, source = _repository()
    if reason == "integration_scope_unavailable":
        catalogs.lock_integration.return_value = None
    elif reason == "provider_scope_mismatch":
        catalogs.lock_integration.return_value = _integration(LLMProvider.XAI)
    else:
        catalogs.get_selectable_entries_for_identities.return_value = {}
    selection = _selection()
    captured = await repository.capture_exact_choices_in_session(
        manager.session,
        workspace_id="workspace",
        identities=[ConfiguredModelIdentity.from_selection(selection)],
    )
    compiled = compile_capture(captured, selections=[selection])
    with pytest.raises(ActiveModelCapabilitiesUnavailable) as error:
        require_selection(compiled, selection)
    assert error.value.diagnostic.reason == reason
    assert error.value.diagnostic.identity == ConfiguredModelIdentity.from_selection(
        selection
    )
    if reason != "exact_entry_unavailable":
        source.get_models.assert_not_awaited()


async def test_revalidation_checks_inputs_and_presence_not_clocks_or_old_caps() -> None:
    repository, manager, catalogs, source = _repository()
    selection = _selection()
    identity = ConfiguredModelIdentity.from_selection(selection)
    captured = await repository.capture_exact_choices_in_session(
        manager.session, workspace_id="workspace", identities=[identity]
    )
    entry = _entry()
    catalogs.get_selectable_entries_for_identities.return_value = {
        identity: CatalogEntryWithCatalog(
            entry.catalog,
            dataclasses.replace(
                entry.entry,
                updated_at=_NOW + datetime.timedelta(days=1),
                normalized_capabilities={"ignored_old_view": True},
            ),
        )
    }
    assert await repository.inputs_match_in_session(manager.session, captured=captured)
    changed = copy.deepcopy(entry.entry.source_metadata)
    assert changed is not None
    changed["provider_metadata"]["supported_parameters"] = []
    catalogs.get_selectable_entries_for_identities.return_value = {
        identity: CatalogEntryWithCatalog(
            entry.catalog, dataclasses.replace(entry.entry, source_metadata=changed)
        )
    }
    assert not await repository.inputs_match_in_session(
        manager.session, captured=captured
    )
    catalogs.get_selectable_entries_for_identities.return_value = {}
    assert not await repository.inputs_match_in_session(
        manager.session, captured=captured
    )
    original_metadata = captured.catalog_choices[0].source_metadata
    assert original_metadata is not None
    assert original_metadata["provider_metadata"]["supported_parameters"] != []


async def test_page_capture_reuses_rows_after_scope_locks() -> None:
    repository, manager, catalogs, source = _repository()
    scope = await repository.prepare_read_scope_in_session(
        manager.session, workspace_id="workspace", integration_ids=["integration"]
    )
    captured = await repository.capture_current_entries_in_session(
        manager.session, scope=scope, integration_id="integration", entries=[_entry()]
    )
    assert len(captured.choices) == 1
    catalogs.get_selectable_entries_for_identities.assert_not_awaited()
    source.get_models.assert_awaited_once()


def test_compilation_restores_json_tuple_evidence_and_preserves_explicit_no() -> None:
    selection = _selection()
    identity = ConfiguredModelIdentity.from_selection(selection)
    evidence = ProviderCapabilityEvidence(
        input_modalities=CatalogFact(state="value", value=("text",)),
        function_calling=CatalogFact(state="value", value=False),
    )
    metadata = _entry().entry.source_metadata
    assert metadata is not None
    choice = CapturedStoredChoice(
        identity,
        {
            "provider_metadata": metadata["provider_metadata"],
            "capability_evidence": evidence.model_dump(mode="json"),
        },
        (),
        (),
        LLMModelDeveloper.OPENAI,
        "catalog",
    )
    captured = CapturedActiveChoiceInputs("workspace", (choice,), (), None, ())
    compiled = require_selection(
        compile_capture(captured, selections=[selection]), selection
    )
    assert not compiled.capabilities.supports(ModelCapabilityFeature.FUNCTION_CALLING)
    assert not compiled.capabilities.supports(ModelCapabilityFeature.INPUT_IMAGE)


def test_temporary_option_overlay_preserves_settings_and_unused_missing_fallback() -> (
    None
):
    selection = _selection()
    options = make_test_selectable_model_options(selection)
    fallback = make_test_model_selection(
        integration_id="integration",
        provider=LLMProvider.OPENROUTER,
        model_identifier="missing",
    )
    options[0].candidates.append(
        options[0].candidates[0].model_copy(update={"model_selection": fallback})
    )
    raw = copy.deepcopy(options)
    outcome = CompiledActiveChoice(
        ConfiguredModelIdentity.from_selection(selection),
        ModelCapabilities(structured_response=True),
        (),
        "catalog",
    )
    missing = ActiveModelMetadataUnavailable(
        ConfiguredModelIdentity.from_selection(fallback), "exact_entry_unavailable"
    )
    compiled = CompiledActiveChoices((outcome, missing))
    projected = apply_to_options(options, compiled)
    assert options == raw
    assert identities_for_options(projected) == identities_for_options(options)
    assert all(
        before.settings == after.settings
        for before, after in zip(
            options[0].candidates, projected[0].candidates, strict=True
        )
    )
    assert (
        require_selection(compiled, projected[0].candidates[0].model_selection)
        is outcome
    )
    fallback_metadata = projected[0].candidates[1].model_selection.source_metadata
    assert fallback_metadata is not None
    assert fallback_metadata["active_capabilities"]["status"] == "unavailable"


def test_real_agent_workspace_orphan_refinements_adopt_current_facts() -> None:
    contract = _legacy_contract()
    contract["function_calling"] = _legacy_support("unknown")
    refinement = {
        "state": "conditional",
        "origin": "explicit",
        "predicate": {"reasoning_efforts": None, "function_tools": True},
    }
    contract["parallel_function_calls"] = refinement
    contract["strict_function_schema"] = refinement
    selection_json = _selection().model_dump(mode="json")
    selection_json["normalized_capabilities"] = {"semantic_contract": contract}
    selection = AgentModelSelection.model_validate(selection_json)
    option_json = make_test_selectable_model_options(selection)[0].model_dump(
        mode="json"
    )
    option_json["candidates"][0]["model_selection"] = selection_json
    agent_json = {
        "id": "agent",
        "workspace_id": "workspace",
        "name": "test",
        "model_selection": selection_json,
        "lightweight_model_selection": selection_json,
        "selectable_model_options": [option_json],
        "main_model_label": "default",
        "lightweight_model_label": "default",
        "enabled": True,
        "external_channel_default_response_mode": "mention_only",
        "lifecycle_status": "active",
        "type": "public",
        "runtime_profile_id": None,
        "runtime_profile_selection_version": 1,
        "runtime_capability": "none",
        "runtime_capability_version": 1,
        "terminal_enabled": True,
        "tool_search_enabled": True,
        "auto_archive_ttl_days": 30,
        "created_at": _NOW,
        "updated_at": _NOW,
    }
    raw = copy.deepcopy(agent_json)
    agent = Agent.model_validate(agent_json)
    workspace = WorkspaceModelSettings.model_validate(
        {
            "workspace_id": "workspace",
            "default_model_selection": selection_json,
            "default_lightweight_model_selection": None,
            "default_selectable_model_options": [option_json],
            "default_main_model_label": "default",
            "default_lightweight_model_label": "default",
            "created_at": _NOW,
            "updated_at": _NOW,
        }
    )
    assert not agent.model_selection.normalized_capabilities.tool_calling.supported
    choice = CapturedStoredChoice(
        ConfiguredModelIdentity.from_selection(selection),
        _entry().entry.source_metadata,
        (),
        (),
        LLMModelDeveloper.OPENAI,
        "catalog",
    )
    compiled = compile_capture(
        CapturedActiveChoiceInputs("workspace", (choice,), (), None, ()),
        selections=[selection],
    )
    projected = apply_to_agent_read(agent, compiled)
    assert projected.model_selection.normalized_capabilities.tool_calling.supported
    active_tools = projected.model_selection.normalized_capabilities.tool_calling
    assert active_tools.parallel_tool_calls
    assert agent_json == raw
    assert not agent.model_selection.normalized_capabilities.tool_calling.supported
    active_workspace = apply_to_workspace_read(workspace, compiled)
    assert active_workspace.default_lightweight_model_selection is None
    active_main = active_workspace.default_model_selection
    stored_main = workspace.default_model_selection
    assert active_main is not None
    assert stored_main is not None
    assert active_main.normalized_capabilities.tool_calling.supported
    assert not stored_main.normalized_capabilities.tool_calling.supported


@pytest.mark.parametrize(
    "metadata",
    [
        {"provider_metadata": []},
        {"provider_metadata": {"supported_parameters": "tools"}},
        {"provider_metadata": {"architecture": {"input_modalities": True}}},
        {
            "capability_evidence": {
                "function_calling": {"state": "value", "value": "yes"}
            }
        },
        {"capability_evidence": {"unknown_feature": True}},
    ],
)
def test_malformed_stored_declarations_diagnose_without_saved_fallback(
    metadata: Mapping[str, object],
) -> None:
    selection = _selection().model_copy(
        update={"normalized_capabilities": ModelCapabilities(structured_response=True)}
    )
    identity = ConfiguredModelIdentity.from_selection(selection)
    choice = CapturedStoredChoice(
        identity, metadata, (), (), LLMModelDeveloper.OPENAI, "catalog"
    )
    compiled = compile_capture(
        CapturedActiveChoiceInputs("workspace", (choice,), (), None, ()),
        selections=[selection],
    )
    with pytest.raises(ActiveModelCapabilitiesUnavailable) as error:
        require_selection(compiled, selection)
    assert error.value.diagnostic.reason == "stored_declarations_invalid"
    assert error.value.diagnostic.identity == identity
    assert selection.normalized_capabilities.structured_response


async def test_malformed_execution_option_keeps_selected_identity() -> None:
    repository, manager, catalogs, source = _repository()
    selection = _selection()
    identity = ConfiguredModelIdentity.from_selection(selection)
    entry = _entry()
    catalogs.get_selectable_entries_for_identities.return_value = {
        identity: CatalogEntryWithCatalog(
            entry.catalog,
            dataclasses.replace(
                entry.entry, supported_execution_options=["unknown_option"]
            ),
        )
    }
    captured = await repository.capture_exact_choices_in_session(
        manager.session, workspace_id="workspace", identities=[identity]
    )
    compiled = compile_capture(captured, selections=[selection])
    with pytest.raises(ActiveModelCapabilitiesUnavailable) as error:
        require_selection(compiled, selection)
    assert error.value.diagnostic.reason == "stored_declarations_invalid"
    assert error.value.diagnostic.identity == identity


def test_foreign_source_route_is_never_same_named_model_evidence() -> None:
    selection = _selection()
    identity = ConfiguredModelIdentity.from_selection(selection)
    foreign = decode_catalog_source(
        json.dumps(
            {
                selection.model_identifier: {
                    "litellm_provider": "openai",
                    "mode": "chat",
                    "supports_function_calling": True,
                    "supports_vision": True,
                }
            }
        ).encode()
    )
    choice = CapturedStoredChoice(
        identity, None, foreign.models, (), LLMModelDeveloper.OPENAI, "catalog"
    )
    compiled = require_selection(
        compile_capture(
            CapturedActiveChoiceInputs("workspace", (choice,), (), None, ()),
            selections=[selection],
        ),
        selection,
    )
    assert not compiled.capabilities.supports(ModelCapabilityFeature.INPUT_IMAGE)
    assert not compiled.capabilities.supports(ModelCapabilityFeature.FUNCTION_CALLING)


async def test_empty_capture_performs_no_scope_source_or_catalog_io() -> None:
    repository, manager, catalogs, source = _repository()
    captured = await repository.capture_exact_choices_in_session(
        manager.session, workspace_id="workspace", identities=[]
    )
    assert captured.choices == ()
    assert captured.source_expectations == ()
    catalogs.lock_integration.assert_not_awaited()
    catalogs.get_selectable_entries_for_identities.assert_not_awaited()
    source.get_projection_metadata.assert_not_awaited()
    source.get_models.assert_not_awaited()
