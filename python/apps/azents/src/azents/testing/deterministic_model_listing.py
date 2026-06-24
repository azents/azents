"""Testenv-only deterministic model listing fixture."""

from datetime import datetime, timezone
from typing import Literal

from azents.core.enums import LLMModelDeveloper, LLMProvider
from azents.core.llm_catalog import (
    ModelCapabilities,
    ModelContextWindow,
    ModelModalities,
    ModelModality,
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
    "deterministic-main-only",
    "deterministic-no-candidates",
    "deterministic-two-integrations",
    "deterministic-failure",
]
DETERMINISTIC_FIXTURE_VARIANTS: tuple[DeterministicFixtureVariant, ...] = (
    "deterministic-success",
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
        case "deterministic-success" | "deterministic-two-integrations":
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
    max_input_tokens = 64_000 if lightweight else 128_000
    return NormalizedModelCandidate(
        provider=provider,
        model_identifier=identifier,
        model_display_name=display_name,
        model_developer=LLMModelDeveloper.OPENAI,
        model_family=family,
        normalized_capabilities=ModelCapabilities(
            context_window=ModelContextWindow(
                max_input_tokens=max_input_tokens,
                max_output_tokens=16_000,
            ),
            modalities=ModelModalities(
                input=[ModelModality.TEXT, ModelModality.IMAGE, ModelModality.PDF],
                output=[ModelModality.TEXT],
            ),
            tool_calling=ModelToolCallingCapabilities(supported=True),
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
