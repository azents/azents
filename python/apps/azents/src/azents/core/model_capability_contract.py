"""Self-contained support semantics for versioned saved model capabilities."""

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, model_validator

type ReasoningEffortValue = Literal[
    "none", "minimal", "low", "medium", "high", "xhigh", "max"
]
type ModalityValue = Literal["text", "image", "pdf", "audio", "video"]
type BuiltinToolValue = Literal["web_search", "image_generation"]
type EvidenceOrigin = Literal["explicit", "contract_derived"]
type SupportState = Literal["supported", "unsupported", "unknown", "conditional"]
type EffortCompleteness = Literal["complete", "partial", "unknown"]


class SupportPredicate(BaseModel):
    """A conjunction of saved effort and function-tool request conditions.

    Null means that dimension does not constrain the request. An omitted request
    effort cannot satisfy an effort predicate without a known saved default.
    Evaluation belongs to the consumers of this contract, not to source lookup.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    reasoning_efforts: tuple[ReasoningEffortValue, ...] | None
    function_tools: bool | None

    @model_validator(mode="after")
    def validate_predicate(self) -> Self:
        """Reject empty predicates and impossible or duplicate effort sets."""
        if self.reasoning_efforts is None and self.function_tools is None:
            raise ValueError("A conditional capability requires a known predicate.")
        if self.reasoning_efforts is not None:
            if not self.reasoning_efforts:
                raise ValueError("An effort predicate must contain an accepted effort.")
            if len(self.reasoning_efforts) != len(set(self.reasoning_efforts)):
                raise ValueError(
                    "An effort predicate cannot contain duplicate efforts."
                )
        return self


class CapabilitySupport(BaseModel):
    """One justified support state, independent of source or runtime libraries."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    state: SupportState
    origin: EvidenceOrigin | None
    predicate: SupportPredicate | None

    @model_validator(mode="after")
    def validate_support(self) -> Self:
        """Keep unknown evidence and conditional support unambiguous."""
        if (self.state == "unknown") != (self.origin is None):
            raise ValueError("Only unknown support may omit its evidence origin.")
        if (self.state == "conditional") != (self.predicate is not None):
            raise ValueError("Only conditional support requires a predicate.")
        return self

    @property
    def enabled(self) -> bool:
        """Return conservative unconditional support for existing boolean views."""
        return self.state == "supported"

    @property
    def nullable_enabled(self) -> bool | None:
        """Preserve unknown in existing nullable views without enabling conditions."""
        return None if self.state == "unknown" else self.enabled


class EffortDeclaration(BaseModel):
    """An individual effort fact and whether it was explicit or derived."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    level: ReasoningEffortValue
    state: Literal["supported", "unsupported", "unknown"]
    origin: EvidenceOrigin | None

    @model_validator(mode="after")
    def validate_origin(self) -> Self:
        """Require provenance for positive and negative effort declarations."""
        if (self.state == "unknown") != (self.origin is None):
            raise ValueError("Only unknown effort declarations may omit their origin.")
        return self


class DefaultEffortEvidence(BaseModel):
    """A saved known default; absence of this object means the default is unknown."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    level: ReasoningEffortValue
    origin: EvidenceOrigin


class ReasoningSupport(BaseModel):
    """Reasoning support and an explicitly complete, partial, or unknown effort set."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    support: CapabilitySupport
    completeness: EffortCompleteness
    efforts: tuple[EffortDeclaration, ...]
    default_effort: DefaultEffortEvidence | None

    @model_validator(mode="after")
    def validate_efforts(self) -> Self:
        """Reject contradictory sets without inventing missing levels or defaults."""
        levels = [declaration.level for declaration in self.efforts]
        if len(levels) != len(set(levels)):
            raise ValueError("Reasoning effort declarations must be unique.")
        if self.completeness == "unknown" and self.efforts:
            raise ValueError("Unknown effort completeness cannot contain declarations.")
        if self.completeness == "partial" and not self.efforts:
            raise ValueError("A partial effort set requires an individual declaration.")
        if self.completeness == "complete" and any(
            declaration.state == "unknown" for declaration in self.efforts
        ):
            raise ValueError(
                "A complete effort set cannot contain unknown declarations."
            )
        supported = {
            declaration.level
            for declaration in self.efforts
            if declaration.state == "supported"
        }
        if supported and self.support.state in {"unknown", "unsupported"}:
            raise ValueError("Supported efforts require justified reasoning support.")
        if self.default_effort is not None:
            if self.support.state == "unsupported":
                raise ValueError(
                    "Unsupported reasoning cannot declare a default effort."
                )
            if any(
                declaration.level == self.default_effort.level
                and declaration.state == "unsupported"
                for declaration in self.efforts
            ):
                raise ValueError("A default effort cannot be explicitly unsupported.")
            if (
                self.completeness == "complete"
                and self.default_effort.level not in supported
            ):
                raise ValueError(
                    "A default effort must belong to a complete effort set."
                )
        return self

    @property
    def enabled_efforts(self) -> tuple[ReasoningEffortValue, ...]:
        """Expose justified unconditional levels without expanding partial sets."""
        if not self.support.enabled:
            return ()
        return tuple(
            declaration.level
            for declaration in self.efforts
            if declaration.state == "supported"
        )


class ParameterSupport(BaseModel):
    """Independent support facts for the existing configurable parameters."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    temperature: CapabilitySupport
    max_output_tokens: CapabilitySupport
    top_p: CapabilitySupport
    top_k: CapabilitySupport
    stop_sequences: CapabilitySupport


class ModalitySupport(BaseModel):
    """One supported, denied, unknown, or conditional content form."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    modality: ModalityValue
    support: CapabilitySupport


class BuiltinToolSupport(BaseModel):
    """One implemented configurable tool's saved support fact."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    tool: BuiltinToolValue
    support: CapabilitySupport


class ModelCapabilityContract(BaseModel):
    """Version-two semantic authority carried by a newly projected selection.

    Existing boolean/list capability fields are conservative derived views of
    this object. Raw source records and collection provenance are stored outside
    this bounded dispatch contract. No field triggers source or profile lookup.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    version: Literal[2]
    reasoning: ReasoningSupport
    reasoning_summaries: CapabilitySupport
    function_calling: CapabilitySupport
    parallel_function_calls: CapabilitySupport
    strict_function_schema: CapabilitySupport
    structured_response: CapabilitySupport
    parameters: ParameterSupport
    input_modalities: tuple[ModalitySupport, ...]
    output_modalities: tuple[ModalitySupport, ...]
    built_in_tools: tuple[BuiltinToolSupport, ...]

    @model_validator(mode="after")
    def validate_unique_facts(self) -> Self:
        """Prevent conflicting duplicate facts and unsupported function refinements."""
        for modalities in (self.input_modalities, self.output_modalities):
            names = [declaration.modality for declaration in modalities]
            if len(names) != len(set(names)):
                raise ValueError("Modality support declarations must be unique.")
        tools = [declaration.tool for declaration in self.built_in_tools]
        if len(tools) != len(set(tools)):
            raise ValueError("Built-in tool support declarations must be unique.")
        if not self.function_calling.enabled and any(
            support.enabled
            for support in (self.parallel_function_calls, self.strict_function_schema)
        ):
            raise ValueError(
                "Unconditional function refinements require function support."
            )
        return self
