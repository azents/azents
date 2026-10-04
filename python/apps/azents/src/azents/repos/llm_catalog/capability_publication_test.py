"""New publication rejects historical support and obsolete compiler payloads."""

import dataclasses

import pytest

from azents.core.enums import (
    LLMCatalogEntryVisibility,
    LLMModelLifecycleStatus,
    LLMProvider,
)
from azents.core.llm_catalog import ModelCapabilities
from azents.core.model_capability_projection import CAPABILITY_PROJECTION_REVISION
from azents.core.model_pricing import normalize_model_pricing
from azents.repos.llm_catalog import LLMCatalogRepository
from azents.repos.llm_catalog.data import LLMCatalogEntryCreate


def _entry() -> LLMCatalogEntryCreate:
    return LLMCatalogEntryCreate(
        provider=LLMProvider.XAI_OAUTH,
        provider_model_identifier="exact-provider-model",
        display_name="Exact provider model",
        normalized_capabilities=ModelCapabilities().model_dump(mode="json"),
        supported_execution_options=[],
        lifecycle_status=LLMModelLifecycleStatus.ACTIVE,
        visibility_status=LLMCatalogEntryVisibility.SELECTABLE,
        provider_integration_id="integration",
        publisher="xai",
        family=None,
        source_metadata=None,
        projection_metadata={
            "capability_compiler_revision": CAPABILITY_PROJECTION_REVISION
        },
        hidden_reason=None,
        pricing=normalize_model_pricing(
            source_key=None, source_model=None, collected_at=None
        ),
    )


@pytest.mark.parametrize("raw_version", [None, 1, 2, "3"])
def test_historical_decode_cannot_authorize_new_publication(
    raw_version: object,
) -> None:
    entry = _entry()
    raw = dict(entry.normalized_capabilities)
    raw["capability_schema_version"] = raw_version
    with pytest.raises(ValueError, match="final v3"):
        LLMCatalogRepository._validate_conversation_capabilities(
            [dataclasses.replace(entry, normalized_capabilities=raw)]
        )


@pytest.mark.parametrize("revision", [None, "1", "3", "future"])
def test_new_publication_requires_actual_compiler_generation(
    revision: str | None,
) -> None:
    with pytest.raises(ValueError, match="current capability compiler"):
        LLMCatalogRepository._validate_conversation_capabilities(
            [
                dataclasses.replace(
                    _entry(),
                    projection_metadata={"capability_compiler_revision": revision},
                )
            ]
        )


def test_current_final_publication_is_not_rewritten_by_validation() -> None:
    entry = _entry()
    before = dataclasses.asdict(entry)
    LLMCatalogRepository._validate_conversation_capabilities([entry])
    assert dataclasses.asdict(entry) == before


def test_new_descriptor_cannot_keep_competing_semantic_authority() -> None:
    entry = _entry()
    raw = {**entry.normalized_capabilities, "semantic_contract": {}}
    with pytest.raises(ValueError, match="semantic descriptor"):
        LLMCatalogRepository._validate_conversation_capabilities(
            [dataclasses.replace(entry, normalized_capabilities=raw)]
        )
