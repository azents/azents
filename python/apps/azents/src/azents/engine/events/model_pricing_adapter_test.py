"""Both native adapters capture the actual physical candidate's saved prices."""

import datetime

import pytest

from azents.core.enums import LLMModelDeveloper, LLMProvider
from azents.core.inference_profile import AppliedModelRoute, SessionInferenceState
from azents.core.model_pricing import CapturedModelPricing, ModelPricingDefinition
from azents.engine.events import engine_adapter as adapter_module
from azents.engine.events import engine_adapter_test as fixtures
from azents.engine.run.contracts import RunRequest
from azents.testing.model_metadata import make_test_model_pricing
from azents.testing.model_selection import (
    make_test_model_candidate,
    make_test_model_selection,
    make_test_model_settings,
)

_owner_operations = fixtures._fake_execution_owner_operations


@pytest.mark.parametrize("provider", [LLMProvider.OPENAI, LLMProvider.ANTHROPIC])
@pytest.mark.parametrize("ordinal", [1, 2])
async def test_actual_primary_or_fallback_selection_supplies_adapter_pricing(
    monkeypatch: pytest.MonkeyPatch,
    provider: LLMProvider,
    ordinal: int,
) -> None:
    model = "gpt-4o" if provider is LLMProvider.OPENAI else "claude-sonnet-4-5"
    captured_fixture = make_test_model_pricing(
        provider=provider, model_identifier=model
    )
    definition = ModelPricingDefinition(
        rules=captured_fixture.rules,
        unavailable_reason=captured_fixture.unavailable_reason,
        source_key=captured_fixture.source_key,
        source_model_key=captured_fixture.source_model_key,
        collected_at=captured_fixture.collected_at,
    )
    selection = make_test_model_selection(
        provider=provider,
        model_identifier=model,
        integration_id=f"physical-candidate-{ordinal}",
        model_developer=(
            LLMModelDeveloper.OPENAI
            if provider is LLMProvider.OPENAI
            else LLMModelDeveloper.ANTHROPIC
        ),
    ).model_copy(update={"pricing": definition})
    state = SessionInferenceState(
        model_target_label="selected-label",
        model_selection=selection,
        model_settings=make_test_model_settings(),
        reasoning_effort=None,
        enabled_execution_options=[],
        effective_context_window_tokens=128_000,
        effective_auto_compaction_threshold_tokens=102_400,
        resolved_at=datetime.datetime(2026, 10, 3, tzinfo=datetime.UTC),
        applied_model_route=AppliedModelRoute(
            operation_id="operation",
            operation_kind="foreground",
            candidate_ordinal=ordinal,
            candidate_role="primary" if ordinal == 1 else "fallback",
            provider=provider,
            llm_provider_integration_id=selection.llm_provider_integration_id,
            model_identifier=model,
            model_display_name=model,
            effective_context_window_tokens=128_000,
            effective_auto_compaction_threshold_tokens=102_400,
        ),
    )
    seen: list[ModelPricingDefinition | None] = []
    original = adapter_module._capture_model_pricing

    def capture(
        *,
        definition: ModelPricingDefinition | None,
        provider: LLMProvider,
        model_identifier: str,
    ) -> CapturedModelPricing:
        seen.append(definition)
        return original(
            definition=definition,
            provider=provider,
            model_identifier=model_identifier,
        )

    monkeypatch.setattr(adapter_module, "_capture_model_pricing", capture)
    execution = fixtures._Execution()
    adapter = fixtures._agent_engine_adapter(
        execution_factory=fixtures._capture_execution_factory(execution)
    )
    request = RunRequest(
        top_k=None,
        model_assembly_metadata=None,
        compaction_candidate=make_test_model_candidate(),
        enabled_execution_options=[],
        session_id="session-1",
        user_messages=[],
        agent_prompt=None,
        toolkits=[],
        provider=provider,
        model=model,
        model_capabilities=selection.normalized_capabilities,
        credential_kwargs={"api_key": "synthetic-key"},
        workspace_id="workspace-1",
        agent_id="agent-1",
        tool_search_enabled=False,
        auto_compaction_threshold_tokens=None,
        inference_state=state,
        compaction_provider_integration_id=None,
    )
    _ = [emit async for emit in adapter.run(request, fixtures._run_context())]
    assert execution.prepared_model_call is not None
    assert len(seen) == 1
    assert seen[0] is selection.pricing
