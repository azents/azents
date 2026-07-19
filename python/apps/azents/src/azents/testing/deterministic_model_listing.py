"""Testenv-only deterministic model listing fixture."""

from datetime import datetime, timezone
from typing import Literal

from azents.core.enums import LLMModelDeveloper, LLMProvider
from azents.core.llm_catalog import (
    ModelBuiltInToolCapabilities,
    ModelCapabilities,
    ModelContextWindow,
    ModelModalities,
    ModelModality,
    ModelReasoningCapabilities,
    ModelReasoningEffort,
    ModelToolCallingCapabilities,
)
from azents.services.model_listing.data import (
    ModelListingOutput,
    ModelListingSkipSummary,
    ModelListingSummary,
    NormalizedModelCandidate,
)

DETERMINISTIC_FIXTURE_NAME_PREFIX = "__testenv_model_listing:"
DeterministicFixtureVariant = Literal[
    "deterministic-success",
    "deterministic-model-settings",
    "deterministic-openrouter",
    "deterministic-main-only",
    "deterministic-no-candidates",
    "deterministic-two-integrations",
    "deterministic-failure",
]
DETERMINISTIC_FIXTURE_VARIANTS: tuple[DeterministicFixtureVariant, ...] = (
    "deterministic-success",
    "deterministic-model-settings",
    "deterministic-openrouter",
    "deterministic-main-only",
    "deterministic-no-candidates",
    "deterministic-two-integrations",
    "deterministic-failure",
)


def parse_deterministic_fixture_variant(
    integration_name: str,
) -> DeterministicFixtureVariant | None:
    """Extract testenv fixture variant from Integration name."""
    if not integration_name.startswith(DETERMINISTIC_FIXTURE_NAME_PREFIX):
        return None
    variant = integration_name.removeprefix(DETERMINISTIC_FIXTURE_NAME_PREFIX)
    if variant in DETERMINISTIC_FIXTURE_VARIANTS:
        return variant
    return None


def build_deterministic_listing(
    *,
    variant: DeterministicFixtureVariant,
    provider: LLMProvider,
    integration_id: str,
) -> ModelListingOutput:
    """Create deterministic listing result by variant."""
    fetched_at = datetime.now(timezone.utc)
    source = f"testenv_fixture:{variant}"
    match variant:
        case "deterministic-openrouter":
            if provider != LLMProvider.OPENROUTER:
                msg = "The OpenRouter fixture requires provider=openrouter."
                raise ValueError(msg)
            models = [
                _candidate(
                    provider=provider,
                    identifier="anthropic/claude-sonnet-4.6",
                    display_name="Claude Sonnet 4.6 via OpenRouter",
                    family="claude-sonnet-4.6",
                    integration_id=integration_id,
                    source=source,
                    fetched_at=fetched_at,
                    lightweight=False,
                ),
                _candidate(
                    provider=provider,
                    identifier="new-publisher/frontier-text",
                    display_name="Frontier Text via OpenRouter",
                    family="frontier-text",
                    integration_id=integration_id,
                    source=source,
                    fetched_at=fetched_at,
                    lightweight=True,
                ),
            ]
            skips = [
                ModelListingSkipSummary(
                    reason="invalid_model_identifier",
                    count=1,
                )
            ]
        case (
            "deterministic-success"
            | "deterministic-model-settings"
            | "deterministic-two-integrations"
        ):
            models = [
                _candidate(
                    provider=provider,
                    identifier="gpt-5.5",
                    display_name="GPT 5.5 Deterministic",
                    family="gpt-5.5",
                    integration_id=integration_id,
                    source=source,
                    fetched_at=fetched_at,
                    lightweight=False,
                ),
                _candidate(
                    provider=provider,
                    identifier="gpt-5.5-mini",
                    display_name="GPT 5.5 Mini Deterministic",
                    family="gpt-5.5-mini",
                    integration_id=integration_id,
                    source=source,
                    fetched_at=fetched_at,
                    lightweight=True,
                ),
            ]
            skips = [
                ModelListingSkipSummary(
                    reason="missing_context_window",
                    count=1,
                )
            ]
        case "deterministic-main-only":
            models = [
                _candidate(
                    provider=provider,
                    identifier="gpt-5.5",
                    display_name="GPT 5.5 Deterministic",
                    family="gpt-5.5",
                    integration_id=integration_id,
                    source=source,
                    fetched_at=fetched_at,
                    lightweight=False,
                )
            ]
            skips = [
                ModelListingSkipSummary(
                    reason="lightweight_candidate_missing",
                    count=1,
                )
            ]
        case "deterministic-no-candidates":
            models = []
            skips = [
                ModelListingSkipSummary(
                    reason="missing_runtime_contract",
                    count=2,
                )
            ]
        case "deterministic-failure":
            msg = "Deterministic failure fixture cannot build a successful listing."
            raise RuntimeError(msg)
    return ModelListingOutput(
        models=models,
        summary=ModelListingSummary(
            source=source,
            fetched_at=fetched_at,
            returned_count=len(models),
            skipped_count=sum(skip.count for skip in skips),
        ),
        skips=skips,
    )


def _candidate(
    *,
    provider: LLMProvider,
    identifier: str,
    display_name: str,
    family: str,
    integration_id: str,
    source: str,
    fetched_at: datetime,
    lightweight: bool,
) -> NormalizedModelCandidate:
    """Build fixture candidate."""
    if provider in {LLMProvider.XAI, LLMProvider.XAI_OAUTH}:
        identifier = "grok-4-fast" if lightweight else "grok-4"
        display_name = (
            "Grok 4 Fast Deterministic" if lightweight else "Grok 4 Deterministic"
        )
        family = "grok-4-fast" if lightweight else "grok-4"
        developer = LLMModelDeveloper.XAI
    elif provider == LLMProvider.OPENROUTER:
        developer = (
            LLMModelDeveloper.ANTHROPIC
            if identifier.startswith("anthropic/")
            else LLMModelDeveloper.OTHER
        )
    else:
        developer = LLMModelDeveloper.OPENAI
    max_input_tokens = 64_000 if lightweight else 128_000
    return NormalizedModelCandidate(
        provider=provider,
        model_identifier=identifier,
        model_display_name=display_name,
        model_developer=developer,
        model_family=family,
        normalized_capabilities=ModelCapabilities(
            context_window=ModelContextWindow(
                max_input_tokens=max_input_tokens,
                max_output_tokens=16_000,
            ),
            modalities=ModelModalities(
                input=(
                    [ModelModality.TEXT, ModelModality.IMAGE]
                    if provider == LLMProvider.OPENROUTER
                    else [ModelModality.TEXT, ModelModality.IMAGE, ModelModality.PDF]
                ),
                output=[ModelModality.TEXT],
            ),
            tool_calling=ModelToolCallingCapabilities(supported=True),
            reasoning=ModelReasoningCapabilities(
                supported=not lightweight,
                effort_levels=(
                    [
                        ModelReasoningEffort.NONE,
                        ModelReasoningEffort.MINIMAL,
                        ModelReasoningEffort.LOW,
                        ModelReasoningEffort.HIGH,
                        ModelReasoningEffort.XHIGH,
                        ModelReasoningEffort.MAX,
                    ]
                    if not lightweight
                    else []
                ),
                summaries=not lightweight,
            ),
            built_in_tools=ModelBuiltInToolCapabilities(
                supported=(
                    ["web_search"]
                    if provider == LLMProvider.OPENROUTER
                    else (
                        ["web_search", "image_generation"]
                        if source == "testenv_fixture:deterministic-model-settings"
                        and not lightweight
                        else []
                    )
                )
            ),
        ),
        model_snapshot={
            "source": source,
            "provider": provider.value,
            "model_identifier": identifier,
            "model_display_name": display_name,
            "fixture_variant": source.removeprefix("testenv_fixture:"),
        },
        source_metadata={
            "source": source,
            "integration_marker": integration_id,
            "fixture_lightweight": lightweight,
        },
        last_refreshed_at=fetched_at,
    )
