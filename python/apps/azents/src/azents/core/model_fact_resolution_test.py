"""All raw evidence fields survive scoped fact assembly before route admission."""

import json

import pytest

from azents.core.enums import LLMProvider
from azents.core.llm_catalog import ModelModality, ModelReasoningEffort
from azents.core.model_capability_evidence import ProviderCapabilityEvidence
from azents.core.model_catalog_source import CatalogSourceModel, decode_catalog_source
from azents.core.model_fact_resolution import resolve_model_facts

_SAMPLES: dict[str, object] = {
    "default_input_tokens": 272000,
    "max_input_tokens": 872000,
    "max_output_tokens": 128000,
    "input_modalities": ("text", "image"),
    "output_modalities": ("text",),
    "reasoning_efforts": (ModelReasoningEffort.LOW, ModelReasoningEffort.HIGH),
    "default_reasoning_effort": ModelReasoningEffort.HIGH,
}


@pytest.mark.parametrize("field", list(ProviderCapabilityEvidence.model_fields))
@pytest.mark.parametrize("presence", ["absent", "null", "value"])
def test_every_provider_field_retains_original_presence_and_value(
    field: str, presence: str
) -> None:
    value = _SAMPLES.get(field, True) if presence == "value" else None
    evidence = ProviderCapabilityEvidence.model_validate(
        {field: {"state": presence, "value": value}}
    )
    facts = resolve_model_facts(
        provider=LLMProvider.OPENROUTER,
        exact_model="literal-model",
        source_model=None,
        evidence=evidence,
    )
    assert facts.declarations.model_dump()[field] == evidence.model_dump()[field]
    assert facts.provider_declarations == evidence
    provenance = next(item for item in facts.provenance if item.field == field)
    assert provenance.presence == presence
    assert provenance.owner == ("absent" if presence == "absent" else "provider")
    assert len(facts.provenance) == len(ProviderCapabilityEvidence.model_fields)


def _source(fields: dict[str, object]) -> CatalogSourceModel:
    return decode_catalog_source(
        json.dumps(
            {"native-model": {"litellm_provider": "openai", "mode": "chat", **fields}}
        ).encode()
    ).models[0]


@pytest.mark.parametrize("value", [False, None, True])
def test_explicit_provider_boolean_does_not_become_a_source_default(
    value: bool | None,
) -> None:
    evidence = ProviderCapabilityEvidence.model_validate(
        {
            "function_calling": {
                "state": "null" if value is None else "value",
                "value": value,
            }
        }
    )
    facts = resolve_model_facts(
        provider=LLMProvider.OPENAI,
        exact_model="native-model",
        source_model=_source({"supports_function_calling": True}),
        evidence=evidence,
    )
    assert facts.declarations.function_calling.value == value
    assert facts.declarations.function_calling.state == (
        "null" if value is None else "value"
    )


def test_positive_audio_video_facts_survive_before_transport_constraints() -> None:
    facts = resolve_model_facts(
        provider=LLMProvider.OPENAI,
        exact_model="native-model",
        source_model=_source(
            {
                "supports_audio_input": True,
                "supports_video_input": True,
                "supports_audio_output": True,
            }
        ),
        evidence=None,
    )
    assert (
        next(
            item.declaration.value
            for item in facts.input_modalities
            if item.modality is ModelModality.AUDIO
        )
        is True
    )
    assert (
        next(
            item.declaration.value
            for item in facts.input_modalities
            if item.modality is ModelModality.VIDEO
        )
        is True
    )
    assert (
        next(
            item.declaration.value
            for item in facts.output_modalities
            if item.modality is ModelModality.AUDIO
        )
        is True
    )


def test_literal_host_mismatch_never_borrows_model_or_limit_facts() -> None:
    with pytest.raises(ValueError, match="exact hosting identity"):
        resolve_model_facts(
            provider=LLMProvider.CHATGPT_OAUTH,
            exact_model="native-model",
            source_model=_source(
                {"supports_function_calling": True, "max_input_tokens": 922000}
            ),
            evidence=None,
        )


def test_positive_efforts_preserve_explicit_reasoning_denial_diagnostic() -> None:
    facts = resolve_model_facts(
        provider=LLMProvider.OPENAI,
        exact_model="native-model",
        source_model=_source({"supports_reasoning": False}),
        evidence=ProviderCapabilityEvidence.model_validate(
            {
                "reasoning_efforts": {
                    "state": "value",
                    "value": (ModelReasoningEffort.HIGH,),
                }
            }
        ),
    )
    assert facts.declarations.reasoning.value is False
    assert facts.declarations.reasoning_efforts.value == (ModelReasoningEffort.HIGH,)
    assert facts.diagnostics == (
        "reasoning_efforts_conflict_with_explicit_reasoning_denial",
    )
