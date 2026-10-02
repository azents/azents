"""Evaluate saved model support without a source, profile, or provider lookup."""

import dataclasses
from collections.abc import Mapping
from typing import assert_never

from pydantic import BaseModel, ConfigDict

from azents.core.llm_catalog import ModelCapabilities
from azents.core.model_capability_contract import CapabilitySupport


@dataclasses.dataclass(frozen=True)
class ModelSupportContext:
    """Effective saved effort and actual function-tool presence for one request."""

    reasoning_effort: str | None
    function_tools: bool | None


@dataclasses.dataclass(frozen=True)
class ModelSupportRequest:
    """Requested controls, distinct from values a lowerer supplies by default."""

    reasoning_effort: str | None
    function_tools: bool | None
    temperature: bool
    max_output_tokens: bool
    top_p: bool
    top_k: bool
    stop_sequences: bool
    parallel_function_calls: bool
    strict_function_schema: bool
    structured_response: bool
    reasoning_summary: bool


class _ReasoningOptions(BaseModel):
    """The support-relevant portion of a provider reasoning declaration."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    effort: str | None = None
    summary: str | None = None


class _ResponseFormat(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    type: str | None = None


class _ResponseText(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    format: _ResponseFormat | None = None


class _ExtraBodyOptions(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    reasoning: _ReasoningOptions | None = None


class ModelSupportOptions(BaseModel):
    """Decode support-relevant options at the provider translation boundary.

    Optional ingress fields preserve absence without inventing model facts.
    Unrelated options retain the existing SDK and credential validation.
    """

    model_config = ConfigDict(extra="ignore", frozen=True)

    reasoning: _ReasoningOptions | None = None
    extra_body: _ExtraBodyOptions | None = None
    openai_reasoning_effort: str | None = None
    anthropic_effort: str | None = None
    openai_reasoning_summary: str | None = None
    temperature: float | None = None
    max_output_tokens: int | None = None
    max_tokens: int | None = None
    top_p: float | None = None
    top_k: int | None = None
    stop: str | list[str] | None = None
    stop_sequences: list[str] | None = None
    parallel_tool_calls: bool | None = None
    text: _ResponseText | None = None

    @property
    def explicit_effort(self) -> str | None:
        """Resolve an explicit effort, rejecting conflicting wire declarations."""
        efforts = {
            effort
            for effort in (
                self.reasoning.effort if self.reasoning is not None else None,
                self.extra_body.reasoning.effort
                if self.extra_body is not None and self.extra_body.reasoning is not None
                else None,
                self.openai_reasoning_effort,
                self.anthropic_effort,
            )
            if effort is not None
        }
        if len(efforts) > 1:
            raise ValueError("Conflicting reasoning effort settings are not supported.")
        return next(iter(efforts), None)

    @property
    def summary_requested(self) -> bool:
        """Return whether a supported wire dialect explicitly requests summary."""
        return any(
            summary not in {None, "none"}
            for summary in (
                self.reasoning.summary if self.reasoning is not None else None,
                self.extra_body.reasoning.summary
                if self.extra_body is not None and self.extra_body.reasoning is not None
                else None,
                self.openai_reasoning_summary,
            )
        )

    @property
    def structured_response_requested(self) -> bool:
        """Keep response schemas separate from strict function definitions."""
        return (
            self.text is not None
            and self.text.format is not None
            and self.text.format.type in {"json_schema", "json_object"}
        )


def decode_model_support_options(options: Mapping[str, object]) -> ModelSupportOptions:
    """Decode declared support-relevant options before evaluating the contract."""
    return ModelSupportOptions.model_validate(dict(options))


def model_support_request_from_options(
    options: ModelSupportOptions,
    *,
    selected_effort: str | None,
    function_tools: bool,
    strict_function_schema: bool,
) -> ModelSupportRequest:
    """Build a typed request view without modifying wire options or selection."""
    wire_effort = options.explicit_effort
    if (
        selected_effort is not None
        and wire_effort is not None
        and selected_effort != wire_effort
    ):
        raise ValueError("Conflicting reasoning effort settings are not supported.")
    return ModelSupportRequest(
        reasoning_effort=wire_effort if wire_effort is not None else selected_effort,
        function_tools=function_tools,
        temperature=options.temperature is not None,
        max_output_tokens=(
            options.max_output_tokens is not None or options.max_tokens is not None
        ),
        top_p=options.top_p is not None,
        top_k=options.top_k is not None,
        stop_sequences=options.stop is not None or options.stop_sequences is not None,
        parallel_function_calls=options.parallel_tool_calls is True,
        strict_function_schema=strict_function_schema,
        structured_response=options.structured_response_requested,
        reasoning_summary=options.summary_requested,
    )


def resolve_model_support_context(
    capabilities: ModelCapabilities,
    *,
    requested_effort: str | None,
    function_tools: bool | None,
) -> ModelSupportContext:
    """Resolve conditions from explicit effort, then a known saved default.

    :param capabilities: the selected immutable capability snapshot
    :param requested_effort: explicit request setting, or omission
    :param function_tools: whether this request declares function tools
    :returns: condition context; an unknown default remains unknown
    """
    effort = requested_effort
    contract = capabilities.semantic_contract
    if effort is None and contract is not None:
        default = contract.reasoning.default_effort
        if default is not None:
            effort = default.level
    return ModelSupportContext(reasoning_effort=effort, function_tools=function_tools)


def model_support_allowed(
    support: CapabilitySupport, *, context: ModelSupportContext
) -> bool | None:
    """Evaluate a saved predicate while keeping unknown distinct from denial.

    :param support: one saved support fact
    :param context: actual request conditions, with possibly unknown effort
    :returns: allowed, denied, or unknown; does not alter the request
    """
    match support.state:
        case "supported":
            return True
        case "unsupported":
            return False
        case "unknown":
            return None
        case "conditional":
            predicate = support.predicate
            if predicate is None:
                raise ValueError("Conditional model support lacks its saved predicate.")
            if predicate.reasoning_efforts is not None and (
                context.reasoning_effort is None
                or context.reasoning_effort not in predicate.reasoning_efforts
            ):
                return False
            if predicate.function_tools is not None:
                if context.function_tools is None:
                    return None
                if predicate.function_tools != context.function_tools:
                    return False
            return True
        case _ as unreachable:
            assert_never(unreachable)


def validate_saved_model_request(
    capabilities: ModelCapabilities, *, request: ModelSupportRequest
) -> None:
    """Reject known incompatible controls without clamping or dropping settings.

    Unknown model support retains the existing provider error boundary instead of
    inventing a denial. Effort selection still requires an individually justified
    saved level, as it does in the existing inference-profile authorization path.
    Descriptor-absent historical selections retain their previous behavior.

    :param capabilities: saved capability authorization
    :param request: explicit requested controls and function-tool presence
    :raises ValueError: a requested control is denied or its condition is unmet
    """
    contract = capabilities.semantic_contract
    if contract is None:
        return
    context = resolve_model_support_context(
        capabilities,
        requested_effort=request.reasoning_effort,
        function_tools=request.function_tools,
    )
    if request.reasoning_effort is not None:
        allowed_efforts = {
            declaration.level
            for declaration in contract.reasoning.efforts
            if declaration.state == "supported"
        }
        if request.reasoning_effort not in allowed_efforts:
            raise ValueError(
                "Reasoning effort is not authorized by the saved capability snapshot"
            )
        _require_support(contract.reasoning.support, "reasoning effort", context)
    checks = (
        (request.function_tools, contract.function_calling, "function tools"),
        (request.temperature, contract.parameters.temperature, "temperature"),
        (
            request.max_output_tokens,
            contract.parameters.max_output_tokens,
            "maximum output tokens",
        ),
        (request.top_p, contract.parameters.top_p, "top-p"),
        (request.top_k, contract.parameters.top_k, "top-k"),
        (request.stop_sequences, contract.parameters.stop_sequences, "stop sequences"),
        (
            request.parallel_function_calls,
            contract.parallel_function_calls,
            "parallel function calls",
        ),
        (
            request.strict_function_schema,
            contract.strict_function_schema,
            "strict function schemas",
        ),
        (
            request.structured_response,
            contract.structured_response,
            "structured output",
        ),
        (request.reasoning_summary, contract.reasoning_summaries, "reasoning summary"),
    )
    for requested, support, name in checks:
        if requested:
            _require_support(support, name, context)


def _require_support(
    support: CapabilitySupport, name: str, context: ModelSupportContext
) -> None:
    if model_support_allowed(support, context=context) is not False:
        return
    if support.state == "conditional":
        raise ValueError(f"The selected request does not satisfy {name} conditions.")
    raise ValueError(f"The saved model contract does not support {name}.")


def saved_structured_response_support(
    capabilities: ModelCapabilities,
    *,
    requested_effort: str | None,
    function_tools: bool,
) -> bool | None:
    """Select the response-format contract independently from strict tool schemas.

    :returns: effective response support; the historical strict flag is retained
        only when no versioned response contract exists
    """
    contract = capabilities.semantic_contract
    if contract is None:
        return capabilities.tool_calling.strict_json_schema
    context = resolve_model_support_context(
        capabilities,
        requested_effort=requested_effort,
        function_tools=function_tools,
    )
    return model_support_allowed(contract.structured_response, context=context)


def saved_builtin_tool_allowed(
    capabilities: ModelCapabilities,
    *,
    tool: str,
    context: ModelSupportContext,
) -> bool:
    """Authorize route-projected built-in tools from satisfied saved facts.

    :param capabilities: immutable selected capability snapshot
    :param tool: actual requested route-projected built-in capability name
    :param context: effective effort and actual function-declaration presence
    :returns: known authorization; unknown or missing v2 facts remain unavailable
    """
    contract = capabilities.semantic_contract
    if contract is None:
        return tool in capabilities.built_in_tools.supported
    return any(
        declaration.tool == tool
        and model_support_allowed(declaration.support, context=context) is True
        for declaration in contract.built_in_tools
    )
