"""Testenv-only deterministic model listing fixture."""

from datetime import datetime, timezone
from typing import Literal, NamedTuple, assert_never

from azents.core.enums import LLMModelDeveloper, LLMProvider
from azents.core.llm_catalog import (
    ModelBuiltInToolCapabilities,
    ModelCapabilities,
    ModelCompatibilityCapabilities,
    ModelContextWindow,
    ModelModalities,
    ModelModality,
    ModelReasoningCapabilities,
    ModelReasoningEffort,
    ModelToolCallingCapabilities,
)
from azents.core.model_execution_options import ModelExecutionOptionId
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
    "deterministic-context-ranges",
    "deterministic-openrouter",
    "deterministic-main-only",
    "deterministic-no-candidates",
    "deterministic-two-integrations",
    "deterministic-failure",
    "deterministic-brave-text-only",
    "deterministic-provider-core",
]
DETERMINISTIC_FIXTURE_VARIANTS: tuple[DeterministicFixtureVariant, ...] = (
    "deterministic-success",
    "deterministic-model-settings",
    "deterministic-context-ranges",
    "deterministic-openrouter",
    "deterministic-main-only",
    "deterministic-no-candidates",
    "deterministic-two-integrations",
    "deterministic-failure",
    "deterministic-brave-text-only",
    "deterministic-provider-core",
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
        case "deterministic-provider-core":
            models = _provider_core_candidates(
                provider=provider,
                integration_id=integration_id,
                source=source,
                fetched_at=fetched_at,
            )
            skips = []
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
            | "deterministic-context-ranges"
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
            if (
                variant == "deterministic-model-settings"
                and provider == LLMProvider.OPENAI
            ):
                models.extend(
                    [
                        _candidate(
                            provider=provider,
                            identifier=identifier,
                            display_name=display_name,
                            family=identifier,
                            integration_id=integration_id,
                            source=source,
                            fetched_at=fetched_at,
                            lightweight=False,
                        )
                        for identifier, display_name in (
                            ("gpt-6-astra", "GPT 6 Astra Deterministic"),
                            ("gpt-5.6-sol", "GPT 5.6 Sol Deterministic"),
                        )
                    ]
                )
        case "deterministic-brave-text-only":
            models = [
                _candidate(
                    provider=provider,
                    identifier="gpt-5.5",
                    display_name="GPT 5.5 Text-Only Fixture",
                    family="gpt-5.5",
                    integration_id=integration_id,
                    source=source,
                    fetched_at=fetched_at,
                    lightweight=False,
                )
            ]
            skips = []
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


class _CoreModel(NamedTuple):
    """Nominal provider-native identity, without cross-provider model aliases."""

    identifier: str
    developer: LLMModelDeveloper
    family: str


def _provider_core_candidates(
    *,
    provider: LLMProvider,
    integration_id: str,
    source: str,
    fetched_at: datetime,
) -> list[NormalizedModelCandidate]:
    """Expose conservative native families for the small SDK smoke matrix."""
    match provider:
        case LLMProvider.OPENAI | LLMProvider.CHATGPT_OAUTH:
            identities = [_CoreModel("gpt-5.5", LLMModelDeveloper.OPENAI, "gpt-5.5")]
        case LLMProvider.XAI | LLMProvider.XAI_OAUTH:
            identities = [_CoreModel("grok-4", LLMModelDeveloper.XAI, "grok-4")]
        case LLMProvider.ANTHROPIC:
            identities = [
                _CoreModel(
                    "claude-sonnet-4-6", LLMModelDeveloper.ANTHROPIC, "claude-sonnet"
                )
            ]
        case LLMProvider.GOOGLE_GEMINI:
            identities = [
                _CoreModel("gemini-2.5-pro", LLMModelDeveloper.GOOGLE, "gemini"),
                _CoreModel(
                    "gemini-3.1-flash-image-preview", LLMModelDeveloper.GOOGLE, "gemini"
                ),
            ]
        case LLMProvider.GOOGLE_VERTEX_AI:
            identities = [
                _CoreModel("gemini-2.5-pro", LLMModelDeveloper.GOOGLE, "gemini"),
                _CoreModel(
                    "publishers/anthropic/models/claude-sonnet-4-6",
                    LLMModelDeveloper.ANTHROPIC,
                    "claude-sonnet",
                ),
            ]
        case LLMProvider.AWS_BEDROCK:
            identities = [
                _CoreModel(
                    "anthropic.claude-3-haiku-20240307-v1:0",
                    LLMModelDeveloper.ANTHROPIC,
                    "claude-haiku",
                ),
                _CoreModel("amazon.nova-lite-v1:0", LLMModelDeveloper.OTHER, "nova"),
                _CoreModel(
                    "mistral.mistral-large-2407-v1:0",
                    LLMModelDeveloper.MISTRAL,
                    "mistral-large",
                ),
            ]
        case LLMProvider.OPENROUTER:
            identities = [
                _CoreModel(
                    "anthropic/claude-sonnet-4.6",
                    LLMModelDeveloper.ANTHROPIC,
                    "claude-sonnet",
                )
            ]
        case LLMProvider.KIMI_OAUTH:
            identities = [_CoreModel("kimi-k2.5", LLMModelDeveloper.MOONSHOT, "kimi")]
        case _:
            assert_never(provider)
    return [
        NormalizedModelCandidate(
            provider=provider,
            model_identifier=identity.identifier,
            model_display_name=f"Core {identity.identifier}",
            model_developer=identity.developer,
            model_family=identity.family,
            normalized_capabilities=ModelCapabilities(
                context_window=ModelContextWindow(
                    max_input_tokens=64_000,
                    max_output_tokens=4_096,
                ),
                modalities=ModelModalities(
                    input=[ModelModality.TEXT],
                    output=(
                        [ModelModality.TEXT, ModelModality.IMAGE]
                        if identity.identifier == "gemini-3.1-flash-image-preview"
                        else [ModelModality.TEXT]
                    ),
                ),
                tool_calling=ModelToolCallingCapabilities(
                    supported=identity.identifier != "gemini-3.1-flash-image-preview"
                ),
                reasoning=ModelReasoningCapabilities(supported=False),
                built_in_tools=ModelBuiltInToolCapabilities(supported=[]),
                compatibility=ModelCompatibilityCapabilities(
                    provider_family=provider.value,
                ),
            ),
            supported_execution_options=[],
            model_snapshot={
                "source": source,
                "provider": provider.value,
                "model_identifier": identity.identifier,
                "fixture_variant": "deterministic-provider-core",
            },
            source_metadata={
                "source": source,
                "integration_marker": integration_id,
                "fixture_family": identity.family,
            },
            last_refreshed_at=fetched_at,
        )
        for identity in identities
    ]


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
    if source == "testenv_fixture:deterministic-context-ranges":
        default_input_tokens = None if lightweight else 96_000
        max_input_tokens = 512_000 if lightweight else 256_000
    else:
        default_input_tokens = None
        max_input_tokens = 64_000 if lightweight else 128_000
    input_modalities = (
        [ModelModality.TEXT, ModelModality.IMAGE]
        if provider == LLMProvider.OPENROUTER
        else [ModelModality.TEXT, ModelModality.IMAGE, ModelModality.PDF]
    )
    if source == "testenv_fixture:deterministic-brave-text-only":
        input_modalities = [ModelModality.TEXT]
    return NormalizedModelCandidate(
        provider=provider,
        model_identifier=identifier,
        model_display_name=display_name,
        model_developer=developer,
        model_family=family,
        normalized_capabilities=ModelCapabilities(
            context_window=ModelContextWindow(
                default_input_tokens=default_input_tokens,
                max_input_tokens=max_input_tokens,
                max_output_tokens=16_000,
            ),
            modalities=ModelModalities(
                input=input_modalities,
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
        supported_execution_options=(
            (
                [ModelExecutionOptionId.FAST, ModelExecutionOptionId.ULTRAFAST]
                if identifier in {"gpt-6-astra", "gpt-5.6-sol"}
                else [ModelExecutionOptionId.FAST]
            )
            if provider == LLMProvider.OPENAI
            and identifier in {"gpt-5.5", "gpt-6-astra", "gpt-5.6-sol"}
            and not lightweight
            else []
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
