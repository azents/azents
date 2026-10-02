"""Producer addressing is exact and does not transfer capabilities between hosts."""

import json

import pytest

from azents.core.enums import LLMProvider
from azents.core.model_catalog_identity import (
    CatalogIdentityError,
    lookup_catalog_model,
    provider_namespace_matches,
    source_model_matches,
    system_catalog_models,
)
from azents.core.model_catalog_source import CatalogSourcePayload, decode_catalog_source


def _payload(key: str, namespace: str) -> CatalogSourcePayload:
    return decode_catalog_source(
        json.dumps({key: {"litellm_provider": namespace, "mode": "chat"}}).encode()
    )


@pytest.mark.parametrize(
    ("provider", "namespace", "key", "identifier"),
    [
        (LLMProvider.OPENAI, "openai", "gpt-visible", "gpt-visible"),
        (LLMProvider.ANTHROPIC, "anthropic", "claude-visible", "claude-visible"),
        (
            LLMProvider.GOOGLE_GEMINI,
            "gemini",
            "gemini/gemini-visible",
            "gemini-visible",
        ),
        (
            LLMProvider.CHATGPT_OAUTH,
            "chatgpt",
            "chatgpt/account-visible",
            "account-visible",
        ),
        (LLMProvider.XAI, "xai", "xai/grok-visible", "grok-visible"),
        (
            LLMProvider.XAI_OAUTH,
            "xai_oauth",
            "xai_oauth/account-visible",
            "account-visible",
        ),
        (
            LLMProvider.KIMI_OAUTH,
            "kimi_oauth",
            "kimi_oauth/account-visible",
            "account-visible",
        ),
        (
            LLMProvider.OPENROUTER,
            "openrouter",
            "openrouter/vendor/model",
            "vendor/model",
        ),
        (
            LLMProvider.AWS_BEDROCK,
            "bedrock_converse",
            "us.anthropic.model-v1:0",
            "us.anthropic.model-v1:0",
        ),
        (
            LLMProvider.GOOGLE_VERTEX_AI,
            "vertex_ai",
            "vertex_ai/projects/p/locations/l/publishers/google/models/m",
            "projects/p/locations/l/publishers/google/models/m",
        ),
        (
            LLMProvider.GOOGLE_VERTEX_AI,
            "vertex_ai-anthropic_models",
            "vertex_ai/claude-visible",
            "claude-visible",
        ),
    ],
)
def test_exact_provider_addresses_preserve_full_execution_identifiers(
    provider: LLMProvider, namespace: str, key: str, identifier: str
) -> None:
    payload = _payload(key, namespace)
    model = lookup_catalog_model(
        payload, provider=provider, model_identifier=identifier
    )
    assert model is payload.models[0]
    assert source_model_matches(
        provider=provider, model_identifier=identifier, source_model=model
    )
    assert model.source_key == key


@pytest.mark.parametrize(
    ("provider", "namespace", "key", "identifier"),
    [
        (LLMProvider.CHATGPT_OAUTH, "openai", "gpt-visible", "gpt-visible"),
        (LLMProvider.XAI_OAUTH, "xai", "xai/grok-visible", "grok-visible"),
        (LLMProvider.KIMI_OAUTH, "moonshot", "moonshot/kimi-visible", "kimi-visible"),
        (LLMProvider.AWS_BEDROCK, "anthropic", "claude-visible", "claude-visible"),
        (LLMProvider.AWS_BEDROCK, "bedrock", "bedrock/visible", "visible"),
        (
            LLMProvider.AWS_BEDROCK,
            "bedrock_converse",
            "anthropic.model",
            "us.anthropic.model",
        ),
        (
            LLMProvider.AWS_BEDROCK,
            "bedrock_converse",
            "anthropic.model",
            "arn:aws:bedrock:us-east-1::foundation-model/anthropic.model",
        ),
        (
            LLMProvider.GOOGLE_VERTEX_AI,
            "gemini",
            "gemini/gemini-visible",
            "gemini-visible",
        ),
        (
            LLMProvider.GOOGLE_VERTEX_AI,
            "vertex_ai",
            "vertex_ai/m",
            "projects/p/locations/l/publishers/google/models/m",
        ),
        (LLMProvider.GOOGLE_GEMINI, "gemini", "gemini-visible", "gemini-visible"),
        (LLMProvider.OPENAI, "openai", "openai/gpt-visible", "gpt-visible"),
        (
            LLMProvider.ANTHROPIC,
            "anthropic",
            "anthropic/claude-visible",
            "claude-visible",
        ),
        (LLMProvider.OPENROUTER, "openrouter", "openrouter/vendor/model", "model"),
    ],
)
def test_unknown_or_cross_host_addresses_do_not_gain_metadata(
    provider: LLMProvider, namespace: str, key: str, identifier: str
) -> None:
    assert (
        lookup_catalog_model(
            _payload(key, namespace), provider=provider, model_identifier=identifier
        )
        is None
    )


def test_system_inventory_uses_only_adopted_gemini_qualified_addresses() -> None:
    payload = decode_catalog_source(
        json.dumps(
            {
                "gemini-visible": {"litellm_provider": "gemini", "mode": "chat"},
                "gemini/gemini-visible": {"litellm_provider": "gemini", "mode": "chat"},
                "vertex_ai/gemini-visible": {
                    "litellm_provider": "vertex_ai",
                    "mode": "chat",
                },
            }
        ).encode()
    )
    models = system_catalog_models(payload, provider=LLMProvider.GOOGLE_GEMINI)
    assert len(payload.models) == 3
    assert len(models) == 1
    assert models[0].execution_model_identifier == "gemini-visible"
    assert models[0].source_model.source_key == "gemini/gemini-visible"


def test_conflicting_adopted_scope_is_rejected_without_an_arbitrary_winner() -> None:
    first = _payload("vertex_ai/opaque", "vertex_ai").models[0]
    second = _payload("vertex_ai/opaque", "vertex_ai-language-models").models[0]
    payload = CatalogSourcePayload(
        schema_version="1", interpreter_version="1", models=(first, second)
    )
    with pytest.raises(CatalogIdentityError, match="Conflicting"):
        lookup_catalog_model(
            payload, provider=LLMProvider.GOOGLE_VERTEX_AI, model_identifier="opaque"
        )


def test_namespaces_do_not_equate_oauth_or_other_bedrock_apis() -> None:
    assert provider_namespace_matches(LLMProvider.XAI, "xai")
    assert not provider_namespace_matches(LLMProvider.XAI_OAUTH, "xai")
    assert not provider_namespace_matches(LLMProvider.KIMI_OAUTH, "moonshot")
    assert not provider_namespace_matches(LLMProvider.AWS_BEDROCK, "bedrock")
    assert provider_namespace_matches(LLMProvider.AWS_BEDROCK, "bedrock_converse")
