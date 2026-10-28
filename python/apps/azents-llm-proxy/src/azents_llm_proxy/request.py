"""Closed Responses ingress and explicit-history resource boundary."""

import base64
import binascii
import copy
import re
from dataclasses import dataclass
from typing import Literal

from azents_llm_contract.settings import Feature
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as SchemaValidationError
from openai.types.responses.response_create_params import ResponseCreateParamsBase
from pydantic import ConfigDict, TypeAdapter, ValidationError, with_config
from typing_extensions import NotRequired


@with_config(ConfigDict(extra="forbid", hide_input_in_errors=True))
class ResponseRequest(ResponseCreateParamsBase, total=False):
    """Official Responses fields plus normal LiteLLM generation controls only."""

    stream: NotRequired[bool]
    top_k: NotRequired[int]
    stop: NotRequired[str | list[str]]
    reasoning_effort: NotRequired[
        Literal["none", "minimal", "low", "medium", "high", "xhigh", "max"]
    ]


class RequestRejected(Exception):
    """Fixed safe diagnostic: never include prompt, tool, URL or token input."""


@dataclass(frozen=True, repr=False)
class InferenceRequest:
    model: str
    target_id: str
    payload: ResponseRequest
    input_features: frozenset[Feature]


_ADAPTER = TypeAdapter(ResponseRequest)


def _close_protocol_objects(value: object) -> None:
    """Close SDK protocol records while leaving user JSON schemas opaque.

    This operates on the SDK's schema, not on caller-provided function schemas.
    JSON-value dictionaries intentionally have no named protocol properties.
    """
    if isinstance(value, dict):
        if value.get("type") == "object" and "properties" in value:
            value["additionalProperties"] = False
        for child in value.values():
            _close_protocol_objects(child)
    elif isinstance(value, list):
        for child in value:
            _close_protocol_objects(child)


_SCHEMA = _ADAPTER.json_schema()
_close_protocol_objects(_SCHEMA)
_VALIDATOR = Draft202012Validator(_SCHEMA)
_TARGET = re.compile(r"[0-9a-f]{64}")
_ALLOWED_INPUT_ITEMS = frozenset(
    {
        None,
        "message",
        "function_call",
        "function_call_output",
        "reasoning",
        "web_search_call",
        "image_generation_call",
    }
)


def _validate_data_url(value: object, *, image: bool) -> None:
    if not isinstance(value, str) or ";base64," not in value:
        raise RequestRejected("Only inline bounded media is supported.")
    prefix, encoded = value.split(";base64,", 1)
    allowed = (
        {"data:image/png", "data:image/jpeg", "data:image/webp", "data:image/gif"}
        if image
        else {"data:application/pdf"}
    )
    if prefix not in allowed:
        raise RequestRejected("Media format is not supported.")
    _validate_base64(encoded)


def _validate_base64(value: object) -> None:
    if not isinstance(value, str) or not value:
        raise RequestRejected("Inline media is invalid.")
    try:
        base64.b64decode(value, validate=True)
    except binascii.Error, ValueError:
        raise RequestRejected("Inline media is invalid.") from None


def _validate_content_part(value: object) -> Feature:
    # SDK decoding and closed-schema validation precede these ingress checks.
    if not isinstance(value, dict):
        raise RequestRejected("Content part is not supported.")
    match value.get("type"):
        case "input_image":
            if value.get("file_id") is not None:
                raise RequestRejected("Stored media references are not supported.")
            _validate_data_url(value.get("image_url"), image=True)
            return "input:image"
        case "input_file":
            if value.get("file_id") is not None or value.get("file_url") is not None:
                raise RequestRejected(
                    "Stored or remote media references are not supported."
                )
            _validate_data_url(value.get("file_data"), image=False)
            return "input:pdf"
        case "input_text" | "output_text" | "refusal":
            return "input:text"
        case _:
            raise RequestRejected("Content part is not supported.")


def _validate_history(value: object) -> frozenset[Feature]:
    if isinstance(value, str):
        return frozenset({"input:text"})
    if not isinstance(value, list):
        raise RequestRejected("Explicit input history is required.")
    features: set[Feature] = set()
    for item in value:
        if not isinstance(item, dict) or item.get("type") not in _ALLOWED_INPUT_ITEMS:
            raise RequestRejected("Input item is not supported.")
        if item.get("type") == "image_generation_call":
            _validate_base64(item.get("result"))
            features.add("input:image")
        if item.get("type") == "function_call_output":
            output = item.get("output")
            if isinstance(output, list):
                for part in output:
                    features.add(_validate_content_part(part))
            elif isinstance(output, str):
                features.add("input:text")
        content = item.get("content")
        if isinstance(content, list):
            for part in content:
                features.add(_validate_content_part(part))
        elif isinstance(content, str):
            features.add("input:text")
    return frozenset(features)


def _sdk_image_defaults(value: object) -> object:
    """Express the documented auto detail default for the SDK's required key."""
    normalized = copy.deepcopy(value)
    if not isinstance(normalized, dict):
        return normalized
    history = normalized.get("input")
    if not isinstance(history, list):
        return normalized
    for item in history:
        if not isinstance(item, dict):
            continue
        for key in ("content", "output"):
            parts = item.get(key)
            if isinstance(parts, list):
                for part in parts:
                    if isinstance(part, dict) and part.get("type") == "input_image":
                        part.setdefault("detail", "auto")
    return normalized


def decode_request(value: object) -> InferenceRequest:
    """Validate once; unknown SDK/routing extensions never enter business logic."""
    normalized = _sdk_image_defaults(value)
    try:
        _VALIDATOR.validate(normalized)
        payload = _ADAPTER.validate_python(normalized, strict=True)
    except ValidationError, SchemaValidationError:
        raise RequestRejected("Invalid Responses request.") from None
    model = payload.get("model")
    metadata = payload.get("metadata")
    target = metadata.get("azents_target_id") if metadata is not None else None
    if not isinstance(model, str) or not model or len(model) > 2048:
        raise RequestRejected("A model selector is required.")
    if not isinstance(target, str) or _TARGET.fullmatch(target) is None:
        raise RequestRejected("A target selector is required.")
    if (
        payload.get("background") is True
        or payload.get("store") is True
        or payload.get("previous_response_id") is not None
        or payload.get("conversation") is not None
        or payload.get("prompt") is not None
    ):
        raise RequestRejected("Stored and background operations are not supported.")
    tools = payload.get("tools")
    if tools is not None:
        # SDK Iterable fields otherwise validate lazily and can be exhausted by
        # an authority check before the actual provider serialization.
        payload["tools"] = list(tools)
    include = payload.get("include")
    if include is not None:
        payload["include"] = list(include)
    for tool in payload.get("tools") or ():
        if tool["type"] not in {
            "function",
            "web_search",
            "web_search_preview",
            "image_generation",
        }:
            raise RequestRejected("Tool type is not supported.")
        if tool["type"] == "image_generation":
            mask = tool.get("input_image_mask")
            if mask is not None:
                if mask.get("file_id") is not None:
                    raise RequestRejected("Stored media references are not supported.")
                _validate_data_url(mask.get("image_url"), image=True)
    if "input" not in payload:
        raise RequestRejected("Explicit input history is required.")
    # Inspect JSON at ingress, before SDK union branches produce BaseModel
    # output items. Do not interpret function-argument schemas as transport data.
    assert isinstance(normalized, dict)
    input_features = _validate_history(normalized["input"])
    return InferenceRequest(
        model=model, target_id=target, payload=payload, input_features=input_features
    )
