"""Pure same-identity compilation and temporary active capability projections."""

import dataclasses
import json
from collections.abc import Mapping, Sequence
from typing import Any, Literal, Protocol

from pydantic import ValidationError

from azents.core.agent import AgentModelSelection, SelectableModelOption
from azents.core.enums import LLMModelDeveloper, LLMProvider
from azents.core.llm_catalog import ModelCapabilities
from azents.core.model_capability_evidence import ProviderCapabilityEvidence
from azents.core.model_capability_projection import (
    CAPABILITY_PROJECTION_REVISION,
    compile_stored_choice,
)
from azents.core.model_catalog_identity import source_model_matches
from azents.core.model_catalog_source import CatalogSourceModel
from azents.core.model_execution_options import ModelExecutionOptionId
from azents.core.model_provider_declarations import decode_stored_provider_evidence


@dataclasses.dataclass(frozen=True, order=True)
class ConfiguredModelIdentity:
    """An unchanged configured physical choice, never an inventory match."""

    integration_id: str
    provider: LLMProvider
    model_identifier: str

    @classmethod
    def from_selection(
        cls, selection: AgentModelSelection
    ) -> "ConfiguredModelIdentity":
        return cls(
            integration_id=selection.llm_provider_integration_id,
            provider=selection.provider,
            model_identifier=selection.model_identifier,
        )


@dataclasses.dataclass(frozen=True)
class CapturedStoredChoice:
    """Only local current declarations and exact source inputs enter compilation."""

    identity: ConfiguredModelIdentity
    source_metadata: Mapping[str, Any] | None
    source_models: tuple[CatalogSourceModel, ...]
    supported_execution_options: tuple[ModelExecutionOptionId, ...]
    model_developer: LLMModelDeveloper | None
    catalog_id: str


@dataclasses.dataclass(frozen=True)
class ActiveModelMetadataUnavailable:
    """Metadata failure diagnostics remain separate from final feature membership."""

    identity: ConfiguredModelIdentity
    reason: Literal[
        "integration_scope_unavailable",
        "exact_entry_unavailable",
        "provider_scope_mismatch",
        "stored_declarations_invalid",
        "required_evidence_unavailable",
    ]


class ActiveCapabilityCapture(Protocol):
    """The compiler needs no repository state or transaction handle."""

    @property
    def choices(
        self,
    ) -> tuple[CapturedStoredChoice | ActiveModelMetadataUnavailable, ...]: ...


@dataclasses.dataclass(frozen=True)
class CompiledActiveChoice:
    identity: ConfiguredModelIdentity
    capabilities: ModelCapabilities
    supported_execution_options: tuple[ModelExecutionOptionId, ...]
    catalog_id: str


@dataclasses.dataclass(frozen=True)
class CompiledActiveChoices:
    outcomes: tuple[CompiledActiveChoice | ActiveModelMetadataUnavailable, ...]

    def outcome_for(
        self, selection: AgentModelSelection
    ) -> CompiledActiveChoice | ActiveModelMetadataUnavailable:
        identity = ConfiguredModelIdentity.from_selection(selection)
        return next(
            (outcome for outcome in self.outcomes if outcome.identity == identity),
            ActiveModelMetadataUnavailable(identity, "required_evidence_unavailable"),
        )


class ActiveModelCapabilitiesUnavailable(ValueError):
    """The assigned choice lacks usable metadata; it is not a quota skip."""

    def __init__(self, diagnostic: ActiveModelMetadataUnavailable) -> None:
        self.diagnostic = diagnostic
        super().__init__(f"Active model metadata is unavailable: {diagnostic.reason}.")


def identities_for_options(
    options: Sequence[SelectableModelOption],
) -> tuple[ConfiguredModelIdentity, ...]:
    """Preserve configured order while avoiding repeated metadata reads."""
    return tuple(
        dict.fromkeys(
            ConfiguredModelIdentity.from_selection(candidate.model_selection)
            for option in options
            for candidate in option.candidates
        )
    )


def compile_capture(
    captured: ActiveCapabilityCapture, *, selections: Sequence[AgentModelSelection]
) -> CompiledActiveChoices:
    """Compile captured declarations without saved capability fallback or I/O."""
    selections_by_identity = {
        ConfiguredModelIdentity.from_selection(selection): selection
        for selection in selections
    }
    outcomes: list[CompiledActiveChoice | ActiveModelMetadataUnavailable] = []
    for choice in captured.choices:
        if isinstance(choice, ActiveModelMetadataUnavailable):
            outcomes.append(choice)
            continue
        saved = selections_by_identity.get(choice.identity)
        if saved is None:
            outcomes.append(
                ActiveModelMetadataUnavailable(
                    choice.identity, "required_evidence_unavailable"
                )
            )
            continue
        metadata = choice.source_metadata or {}
        try:
            supplied_evidence = metadata.get("capability_evidence")
            evidence = (
                ProviderCapabilityEvidence.model_validate_json(
                    json.dumps(supplied_evidence)
                )
                if supplied_evidence is not None
                else None
            )
            raw = metadata.get("provider_metadata")
            if raw is not None and not isinstance(raw, Mapping):
                raise ValueError("Stored provider declarations are not an object.")
            evidence = decode_stored_provider_evidence(
                provider=choice.identity.provider,
                provider_metadata=raw,
                capability_evidence=evidence,
            )
            models = [
                model
                for model in choice.source_models
                if source_model_matches(
                    provider=choice.identity.provider,
                    model_identifier=choice.identity.model_identifier,
                    source_model=model,
                )
            ]
            if len(models) > 1:
                raise ValueError("Stored model source identity is ambiguous.")
            compiled = compile_stored_choice(
                provider=choice.identity.provider,
                exact_model=choice.identity.model_identifier,
                evidence=evidence,
                source_model=models[0] if models else None,
                model_developer=choice.model_developer or saved.model_developer,
            )
        except ValidationError, ValueError, TypeError:
            outcomes.append(
                ActiveModelMetadataUnavailable(
                    choice.identity, "stored_declarations_invalid"
                )
            )
            continue
        outcomes.append(
            CompiledActiveChoice(
                identity=choice.identity,
                capabilities=compiled.capabilities,
                supported_execution_options=choice.supported_execution_options,
                catalog_id=choice.catalog_id,
            )
        )
    return CompiledActiveChoices(tuple(outcomes))


def require_selection(
    compiled: CompiledActiveChoices, selection: AgentModelSelection
) -> CompiledActiveChoice:
    """Require only the assigned choice; do not reject unused fallback metadata."""
    outcome = compiled.outcome_for(selection)
    if isinstance(outcome, ActiveModelMetadataUnavailable):
        raise ActiveModelCapabilitiesUnavailable(outcome)
    return outcome


def apply_to_selection(
    selection: AgentModelSelection, compiled: CompiledActiveChoices
) -> AgentModelSelection:
    """Project metadata in RAM; all user identity and unrelated fields are retained."""
    outcome = compiled.outcome_for(selection)
    diagnostics = dict(selection.source_metadata or {})
    if isinstance(outcome, ActiveModelMetadataUnavailable):
        diagnostics["active_capabilities"] = {
            "status": "unavailable",
            "reason": outcome.reason,
            "compiler_revision": CAPABILITY_PROJECTION_REVISION,
        }
        capabilities = ModelCapabilities()
        options: list[ModelExecutionOptionId] = []
    else:
        diagnostics["active_capabilities"] = {
            "status": "compiled",
            "catalog_id": outcome.catalog_id,
            "compiler_revision": CAPABILITY_PROJECTION_REVISION,
        }
        capabilities = outcome.capabilities.model_copy(deep=True)
        options = list(outcome.supported_execution_options)
    return selection.model_copy(
        update={
            "normalized_capabilities": capabilities,
            "supported_execution_options": options,
            "source_metadata": diagnostics,
        }
    )


def apply_to_options(
    options: Sequence[SelectableModelOption], compiled: CompiledActiveChoices
) -> list[SelectableModelOption]:
    """Keep labels, order and exact user settings, replacing metadata copies only."""
    return [
        option.model_copy(
            update={
                "candidates": [
                    candidate.model_copy(
                        update={
                            "model_selection": apply_to_selection(
                                candidate.model_selection, compiled
                            )
                        }
                    )
                    for candidate in option.candidates
                ]
            }
        )
        for option in options
    ]
