"""Seed requests use current public model options and exact catalog identities."""

import datetime
from dataclasses import replace
from typing import NamedTuple
from unittest.mock import Mock

import pytest
from azents.api.public.agent.v1.data import AgentCreateRequest as ProductAgentCreateRequest
from azentspublicclient.api.agent_v1_api import AgentV1Api
from azentspublicclient.api.llm_provider_integration_v1_api import LLMProviderIntegrationV1Api
from azentspublicclient.exceptions import ApiException, NotFoundException
from azentspublicclient.models.agent_response import AgentResponse
from azentspublicclient.models.llm_catalog_scope import LLMCatalogScope
from azentspublicclient.models.llm_provider import LLMProvider
from azentspublicclient.models.model_capabilities import ModelCapabilities
from azentspublicclient.models.model_catalog_entry_list_response import (
    ModelCatalogEntryListResponse,
)
from azentspublicclient.models.model_catalog_entry_response import ModelCatalogEntryResponse
from azentspublicclient.models.model_catalog_sync_status_response import (
    ModelCatalogSyncStatusResponse,
)
from azentspublicclient.models.model_pricing_definition import ModelPricingDefinition
from azentspublicclient.models.model_pricing_unavailable_reason import ModelPricingUnavailableReason

import testenv.seed.agent as agent_module
import testenv.seed.llm as llm_module
from testenv.runtime_config import TestenvConfig as RuntimeConfig
from testenv.seed.agent import AgentService
from testenv.seed.llm import LLM
from testenv.seed.types import Integration, User, Workspace

_CONFIG = RuntimeConfig(
    public_url="https://public.test",
    admin_url="https://admin.test",
    testenv_api_url="https://testenv.test",
)


class _SeedValues(NamedTuple):
    user: User
    workspace: Workspace
    integration: Integration


def _values() -> _SeedValues:
    user = User(
        email="seed@example.test", access_token="fixture-token", refresh_token="fixture-refresh"
    )
    workspace = Workspace(handle="seed", name="Seed Workspace", owner=user)
    return _SeedValues(
        user,
        workspace,
        Integration(id="integration", workspace=workspace, provider="openai", name="Fixture"),
    )


def _agent_api(monkeypatch: pytest.MonkeyPatch) -> Mock:
    api = Mock(spec=AgentV1Api)
    api.agent_v1_create_agent.return_value = Mock(spec=AgentResponse, id="agent")
    monkeypatch.setattr(agent_module, "public_client", Mock())
    monkeypatch.setattr(agent_module, "AgentV1Api", Mock(return_value=api))
    return api


def test_agent_seed_serializes_exact_canonical_options_and_memory_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    values = _values()
    api = _agent_api(monkeypatch)
    result = AgentService(_CONFIG).create(
        *values, model="literal/provider/model", name="Exact seed", memory_enabled=False
    )
    call = api.agent_v1_create_agent.call_args
    assert call is not None
    payload = call.kwargs["agent_create_request"].to_dict()
    request = ProductAgentCreateRequest.model_validate(payload)
    assert request.selectable_model_options is not None
    assert len(request.selectable_model_options) == 1
    option = request.selectable_model_options[0]
    assert request.main_model_label == request.lightweight_model_label == option.label
    assert option.candidates[0].model_selection.llm_provider_integration_id == "integration"
    assert option.candidates[0].model_selection.model_identifier == "literal/provider/model"
    assert request.memory_enabled is False
    assert (
        "pricing" not in payload["selectable_model_options"][0]["candidates"][0]["model_selection"]
    )
    assert "model_config_id" not in payload and "additional_properties" not in payload
    assert call.kwargs["_headers"] == {"Authorization": "Bearer fixture-token"}
    assert result.id == "agent" and result.model_slug == "literal/provider/model"
    api.agent_v1_create_agent.assert_called_once()


def test_missing_model_rejection_propagates_without_default_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = _agent_api(monkeypatch)
    api.agent_v1_create_agent.side_effect = ApiException(status=422, reason="Model unavailable")
    with pytest.raises(ApiException):
        AgentService(_CONFIG).create(*_values(), model="removed-model")
    api.agent_v1_create_agent.assert_called_once()


def test_seed_rejects_wrong_workspace_before_request(monkeypatch: pytest.MonkeyPatch) -> None:
    api = _agent_api(monkeypatch)
    values = _values()
    foreign = replace(values.integration, workspace=replace(values.workspace, handle="other"))
    with pytest.raises(ValueError, match="belong"):
        AgentService(_CONFIG).create(values.user, values.workspace, foreign, model="gpt-test")
    api.agent_v1_create_agent.assert_not_called()


def _entry(provider: LLMProvider, identifier: str) -> ModelCatalogEntryResponse:
    return ModelCatalogEntryResponse(
        id="entry",
        provider=provider,
        provider_model_identifier=identifier,
        display_name=identifier,
        normalized_capabilities=ModelCapabilities(),
        supported_execution_options=[],
        lifecycle_status="active",
        visibility_status="selectable",
        publisher=None,
        family=None,
        source_metadata=None,
        projection_metadata=None,
        pricing=ModelPricingDefinition(
            rules=None,
            unavailable_reason=ModelPricingUnavailableReason.SOURCE_UNAVAILABLE,
            source_key=None,
            source_model_key=None,
            collected_at=None,
        ),
    )


def _catalog(entries: list[ModelCatalogEntryResponse]) -> ModelCatalogEntryListResponse:
    return ModelCatalogEntryListResponse(
        catalog_id="catalog",
        catalog_scope=LLMCatalogScope.INTEGRATION,
        last_success_at=None,
        latest_sync=None,
        stale=False,
        sync_available_at=None,
        automatic_retry_blocked=False,
        entries=entries,
        total=len(entries),
        limit=100,
        offset=0,
    )


def _catalog_api(monkeypatch: pytest.MonkeyPatch, entries: list[ModelCatalogEntryResponse]) -> Mock:
    api = Mock(spec=LLMProviderIntegrationV1Api)
    api.llm_provider_integration_v1_list_integration_catalog_entries.return_value = _catalog(
        entries
    )
    monkeypatch.setattr(llm_module, "public_client", Mock())
    monkeypatch.setattr(llm_module, "LLMProviderIntegrationV1Api", Mock(return_value=api))
    return api


def test_seed_reads_generated_current_catalog_and_keeps_actual_identifier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = _catalog_api(monkeypatch, [_entry(LLMProvider.OPENAI, "actual-first-model")])
    assert LLM(_CONFIG).first_model_identifier(*_values()) == "actual-first-model"
    api.llm_provider_integration_v1_list_integration_catalog_entries.assert_called_once_with(
        handle="seed",
        integration_id="integration",
        _headers={"Authorization": "Bearer fixture-token"},
        _request_timeout=10,
    )


def test_empty_catalog_fails_instead_of_substituting_workspace_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _catalog_api(monkeypatch, [])
    with pytest.raises(RuntimeError, match="no selectable models"):
        LLM(_CONFIG).first_model_identifier(*_values())


def test_catalog_provider_mismatch_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    _catalog_api(monkeypatch, [_entry(LLMProvider.ANTHROPIC, "other-provider-model")])
    with pytest.raises(RuntimeError, match="does not match"):
        LLM(_CONFIG).first_model_identifier(*_values())


def _initial_catalog(
    entries: list[ModelCatalogEntryResponse],
    status: str | None,
    scope: LLMCatalogScope,
) -> ModelCatalogEntryListResponse:
    listing = _catalog(entries)
    listing.catalog_scope = scope
    if status is not None:
        now = datetime.datetime(2026, 10, 4, tzinfo=datetime.UTC)
        listing.latest_sync = ModelCatalogSyncStatusResponse(
            status=status,
            started_at=now,
            finished_at=None if status == "running" else now,
            failure_code="FixtureFailure" if status == "failed" else None,
            failure_message=None,
            action_hint=None,
            fetched_count=len(entries),
            matched_count=len(entries),
            skipped_count=0,
            hidden_count=0,
        )
        listing.last_success_at = now if status == "succeeded" else None
    return listing


def _polling_api(monkeypatch: pytest.MonkeyPatch) -> Mock:
    api = _catalog_api(monkeypatch, [])
    monkeypatch.setattr(llm_module.time, "monotonic", Mock(return_value=0.0))
    monkeypatch.setattr(llm_module.time, "sleep", Mock())
    return api


def test_initial_seed_waits_for_actual_integration_publication(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = _polling_api(monkeypatch)
    agent_api = _agent_api(monkeypatch)
    api.llm_provider_integration_v1_list_integration_catalog_entries.side_effect = [
        NotFoundException(status=404),
        _initial_catalog(
            [_entry(LLMProvider.OPENAI, "wrong-system-model")],
            "succeeded",
            LLMCatalogScope.SYSTEM,
        ),
        _initial_catalog([], None, LLMCatalogScope.INTEGRATION),
        _initial_catalog(
            [_entry(LLMProvider.OPENAI, "not-ready-model")],
            "running",
            LLMCatalogScope.INTEGRATION,
        ),
        _initial_catalog(
            [_entry(LLMProvider.OPENAI, "actual-fixture-model")],
            "succeeded",
            LLMCatalogScope.INTEGRATION,
        ),
    ]
    identifier = LLM(_CONFIG).wait_for_initial_model_identifier(*_values())
    AgentService(_CONFIG).create(*_values(), model=identifier)
    assert identifier == "actual-fixture-model"
    assert api.llm_provider_integration_v1_list_integration_catalog_entries.call_count == 5
    call = agent_api.agent_v1_create_agent.call_args
    assert call is not None
    request = ProductAgentCreateRequest.model_validate(
        call.kwargs["agent_create_request"].to_dict()
    )
    assert request.selectable_model_options is not None
    assert (
        request.selectable_model_options[0].candidates[0].model_selection.model_identifier
        == "actual-fixture-model"
    )


@pytest.mark.parametrize("status", ["failed", "succeeded"])
def test_terminal_initial_catalog_without_ready_model_fails_immediately(
    monkeypatch: pytest.MonkeyPatch, status: str
) -> None:
    api = _polling_api(monkeypatch)
    entries = [_entry(LLMProvider.OPENAI, "old-model")] if status == "failed" else []
    api.llm_provider_integration_v1_list_integration_catalog_entries.return_value = (
        _initial_catalog(entries, status, LLMCatalogScope.INTEGRATION)
    )
    with pytest.raises(RuntimeError):
        LLM(_CONFIG).wait_for_initial_model_identifier(*_values())
    api.llm_provider_integration_v1_list_integration_catalog_entries.assert_called_once()


def test_initial_catalog_wait_has_bounded_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = _polling_api(monkeypatch)
    api.llm_provider_integration_v1_list_integration_catalog_entries.return_value = (
        _initial_catalog([], "running", LLMCatalogScope.INTEGRATION)
    )
    monkeypatch.setattr(llm_module.time, "monotonic", Mock(side_effect=[0.0, 0.0, 11.0, 11.0]))
    with pytest.raises(TimeoutError, match="did not become ready"):
        LLM(_CONFIG).wait_for_initial_model_identifier(*_values())
    api.llm_provider_integration_v1_list_integration_catalog_entries.assert_called_once()


def test_initial_catalog_wait_does_not_retry_unexpected_api_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = _polling_api(monkeypatch)
    api.llm_provider_integration_v1_list_integration_catalog_entries.side_effect = ApiException(
        status=500
    )
    with pytest.raises(ApiException):
        LLM(_CONFIG).wait_for_initial_model_identifier(*_values())
    api.llm_provider_integration_v1_list_integration_catalog_entries.assert_called_once()
