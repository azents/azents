"""Normalize provider-encoded request intent independently of model support."""

import dataclasses
from collections.abc import Mapping, Sequence
from typing import Annotated, Literal, assert_never

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, ValidationError
from pydantic_ai.models import ModelRequestParameters
from pydantic_ai.native_tools import ImageGenerationTool, WebSearchTool

type RequestDialect = Literal[
    "native_responses",
    "openai_responses",
    "openai_chat",
    "anthropic",
    "google",
    "bedrock",
]
type EffortLevel = Literal["none", "minimal", "low", "medium", "high", "xhigh", "max"]


class EffectiveRequestNormalizationError(ValueError):
    """The request lacks an exact implemented provider encoding."""


class _FrozenPayload(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True, strict=True)


def prepare_effective_model_parameters(
    parameters: ModelRequestParameters,
) -> ModelRequestParameters:
    """Resolve unrequested client strictness before SDK customization and admission.

    A shared response-schema codec flag may enable strict function defaults in
    the SDK. Selecting false for an unspecified function/output-tool preference
    prevents that encoding permission from inventing another requested feature.
    Explicit true/false and the independent native output object are preserved.

    :param parameters: provider request parameters before SDK customization
    :returns: a new parameter snapshot with deterministic function strictness
    """
    return dataclasses.replace(
        parameters,
        function_tools=[
            dataclasses.replace(tool, strict=False) if tool.strict is None else tool
            for tool in parameters.function_tools
        ],
        output_tools=[
            dataclasses.replace(tool, strict=False) if tool.strict is None else tool
            for tool in parameters.output_tools
        ],
    )


class OmittedReasoning(_FrozenPayload):
    """No reasoning declaration is present; a saved default may apply separately."""

    kind: Literal["omitted"] = "omitted"


class ClearedReasoning(_FrozenPayload):
    """An explicit null or empty declaration replaced a preceding declaration."""

    kind: Literal["cleared"] = "cleared"


class EffortReasoning(_FrozenPayload):
    kind: Literal["effort"] = "effort"
    level: EffortLevel


class BudgetReasoning(_FrozenPayload):
    """An explicit positive budget, without an invented canonical effort level."""

    kind: Literal["budget"] = "budget"
    tokens: int = Field(gt=0)


class AdaptiveReasoning(_FrozenPayload):
    """Provider-selected thinking, including Google's explicit automatic budget."""

    kind: Literal["adaptive"] = "adaptive"


class DisabledReasoning(_FrozenPayload):
    """Thinking is explicitly disabled by a provider-encoded declaration."""

    kind: Literal["disabled"] = "disabled"


type ReasoningIntent = Annotated[
    OmittedReasoning
    | ClearedReasoning
    | EffortReasoning
    | BudgetReasoning
    | AdaptiveReasoning
    | DisabledReasoning,
    Field(discriminator="kind"),
]


@dataclasses.dataclass(frozen=True)
class EffectiveModelRequest:
    """Actual provider-facing controls, not catalog facts or model authorization.

    ``present_fields`` retains explicit null/false/empty declarations. Only an
    omitted reasoning intent permits a consumer to consult a saved default.
    """

    dialect: RequestDialect
    reasoning: ReasoningIntent
    encoded_thinking: ReasoningIntent | None
    reasoning_summary: str | None
    temperature: float | None
    max_output_tokens: int | None
    top_p: float | None
    top_k: int | None
    stop_sequences: str | tuple[str, ...] | None
    parallel_function_calls: bool | None
    function_tools: bool
    builtin_tools: tuple[Literal["web_search", "image_generation"], ...]
    strict_function_schema: bool
    structured_response: bool
    present_fields: frozenset[str]

    @property
    def reasoning_effort(self) -> EffortLevel | None:
        """Return the unchanged scalar or explicit off, never a budget-derived level."""
        match self.reasoning:
            case EffortReasoning(level=level):
                return level
            case DisabledReasoning():
                return "none"
            case (
                OmittedReasoning()
                | ClearedReasoning()
                | BudgetReasoning()
                | AdaptiveReasoning()
            ):
                return None
            case _ as unreachable:
                assert_never(unreachable)

    @property
    def summary_requested(self) -> bool:
        return self.reasoning_summary not in {None, "none"}


class _ReasoningDeclaration(_FrozenPayload):
    effort: EffortLevel | None = None
    summary: str | None = None


class _ThinkingDeclaration(_FrozenPayload):
    type: Literal["disabled", "enabled", "adaptive"] | None = None
    budget_tokens: int | None = None
    thinking_level: Literal["MINIMAL", "LOW", "MEDIUM", "HIGH"] | None = Field(
        default=None, validation_alias=AliasChoices("thinking_level", "thinkingLevel")
    )
    thinking_budget: int | None = Field(
        default=None, validation_alias=AliasChoices("thinking_budget", "thinkingBudget")
    )
    include_thoughts: bool | None = Field(
        default=None,
        validation_alias=AliasChoices("include_thoughts", "includeThoughts"),
    )


class _FormatDeclaration(_FrozenPayload):
    type: str | None = None


class _TextDeclaration(_FrozenPayload):
    format: _FormatDeclaration | None = None


class _OutputConfiguration(_FrozenPayload):
    effort: EffortLevel | None = None
    format: _FormatDeclaration | None = None


class _FunctionDeclaration(_FrozenPayload):
    name: str | None = None
    strict: bool | None = None


class _ToolDeclaration(_FrozenPayload):
    type: str | None = None
    name: str | None = None
    strict: bool | None = None
    function: _FunctionDeclaration | None = None
    google_search: dict[str, object] | None = Field(
        default=None, validation_alias=AliasChoices("google_search", "googleSearch")
    )
    function_declarations: list[_FunctionDeclaration] | None = Field(
        default=None,
        validation_alias=AliasChoices("function_declarations", "functionDeclarations"),
    )
    tool_spec: _FunctionDeclaration | None = Field(
        default=None, validation_alias=AliasChoices("tool_spec", "toolSpec")
    )

    @property
    def function_tool(self) -> bool:
        # Anthropic function definitions have no type; hosted definitions do.
        return (
            self.type in {"function", "custom"}
            or self.type is None
            and self.name is not None
            or bool(self.function_declarations)
            or self.tool_spec is not None
        )

    @property
    def strict_function(self) -> bool:
        return (
            self.function_tool
            and self.type != "custom"
            and (
                self.strict is True
                or self.function is not None
                and self.function.strict is True
                or any(
                    declaration.strict is True
                    for declaration in self.function_declarations or ()
                )
                or self.tool_spec is not None
                and self.tool_spec.strict is True
            )
        )

    @property
    def builtin(self) -> Literal["web_search", "image_generation"] | None:
        if (
            self.function_tool
            or self.type == "custom"
            or self.function_declarations is not None
        ):
            return None
        if (
            self.type
            in {
                "web_search",
                "openrouter:web_search",
                "web_search_20250305",
                "web_search_20260209",
            }
            or self.google_search is not None
        ):
            return "web_search"
        if self.type == "image_generation":
            return "image_generation"
        if self.type is None and (
            "google_search" in self.model_fields_set
            or "tool_spec" in self.model_fields_set
        ):
            return None
        raise EffectiveRequestNormalizationError(
            "The final request contains an unimplemented native tool declaration."
        )


class _ToolChoice(_FrozenPayload):
    type: str | None = None
    disable_parallel_tool_use: bool | None = None


class _InferenceConfiguration(_FrozenPayload):
    max_tokens: int | None = Field(
        default=None, validation_alias=AliasChoices("max_tokens", "maxTokens")
    )
    temperature: float | None = None
    top_p: float | None = Field(
        default=None, validation_alias=AliasChoices("top_p", "topP")
    )
    top_k: int | None = Field(
        default=None, validation_alias=AliasChoices("top_k", "topK")
    )
    stop_sequences: list[str] | None = Field(
        default=None, validation_alias=AliasChoices("stop_sequences", "stopSequences")
    )


class _WireBody(_FrozenPayload):
    """Support-relevant body fields decoded before shallow SDK overlay evaluation."""

    reasoning: _ReasoningDeclaration | None = None
    reasoning_effort: EffortLevel | None = None
    thinking: _ThinkingDeclaration | None = None
    output_config: _OutputConfiguration | None = None
    text: _TextDeclaration | None = None
    response_format: _FormatDeclaration | None = None
    temperature: float | None = None
    max_output_tokens: int | None = None
    max_tokens: int | None = None
    max_completion_tokens: int | None = None
    top_p: float | None = None
    top_k: int | None = None
    stop: str | list[str] | None = None
    stop_sequences: list[str] | None = None
    parallel_tool_calls: bool | None = None
    tools: list[_ToolDeclaration] | None = None
    tool_choice: _ToolChoice | str | None = None
    inferenceConfig: _InferenceConfiguration | None = None
    reasoning_config: Literal["low", "high"] | None = None


class _ProviderOptions(_FrozenPayload):
    """Typed authored SDK options plus already encoded provider declarations."""

    reasoning: _ReasoningDeclaration | None = None
    text: _TextDeclaration | None = None
    response_format: _FormatDeclaration | None = None
    temperature: float | None = None
    max_output_tokens: int | None = None
    max_tokens: int | None = None
    top_p: float | None = None
    top_k: int | None = None
    stop: str | list[str] | None = None
    stop_sequences: list[str] | None = None
    parallel_tool_calls: bool | None = None
    tools: list[_ToolDeclaration] | None = None
    tool_choice: _ToolChoice | str | None = None
    extra_body: _WireBody | None = None
    openai_reasoning_effort: EffortLevel | None = None
    openai_reasoning_summary: str | None = None
    openai_native_tools: list[_ToolDeclaration] | None = None
    anthropic_effort: EffortLevel | None = None
    anthropic_thinking: _ThinkingDeclaration | None = None
    google_thinking_config: _ThinkingDeclaration | None = None
    google_response_mime_type: str | None = None
    google_response_json_schema: dict[str, object] | None = None
    bedrock_additional_model_requests_fields: _WireBody | None = None
    thinking_control: (
        bool | Literal["minimal", "low", "medium", "high", "xhigh"] | None
    ) = Field(default=None, validation_alias="thinking")


def _overlay(body: _WireBody, overlay: _WireBody | None) -> _WireBody:
    """Use the SDK's top-level replacement; nested objects are not deep-merged."""
    if overlay is None:
        return body
    values = body.model_dump(exclude_unset=True)
    values.update(overlay.model_dump(exclude_unset=True))
    return _WireBody.model_validate(values)


def _thinking_intent(
    value: _ThinkingDeclaration | None, *, dialect: RequestDialect
) -> ReasoningIntent:
    if value is None:
        return ClearedReasoning()
    if value.type == "disabled":
        return DisabledReasoning()
    if value.type == "adaptive" or dialect == "google" and value.thinking_budget == -1:
        return AdaptiveReasoning()
    if value.thinking_level is not None:
        match value.thinking_level:
            case "MINIMAL":
                return EffortReasoning(level="minimal")
            case "LOW":
                return EffortReasoning(level="low")
            case "MEDIUM":
                return EffortReasoning(level="medium")
            case "HIGH":
                return EffortReasoning(level="high")
            case _ as unreachable:
                assert_never(unreachable)
    budget = (
        value.thinking_budget
        if value.thinking_budget is not None
        else value.budget_tokens
    )
    if budget == 0 and dialect == "google":
        return DisabledReasoning()
    if budget is not None:
        if budget <= 0:
            raise EffectiveRequestNormalizationError(
                "The encoded thinking budget is invalid."
            )
        return BudgetReasoning(tokens=budget)
    if value.type == "enabled" or value.include_thoughts is True:
        return AdaptiveReasoning()
    return ClearedReasoning()


def _reasoning_intent(
    body: _WireBody, dialect: RequestDialect, *, reasoning_replaced: bool
) -> ReasoningIntent:
    if (
        dialect in {"native_responses", "openai_responses"}
        and "reasoning" in body.model_fields_set
    ):
        if body.reasoning is None:
            return ClearedReasoning()
        if body.reasoning.effort is None:
            return (
                ClearedReasoning()
                if reasoning_replaced
                or not body.reasoning.model_fields_set
                or "effort" in body.reasoning.model_fields_set
                else OmittedReasoning()
            )
        return EffortReasoning(level=body.reasoning.effort)
    if dialect == "openai_chat":
        if "reasoning" in body.model_fields_set:
            if body.reasoning is None or body.reasoning.effort is None:
                return ClearedReasoning()
            if (
                body.reasoning_effort is not None
                and body.reasoning_effort != body.reasoning.effort
            ):
                raise EffectiveRequestNormalizationError(
                    "The final body has conflicting reasoning dialects."
                )
            return EffortReasoning(level=body.reasoning.effort)
        if "reasoning_effort" in body.model_fields_set:
            return (
                EffortReasoning(level=body.reasoning_effort)
                if body.reasoning_effort is not None
                else ClearedReasoning()
            )
    if dialect in {"anthropic", "bedrock"}:
        if body.output_config is not None and body.output_config.effort is not None:
            return EffortReasoning(level=body.output_config.effort)
        if "thinking" in body.model_fields_set:
            return _thinking_intent(body.thinking, dialect=dialect)
        if "output_config" in body.model_fields_set:
            return ClearedReasoning()
        if "reasoning_effort" in body.model_fields_set:
            return (
                EffortReasoning(level=body.reasoning_effort)
                if body.reasoning_effort is not None
                else ClearedReasoning()
            )
        if body.reasoning_config is not None:
            return EffortReasoning(level=body.reasoning_config)
    if dialect == "google" and "thinking" in body.model_fields_set:
        return _thinking_intent(body.thinking, dialect=dialect)
    return OmittedReasoning()


def _encoded_thinking_override(
    dialect: RequestDialect, options: _ProviderOptions, body: _WireBody
) -> bool:
    """Identify an actual override of generic SDK thinking translation."""
    if dialect == "google":
        config = options.google_thinking_config
        # The installed SDK checks this object for truthiness before it uses
        # it. Null/empty config does not override a specified generic setting.
        return config is not None and bool(config.model_fields_set)
    if dialect == "anthropic":
        config = options.anthropic_thinking
        return (
            config is not None
            and bool(config.model_fields_set)
            or options.extra_body is not None
            and "thinking" in options.extra_body.model_fields_set
        )
    if dialect == "bedrock":
        additional = options.bedrock_additional_model_requests_fields
        return additional is not None and any(
            key in additional.model_fields_set
            for key in ("thinking", "reasoning_effort", "reasoning_config")
        )
    return any(
        key in body.model_fields_set for key in ("reasoning", "reasoning_effort")
    )


def normalize_effective_model_request(
    *,
    dialect: RequestDialect,
    options: Mapping[str, object],
    parameters: ModelRequestParameters | None,
    native_tools: Sequence[Mapping[str, object]] | None,
) -> EffectiveModelRequest:
    """Normalize actual encoded controls without consulting support or credentials.

    Provider-specific declarations must already carry the selected SDK wire
    encoding. An unresolved generic thinking control cannot prove a lossless
    profile-dependent translation. Explicit budgets remain budgets, not levels.

    :param dialect: actual selected request encoder, not a model-name family
    :param options: request-only SDK options or already encoded native options
    :param parameters: SDK tool/output declarations; output tools count as functions
    :param native_tools: native declarations, or omission for SDK declarations
    :returns: immutable physically effective request intent
    :raises EffectiveRequestNormalizationError: an ambiguous or unimplemented encoding
    """
    if any(
        key in options
        for key in (
            "api_key",
            "base_url",
            "api_base",
            "aws_secret_access_key",
            "vertex_credentials",
            "extra_headers",
        )
    ):
        raise EffectiveRequestNormalizationError(
            "Request intent must not contain client credentials."
        )
    try:
        decoded = _ProviderOptions.model_validate(dict(options))
    except ValidationError as exc:
        raise EffectiveRequestNormalizationError(
            "The request has no implemented provider encoding."
        ) from exc
    values: dict[str, object] = {}
    scalar_names = ("temperature", "top_p", "top_k", "parallel_tool_calls")
    for name in scalar_names:
        if name in decoded.model_fields_set:
            values[name] = decoded.model_dump(include={name})[name]
    if dialect == "native_responses":
        for name in (
            "reasoning",
            "text",
            "response_format",
            "max_output_tokens",
            "stop",
            "tools",
            "tool_choice",
        ):
            if name in decoded.model_fields_set:
                values[name] = decoded.model_dump(include={name})[name]
    else:
        if "max_tokens" in decoded.model_fields_set:
            values[
                "max_output_tokens"
                if dialect in {"openai_responses", "google"}
                else "max_completion_tokens"
                if dialect == "openai_chat"
                else "max_tokens"
            ] = decoded.max_tokens
        if "stop_sequences" in decoded.model_fields_set:
            values[
                "stop"
                if dialect in {"openai_responses", "openai_chat"}
                else "stop_sequences"
            ] = decoded.stop_sequences
        if dialect in {"openai_responses", "openai_chat"}:
            if dialect == "openai_responses":
                reasoning: dict[str, object] = {}
                if decoded.openai_reasoning_effort is not None:
                    reasoning["effort"] = decoded.openai_reasoning_effort
                if decoded.openai_reasoning_summary is not None:
                    reasoning["summary"] = decoded.openai_reasoning_summary
                if reasoning:
                    values["reasoning"] = reasoning
            elif "openai_reasoning_effort" in decoded.model_fields_set:
                values["reasoning_effort"] = decoded.openai_reasoning_effort
        elif dialect == "anthropic":
            if decoded.anthropic_effort is not None:
                values["output_config"] = {"effort": decoded.anthropic_effort}
            if "anthropic_thinking" in decoded.model_fields_set:
                values["thinking"] = (
                    decoded.anthropic_thinking.model_dump(exclude_unset=True)
                    if decoded.anthropic_thinking is not None
                    else None
                )
        elif dialect == "google":
            if "google_thinking_config" in decoded.model_fields_set:
                values["thinking"] = (
                    decoded.google_thinking_config.model_dump(exclude_unset=True)
                    if decoded.google_thinking_config is not None
                    else None
                )
    try:
        body = _WireBody.model_validate(values)
    except ValidationError as exc:
        raise EffectiveRequestNormalizationError(
            "The request has no implemented provider encoding."
        ) from exc
    if dialect == "bedrock":
        additional = decoded.bedrock_additional_model_requests_fields
        if additional is not None:
            # Additional model fields are a separate body scope. Nova's nested
            # inferenceConfig only supplies the verified topK family encoding;
            # it does not replace general Converse sampling or token controls.
            encoded = _WireBody.model_validate(
                additional.model_dump(
                    include={
                        "output_config",
                        "thinking",
                        "reasoning_effort",
                        "reasoning_config",
                        "top_k",
                        "inferenceConfig",
                    },
                    exclude_unset=True,
                )
            )
            body = _overlay(body, encoded)
    elif dialect != "google":
        body = _overlay(body, decoded.extra_body)
    reasoning_intent = _reasoning_intent(
        body,
        dialect,
        reasoning_replaced=(
            decoded.extra_body is not None
            and "reasoning" in decoded.extra_body.model_fields_set
        ),
    )
    unresolved_thinking = decoded.thinking_control
    if parameters is not None and parameters.thinking is not None:
        unresolved_thinking = parameters.thinking
    if unresolved_thinking is not None and not _encoded_thinking_override(
        dialect, decoded, body
    ):
        raise EffectiveRequestNormalizationError(
            "Generic thinking requires an actual provider-encoded declaration."
        )
    declarations = (
        [_ToolDeclaration.model_validate(dict(tool)) for tool in native_tools]
        if native_tools is not None
        else []
    )
    if parameters is not None and native_tools is None:
        declarations.extend(
            _ToolDeclaration(type="function", name=tool.name, strict=tool.strict)
            for tool in [*parameters.function_tools, *parameters.output_tools]
        )
    if native_tools is None and parameters is not None:
        for tool in parameters.native_tools:
            if isinstance(tool, WebSearchTool):
                declarations.append(_ToolDeclaration(type="web_search"))
            elif isinstance(tool, ImageGenerationTool):
                declarations.append(_ToolDeclaration(type="image_generation"))
            else:
                raise EffectiveRequestNormalizationError(
                    "The SDK native tool has no implemented product capability."
                )
    if native_tools is None and dialect in {"openai_responses", "openai_chat"}:
        declarations.extend(decoded.openai_native_tools or ())
    if "tools" in body.model_fields_set:
        declarations = body.tools if body.tools is not None else []
    function_tools = any(tool.function_tool for tool in declarations)
    parallel = body.parallel_tool_calls
    if (
        dialect == "anthropic"
        and isinstance(body.tool_choice, _ToolChoice)
        and body.tool_choice.disable_parallel_tool_use is not None
    ):
        parallel = not body.tool_choice.disable_parallel_tool_use
    if dialect in {"google", "bedrock"} and parallel is not None:
        raise EffectiveRequestNormalizationError(
            "Parallel function calls have no explicit mapping in this codec."
        )
    structured = (
        (
            body.text is not None
            and body.text.format is not None
            and body.text.format.type in {"json_schema", "json_object"}
        )
        or (
            body.response_format is not None
            and body.response_format.type in {"json_schema", "json_object"}
        )
        or (
            body.output_config is not None
            and body.output_config.format is not None
            and body.output_config.format.type == "json_schema"
        )
    )
    # Native response schemas are encoded from output_object, independently from
    # synthetic function-coded output tools. A shallow body override owns clearing.
    if (
        parameters is not None
        and parameters.output_mode == "native"
        and parameters.output_object is not None
    ):
        format_key = (
            "text"
            if dialect == "openai_responses"
            else "response_format"
            if dialect == "openai_chat"
            else "output_config"
            if dialect == "anthropic"
            else None
        )
        if format_key is None or format_key not in body.model_fields_set:
            structured = True
        elif (
            dialect == "anthropic"
            and body.output_config is not None
            and "format" not in body.output_config.model_fields_set
            and (
                decoded.extra_body is None
                or "output_config" not in decoded.extra_body.model_fields_set
            )
        ):
            structured = True
    if dialect == "google" and (
        decoded.google_response_json_schema is not None
        or decoded.google_response_mime_type == "application/json"
    ):
        structured = True
    inference = body.inferenceConfig
    stop = (
        body.stop
        if dialect in {"native_responses", "openai_responses", "openai_chat"}
        else body.stop_sequences
    )
    maximum = (
        body.max_output_tokens
        if dialect in {"native_responses", "openai_responses", "google"}
        else body.max_completion_tokens
        if dialect == "openai_chat"
        else body.max_tokens
    )
    return EffectiveModelRequest(
        dialect=dialect,
        reasoning=reasoning_intent,
        encoded_thinking=(
            _thinking_intent(body.thinking, dialect=dialect)
            if "thinking" in body.model_fields_set
            else None
        ),
        reasoning_summary=body.reasoning.summary
        if body.reasoning is not None
        else None,
        temperature=body.temperature,
        max_output_tokens=maximum,
        top_p=body.top_p,
        top_k=inference.top_k
        if dialect == "bedrock"
        and inference is not None
        and "top_k" in inference.model_fields_set
        else body.top_k,
        stop_sequences=tuple(stop) if isinstance(stop, list) else stop,
        parallel_function_calls=parallel,
        function_tools=function_tools,
        builtin_tools=tuple(
            dict.fromkeys(
                builtin
                for tool in declarations
                if (builtin := tool.builtin) is not None
            )
        ),
        strict_function_schema=any(tool.strict_function for tool in declarations),
        structured_response=structured,
        present_fields=frozenset(body.model_fields_set),
    )
