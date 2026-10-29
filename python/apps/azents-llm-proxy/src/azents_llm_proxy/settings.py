"""Normalize current Agent controls without a second model-preference source."""

import copy

from azents_llm_contract.authority import (
    ApiKeyCredential,
    ChatGPTCredential,
    TargetBinding,
)
from azents_llm_contract.settings import Feature, ModelConfiguration, ReasoningEffort
from openai.types.shared_params import Reasoning

from azents_llm_proxy.request import InferenceRequest, ResponseRequest


class UnsupportedRequest(Exception):
    """A requested feature is not supported by the current selected candidate."""


class FidelityUnavailable(Exception):
    """A selected setting has no verified lossless translation in this artifact."""


def _reasoning(payload: ResponseRequest, config: ModelConfiguration) -> Reasoning:
    if "reasoning" in payload and "reasoning_effort" in payload:
        raise UnsupportedRequest("Conflicting reasoning declarations.")
    if "reasoning_effort" in payload:
        return {"effort": payload["reasoning_effort"]}
    if "reasoning" in payload:
        declared = payload["reasoning"]
        if declared is None or not declared:
            return {}
        if "effort" in declared:
            return copy.deepcopy(declared)
        result = copy.deepcopy(declared)
    else:
        result: Reasoning = {}
    if config.parameters is not None and config.parameters.reasoning_effort is not None:
        result["effort"] = config.parameters.reasoning_effort
    return result


def _supports(
    config: ModelConfiguration,
    feature: Feature,
    *,
    effort: ReasoningEffort | None,
    functions: bool,
) -> bool:
    if feature not in config.supported_features:
        return False
    for condition in config.feature_conditions:
        if condition.feature != feature:
            continue
        if condition.reasoning_efforts is not None:
            if effort not in condition.reasoning_efforts:
                return False
        if (
            condition.function_tools is not None
            and functions != condition.function_tools
        ):
            return False
    return True


def _validate_features(
    payload: ResponseRequest,
    config: ModelConfiguration,
    input_features: frozenset[Feature],
) -> None:
    tools = list(payload.get("tools") or ())
    functions = any(tool["type"] == "function" for tool in tools)
    reasoning = payload.get("reasoning")
    effort = reasoning.get("effort") if reasoning is not None else None
    omitted = "reasoning" not in payload or (
        reasoning is not None and bool(reasoning) and "effort" not in reasoning
    )
    context_effort = config.known_default_reasoning if omitted else effort
    required = set(input_features)
    for selected in config.builtin_tools:
        match selected.name:
            case "web_search":
                required.add("builtin:web_search")
            case "image_generation":
                required.add("builtin:image_generation")
                if config.protocol == "google":
                    required.add("output:image")
    for field, feature in (
        ("temperature", "temperature"),
        ("top_p", "top_p"),
        ("top_k", "top_k"),
        ("max_output_tokens", "max_output_tokens"),
        ("stop", "stop_sequences"),
    ):
        if payload.get(field) is not None:
            required.add(feature)
    if effort is not None:
        required.add("reasoning")
        if effort not in config.reasoning_efforts:
            raise UnsupportedRequest("Reasoning effort is unavailable.")
    if reasoning is not None and reasoning.get("summary") not in {None, "none"}:
        required.add("reasoning_summaries")
    if functions:
        required.add("function_calling")
    if payload.get("parallel_tool_calls") is True:
        required.add("parallel_function_calls")
    text = payload.get("text")
    if text is not None:
        output_format = text.get("format")
        if output_format is not None and output_format["type"] != "text":
            required.add("structured_response")
    for tool in tools:
        if tool["type"] == "function" and tool.get("strict") is True:
            required.add("strict_function_schema")
        elif tool["type"] in {"web_search", "web_search_preview"}:
            required.add("builtin:web_search")
        elif tool["type"] == "image_generation":
            required.add("builtin:image_generation")
    if any(
        not _supports(config, feature, effort=context_effort, functions=functions)
        for feature in required
    ):
        raise UnsupportedRequest("Requested feature is unavailable for this context.")


def normalize_request(
    selected: InferenceRequest, binding: TargetBinding
) -> ResponseRequest:
    """Saved controls apply before feature validation; null caps stay unset.

    An explicit caller reasoning clear is not replaced by the saved default.
    A saved output cap is authoritative and an explicit smaller caller cap wins.
    Model support facts are constraints, never defaults or user preferences.
    """
    payload = copy.deepcopy(selected.payload)
    config = binding.configuration
    parameters = config.parameters
    if parameters is not None:
        if "temperature" not in payload and parameters.temperature is not None:
            payload["temperature"] = parameters.temperature
        if "top_p" not in payload and parameters.top_p is not None:
            payload["top_p"] = parameters.top_p
        if "top_k" not in payload and parameters.top_k is not None:
            payload["top_k"] = parameters.top_k
        if "stop" not in payload and parameters.stop_sequences is not None:
            payload["stop"] = list(parameters.stop_sequences)
    reasoning = _reasoning(payload, config)
    payload.pop("reasoning_effort", None)
    if reasoning or "reasoning" in payload:
        payload["reasoning"] = reasoning
    maximum = payload.get("max_output_tokens")
    if config.max_output_tokens is not None:
        maximum = (
            config.max_output_tokens
            if maximum is None
            else min(maximum, config.max_output_tokens)
        )
    if maximum is not None and config.maximum_output_tokens is not None:
        maximum = min(maximum, config.maximum_output_tokens)
    if maximum is not None:
        payload["max_output_tokens"] = maximum
    tier = payload.get("service_tier")
    if tier == "fast":
        tier = "priority"
        payload["service_tier"] = tier
    supported = config.supported_execution_options
    if tier == "priority" and "fast" not in supported:
        raise UnsupportedRequest("Fast is unavailable for this model.")
    if tier == "ultrafast" and "ultrafast" not in supported:
        raise UnsupportedRequest("Ultrafast is unavailable for this model.")
    if tier not in {None, "default", "priority", "ultrafast"}:
        raise UnsupportedRequest("Service tier is not an Agent execution option.")
    credential = binding.credential
    openai = (
        isinstance(credential, ApiKeyCredential) and credential.provider == "openai"
    )
    if supported and not (openai or isinstance(credential, ChatGPTCredential)):
        raise FidelityUnavailable("Execution options require a supported provider.")
    if tier is None and supported and openai:
        payload["service_tier"] = "default"
    _validate_features(payload, config, selected.input_features)
    # Target selection and caller attribution never cross the provider boundary.
    payload.pop("metadata", None)
    payload["store"] = False
    return payload
