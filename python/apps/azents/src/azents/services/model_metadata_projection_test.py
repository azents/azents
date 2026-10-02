"""Replacement model metadata shadow projection tests."""

import datetime
import importlib.metadata

import pytest

from azents.core.enums import (
    LLMCatalogEntryVisibility,
    LLMModelDeveloper,
    LLMProvider,
)
from azents.core.llm_catalog import ModelCapabilities
from azents.core.model_metadata_source import (
    ModelMetadataSourcePayload,
    SourceEqualsClause,
    SourceModelRecord,
    SourceProviderRecord,
)
from azents.repos.model_metadata_source_data import ModelMetadataSourceSnapshot
from azents.services.model_listing.data import NormalizedModelCandidate
from azents.services.model_listing.providers import (
    _candidate_from_xai_api_key_model,
    _candidate_from_xai_oauth_model,
    _XaiOAuthModelPayload,
)
from azents.services.model_metadata_projection import (
    ModelMetadataProjectionError,
    integration_projection_fingerprint,
    project_integration_replacement_entries,
    project_system_entries,
    projection_fingerprint,
)


def _provider(
    provider_id: str, models: list[SourceModelRecord]
) -> SourceProviderRecord:
    return SourceProviderRecord(
        id=provider_id,
        name=provider_id,
        api_pattern=f"https://{provider_id}.example/.*",
        model_match=None,
        provider_match=None,
        fallback_model_providers=None,
        models=models,
    )


def _model(
    identifier: str,
    *,
    context_window: int = 128_000,
    deprecated: bool = False,
) -> SourceModelRecord:
    return SourceModelRecord(
        id=identifier,
        name=identifier.upper(),
        match=SourceEqualsClause(value=identifier),
        context_window=context_window,
        deprecated=deprecated,
        prices=[],
    )


def _payload() -> ModelMetadataSourcePayload:
    return ModelMetadataSourcePayload(
        providers=[
            _provider(
                "openai",
                [
                    _model("gpt-5.4"),
                    _model("text-embedding-4"),
                ],
            ),
            _provider("anthropic", [_model("claude-sonnet-4-6")]),
            _provider(
                "google",
                [
                    _model("gemini-3.1-pro"),
                    _model("claude-sonnet-4-6"),
                ],
            ),
        ]
    )


def _source(payload: ModelMetadataSourcePayload) -> ModelMetadataSourceSnapshot:
    return ModelMetadataSourceSnapshot(
        id="s" * 32,
        source_key="genai_prices",
        source_kind="genai_prices",
        source_schema_version="1",
        source_url="https://metadata.example/data.json",
        source_hash=payload.content_hash(),
        producer_name="genai-prices",
        producer_version="0.1.9",
        provider_count=payload.provider_count,
        model_count=payload.model_count,
        payload=payload,
        created_at=datetime.datetime(2026, 10, 1, tzinfo=datetime.UTC),
    )


def test_projection_uses_runtime_profile_and_source_neutral_metadata() -> None:
    """Execution capabilities come from the shared resolver, not source flags."""
    entries = project_system_entries(
        provider=LLMProvider.OPENAI,
        source=_source(_payload()),
    )
    by_id = {entry.provider_model_identifier: entry for entry in entries}

    gpt = by_id["gpt-5.4"]
    assert gpt.visibility_status is LLMCatalogEntryVisibility.SELECTABLE
    assert gpt.normalized_capabilities["tool_calling"]["supported"] is True
    assert gpt.normalized_capabilities["reasoning"]["supported"] is True
    assert gpt.normalized_capabilities["context_window"]["max_input_tokens"] == (
        128_000
    )
    assert gpt.source_metadata == {
        "source_kind": "genai_prices",
        "source_provider_id": "openai",
        "source_model_id": "gpt-5.4",
        "source_hash": _source(_payload()).source_hash,
        "context_window": 128_000,
        "deprecated": False,
    }
    assert gpt.projection_metadata is not None

    embedding = by_id["text-embedding-4"]
    assert embedding.visibility_status is LLMCatalogEntryVisibility.HIDDEN
    assert embedding.hidden_reason == "unsupported_model_kind"


@pytest.mark.parametrize("provider", [LLMProvider.XAI, LLMProvider.XAI_OAUTH])
@pytest.mark.parametrize("source_kind", ["missing", "unmatched", "unpriced"])
@pytest.mark.parametrize("backend_search", [None, True, False])
def test_xai_projection_preserves_effective_client_and_native_tools(
    provider: LLMProvider, source_kind: str, backend_search: bool | None
) -> None:
    """Sparse listings and price misses cannot deny executable Grok tools."""
    fetched_at = datetime.datetime(2026, 10, 2, tzinfo=datetime.UTC)
    candidate = (
        _candidate_from_xai_api_key_model(
            model_id="grok-4", created=0, fetched_at=fetched_at
        )
        if provider is LLMProvider.XAI
        else _candidate_from_xai_oauth_model(
            _XaiOAuthModelPayload(id="grok-4", supports_backend_search=backend_search),
            fetched_at=fetched_at,
        )
    )
    source = (
        None
        if source_kind == "missing"
        else _source(
            ModelMetadataSourcePayload(
                providers=[
                    _provider(
                        "x-ai",
                        [_model("grok-4" if source_kind == "unpriced" else "other")],
                    )
                ]
            )
        )
    )
    [entry] = project_integration_replacement_entries(
        integration_id="integration",
        provider=provider,
        candidates=[candidate],
        source=source,
        provider_listing_source="xai:models",
    )
    capabilities = ModelCapabilities.model_validate(entry.normalized_capabilities)

    assert entry.visibility_status is LLMCatalogEntryVisibility.SELECTABLE
    assert capabilities.tool_calling.supported is True
    assert "image_generation" in capabilities.built_in_tools.supported
    assert ("web_search" in capabilities.built_in_tools.supported) is (
        provider is LLMProvider.XAI or backend_search is not False
    )

    [restored_entry] = project_integration_replacement_entries(
        integration_id="integration",
        provider=provider,
        candidates=[
            NormalizedModelCandidate.model_validate_json(candidate.model_dump_json())
        ],
        source=source,
        provider_listing_source="xai:models",
    )
    assert restored_entry.normalized_capabilities == entry.normalized_capabilities


@pytest.mark.parametrize("reasoning", [None, True, False])
@pytest.mark.parametrize("efforts", [None, [], [{"value": "low"}]])
def test_xai_projection_respects_explicit_reasoning_evidence(
    reasoning: bool | None, efforts: list[dict[str, str]] | None
) -> None:
    """Omitted reasoning metadata is not a denial; explicit empty levels are."""
    candidate = _candidate_from_xai_oauth_model(
        _XaiOAuthModelPayload.model_validate(
            {
                "id": "grok-4",
                "supports_reasoning_effort": reasoning,
                "reasoning_efforts": efforts,
            }
        ),
        fetched_at=datetime.datetime(2026, 10, 2, tzinfo=datetime.UTC),
    )
    [entry] = project_integration_replacement_entries(
        integration_id="integration",
        provider=LLMProvider.XAI_OAUTH,
        candidates=[candidate],
        source=None,
        provider_listing_source="xai:models",
    )
    capabilities = ModelCapabilities.model_validate(entry.normalized_capabilities)

    assert capabilities.reasoning.supported is (reasoning is not False)
    assert [effort.value for effort in capabilities.reasoning.effort_levels] == (
        []
        if reasoning is False or efforts == []
        else ["low"]
        if efforts
        else ["low", "medium", "high"]
    )


def test_google_system_projection_excludes_vertex_anthropic_family() -> None:
    """The direct Gemini catalog does not expose Vertex-hosted Claude records."""
    entries = project_system_entries(
        provider=LLMProvider.GOOGLE_GEMINI,
        source=_source(_payload()),
    )
    by_id = {entry.provider_model_identifier: entry for entry in entries}

    assert by_id["gemini-3.1-pro"].visibility_status is (
        LLMCatalogEntryVisibility.SELECTABLE
    )
    assert by_id["claude-sonnet-4-6"].hidden_reason == ("unsupported_model_family")


def test_integration_projection_keeps_unmatched_provider_model_selectable() -> None:
    """Provider-visible integration models do not require a source match."""
    candidate = NormalizedModelCandidate(
        provider=LLMProvider.AWS_BEDROCK,
        model_identifier="provider-visible-unmatched",
        model_display_name="Provider Visible",
        model_developer=LLMModelDeveloper.ANTHROPIC,
        model_family="claude",
        normalized_capabilities=ModelCapabilities(),
        supported_execution_options=[],
        model_snapshot={},
        source_metadata={"provider_listing": True},
        last_refreshed_at=datetime.datetime(2026, 10, 1, tzinfo=datetime.UTC),
    )

    [entry] = project_integration_replacement_entries(
        integration_id="integration-id",
        provider=LLMProvider.AWS_BEDROCK,
        candidates=[candidate],
        source=None,
        provider_listing_source="bedrock:list_foundation_models",
    )

    assert entry.visibility_status is LLMCatalogEntryVisibility.SELECTABLE
    assert entry.hidden_reason is None
    assert entry.projection_metadata is not None
    assert entry.projection_metadata["matched"] is False
    assert entry.source_metadata is not None
    assert entry.source_metadata["source_snapshot_id"] is None


def test_integration_fingerprint_covers_display_and_provider_metadata() -> None:
    """Persisted entry changes cannot reuse a stale candidate snapshot."""
    candidate = NormalizedModelCandidate(
        provider=LLMProvider.AWS_BEDROCK,
        model_identifier="provider-model",
        model_display_name="Original display",
        model_developer=LLMModelDeveloper.ANTHROPIC,
        model_family="claude",
        normalized_capabilities=ModelCapabilities(),
        supported_execution_options=[],
        model_snapshot={},
        source_metadata={"provider_revision": 1},
        last_refreshed_at=datetime.datetime(2026, 10, 1, tzinfo=datetime.UTC),
    )
    original_entries = project_integration_replacement_entries(
        integration_id="integration-id",
        provider=LLMProvider.AWS_BEDROCK,
        candidates=[candidate],
        source=None,
        provider_listing_source="bedrock:list_foundation_models",
    )
    changed_entries = project_integration_replacement_entries(
        integration_id="integration-id",
        provider=LLMProvider.AWS_BEDROCK,
        candidates=[
            candidate.model_copy(
                update={
                    "model_display_name": "Updated display",
                    "source_metadata": {"provider_revision": 2},
                }
            )
        ],
        source=None,
        provider_listing_source="bedrock:list_foundation_models",
    )

    original = integration_projection_fingerprint(
        provider=LLMProvider.AWS_BEDROCK,
        source=None,
        entries=original_entries,
        catalog_configuration_version=1,
    )
    changed = integration_projection_fingerprint(
        provider=LLMProvider.AWS_BEDROCK,
        source=None,
        entries=changed_entries,
        catalog_configuration_version=1,
    )

    assert original != changed


def test_integration_fingerprint_is_independent_of_provider_response_order() -> None:
    """Equivalent provider-visible entry sets have one canonical fingerprint."""
    candidates = [
        NormalizedModelCandidate(
            provider=LLMProvider.AWS_BEDROCK,
            model_identifier=model_identifier,
            model_display_name=model_identifier,
            model_developer=LLMModelDeveloper.ANTHROPIC,
            model_family="claude",
            normalized_capabilities=ModelCapabilities(),
            supported_execution_options=[],
            model_snapshot={},
            source_metadata={"provider_revision": 1},
            last_refreshed_at=datetime.datetime(2026, 10, 1, tzinfo=datetime.UTC),
        )
        for model_identifier in ("model-b", "model-a")
    ]
    entries = project_integration_replacement_entries(
        integration_id="integration-id",
        provider=LLMProvider.AWS_BEDROCK,
        candidates=candidates,
        source=None,
        provider_listing_source="bedrock:list_foundation_models",
    )

    forward = integration_projection_fingerprint(
        provider=LLMProvider.AWS_BEDROCK,
        source=None,
        entries=entries,
        catalog_configuration_version=1,
    )
    reversed_order = integration_projection_fingerprint(
        provider=LLMProvider.AWS_BEDROCK,
        source=None,
        entries=list(reversed(entries)),
        catalog_configuration_version=1,
    )

    assert forward == reversed_order


def test_projection_fingerprint_uses_installed_dependency_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A dependency upgrade reprojections unchanged normalized source content."""
    source = _source(_payload())
    real_version = importlib.metadata.version
    genai_prices_version = "0.1.9"

    def dependency_version(package: str) -> str:
        if package == "genai-prices":
            return genai_prices_version
        return real_version(package)

    monkeypatch.setattr(
        "azents.services.model_metadata_projection.importlib.metadata.version",
        dependency_version,
    )
    first = projection_fingerprint(provider=LLMProvider.OPENAI, source=source)
    genai_prices_version = "0.2.0"
    second = projection_fingerprint(provider=LLMProvider.OPENAI, source=source)

    assert source.producer_version == "0.1.9"
    assert first != second


def test_projection_fingerprint_covers_runtime_and_policy_revision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A capability repair invalidates unchanged-source candidate reuse."""
    source = _source(_payload())
    original = projection_fingerprint(provider=LLMProvider.OPENAI, source=source)
    monkeypatch.setattr(
        "azents.services.model_metadata_projection.RUNTIME_MODEL_PROFILE_RESOLVER_REVISION",
        "next-runtime",
    )
    runtime_changed = projection_fingerprint(provider=LLMProvider.OPENAI, source=source)
    monkeypatch.setattr(
        "azents.services.model_metadata_projection.MODEL_METADATA_PROJECTION_POLICY_REVISION",
        "next-policy",
    )
    policy_changed = projection_fingerprint(provider=LLMProvider.OPENAI, source=source)

    assert len({original, runtime_changed, policy_changed}) == 3


@pytest.mark.parametrize("provider_id", [None, "empty"])
def test_projection_rejects_missing_or_empty_required_provider(
    provider_id: str | None,
) -> None:
    """A required provider must produce a non-empty complete candidate."""
    payload = _payload()
    source_providers = payload.providers
    providers = [
        provider for provider in source_providers if provider.id != "anthropic"
    ]
    if provider_id == "empty":
        providers.append(_provider("anthropic", []))
    incomplete = payload.model_copy(update={"providers": providers})

    with pytest.raises(ModelMetadataProjectionError, match="anthropic"):
        project_system_entries(
            provider=LLMProvider.ANTHROPIC,
            source=_source(incomplete),
        )
