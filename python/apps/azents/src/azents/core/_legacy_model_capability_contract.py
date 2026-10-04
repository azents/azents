"""Read historical v2 descriptors into final fields without rewriting stored JSON."""

from collections.abc import Mapping
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, model_validator

from azents.core.model_capability_contract import (
    BuiltinToolValue,
    ModalityValue,
    ModelCapabilityFeature,
    ModelFeatureCondition,
    ModelRequestConstraints,
    ReasoningEffortValue,
)


class _Predicate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    reasoning_efforts: tuple[ReasoningEffortValue, ...] | None
    function_tools: bool | None


class _Support(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    state: Literal["supported", "unsupported", "unknown", "conditional"]
    origin: Literal["explicit", "contract_derived"] | None
    predicate: _Predicate | None

    @model_validator(mode="after")
    def validate_legacy_shape(self) -> Self:
        if (self.state == "unknown") != (self.origin is None):
            raise ValueError("Historical support origin is inconsistent.")
        if (self.state == "conditional") != (self.predicate is not None):
            raise ValueError("Historical support predicate is inconsistent.")
        return self


class _Effort(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    level: ReasoningEffortValue
    state: Literal["supported", "unsupported", "unknown"]
    origin: Literal["explicit", "contract_derived"] | None

    @model_validator(mode="after")
    def validate_origin(self) -> Self:
        if (self.state == "unknown") != (self.origin is None):
            raise ValueError("Historical effort origin is inconsistent.")
        return self


class _Default(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    level: ReasoningEffortValue
    origin: Literal["explicit", "contract_derived"]


class _Reasoning(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    support: _Support
    completeness: Literal["complete", "partial", "unknown"]
    efforts: tuple[_Effort, ...]
    default_effort: _Default | None


class _Parameters(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    temperature: _Support
    max_output_tokens: _Support
    top_p: _Support
    top_k: _Support
    stop_sequences: _Support


class _Modality(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    modality: ModalityValue
    support: _Support


class _Builtin(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    tool: BuiltinToolValue
    support: _Support


class _Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    version: Literal[2]
    reasoning: _Reasoning
    reasoning_summaries: _Support
    function_calling: _Support
    parallel_function_calls: _Support
    strict_function_schema: _Support
    structured_response: _Support
    parameters: _Parameters
    input_modalities: tuple[_Modality, ...]
    output_modalities: tuple[_Modality, ...]
    built_in_tools: tuple[_Builtin, ...]

    @model_validator(mode="after")
    def validate_unique_declarations(self) -> Self:
        names = [
            [item.modality for item in self.input_modalities],
            [item.modality for item in self.output_modalities],
            [item.tool for item in self.built_in_tools],
            [item.level for item in self.reasoning.efforts],
        ]
        if any(len(values) != len(set(values)) for values in names):
            raise ValueError("Historical capability declarations must be unique.")
        return self


def decode_historical_capabilities(value: Mapping[str, object]) -> dict[str, object]:
    """Convert a read-only descriptor once; unknown never enables a final feature."""
    restored = dict(value)
    raw_contract = restored.pop("semantic_contract", None)
    if raw_contract is None:
        return restored
    contract = _Contract.model_validate(raw_contract)
    conditions: list[ModelFeatureCondition] = []

    def present(feature: ModelCapabilityFeature, support: _Support) -> bool:
        enabled = support.state in {"supported", "conditional"}
        if support.predicate is not None:
            conditions.append(
                ModelFeatureCondition(
                    feature=feature,
                    reasoning_efforts=support.predicate.reasoning_efforts,
                    function_tools=support.predicate.function_tools,
                )
            )
        return enabled

    function = present(
        ModelCapabilityFeature.FUNCTION_CALLING, contract.function_calling
    )
    parallel = present(
        ModelCapabilityFeature.PARALLEL_FUNCTION_CALLS, contract.parallel_function_calls
    )
    strict = present(
        ModelCapabilityFeature.STRICT_FUNCTION_SCHEMA, contract.strict_function_schema
    )
    if not function:
        # Historical conditional refinements did not imply known function support.
        # Keep the final view coherent without creating a positive parent feature.
        parallel = strict = False
        refinements = {
            ModelCapabilityFeature.PARALLEL_FUNCTION_CALLS,
            ModelCapabilityFeature.STRICT_FUNCTION_SCHEMA,
        }
        conditions = [
            condition
            for condition in conditions
            if condition.feature not in refinements
        ]
    restored["tool_calling"] = {
        "supported": function,
        "parallel_tool_calls": parallel,
        "strict_json_schema": strict,
    }
    reasoning = present(ModelCapabilityFeature.REASONING, contract.reasoning.support)
    restored["reasoning"] = {
        "supported": reasoning,
        "effort_levels": [
            effort.level
            for effort in contract.reasoning.efforts
            if reasoning and effort.state == "supported"
        ],
        "summaries": present(
            ModelCapabilityFeature.REASONING_SUMMARIES, contract.reasoning_summaries
        ),
    }
    restored["structured_response"] = present(
        ModelCapabilityFeature.STRUCTURED_RESPONSE, contract.structured_response
    )
    restored["parameters"] = {
        "temperature": present(
            ModelCapabilityFeature.TEMPERATURE, contract.parameters.temperature
        ),
        "max_output_tokens": present(
            ModelCapabilityFeature.MAX_OUTPUT_TOKENS,
            contract.parameters.max_output_tokens,
        ),
        "top_p": present(ModelCapabilityFeature.TOP_P, contract.parameters.top_p),
        "top_k": present(ModelCapabilityFeature.TOP_K, contract.parameters.top_k),
        "stop_sequences": present(
            ModelCapabilityFeature.STOP_SEQUENCES, contract.parameters.stop_sequences
        ),
    }
    restored["modalities"] = {
        "input": [
            item.modality
            for item in contract.input_modalities
            if present(ModelCapabilityFeature(f"input:{item.modality}"), item.support)
        ],
        "output": [
            item.modality
            for item in contract.output_modalities
            if present(ModelCapabilityFeature(f"output:{item.modality}"), item.support)
        ],
    }
    restored["built_in_tools"] = {
        "supported": [
            item.tool
            for item in contract.built_in_tools
            if present(ModelCapabilityFeature(f"builtin:{item.tool}"), item.support)
        ]
    }
    restored["request_constraints"] = ModelRequestConstraints(
        known_default=contract.reasoning.default_effort.level
        if contract.reasoning.default_effort is not None
        else None,
        feature_conditions=tuple(conditions),
    ).model_dump(mode="json")
    return restored
