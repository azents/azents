"""Typed selected-tool ownership and finite provider-native declarations."""

from dataclasses import dataclass
from typing import Literal, Required, TypedDict, TypeVar

from azents_llm_contract.authority import (
    ApiKeyCredential,
    ChatGPTCredential,
    TargetBinding,
    XaiCredential,
)
from azents_llm_contract.settings import BuiltinToolSetting
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as SchemaValidationError
from openai.types.chat import ChatCompletionToolParam
from openai.types.responses import ToolParam, WebSearchToolParam
from openai.types.responses.web_search_tool_param import Filters, UserLocation
from pydantic import ConfigDict, TypeAdapter, ValidationError, with_config
from pydantic_ai.native_tools import ImageGenerationTool, WebSearchTool

from azents_llm_proxy.request import ResponseRequest, _close_protocol_objects
from azents_llm_proxy.settings import FidelityUnavailable, UnsupportedRequest


class _Filters(Filters, total=False):
    blocked_domains: list[str]


@with_config(ConfigDict(extra="forbid", hide_input_in_errors=True))
class _NativeSearch(TypedDict, total=False):
    type: Required[Literal["web_search"]]
    search_context_size: Literal["low", "medium", "high"]
    user_location: UserLocation | None
    external_web_access: bool
    filters: _Filters | None


class AnthropicSearch(TypedDict, total=False):
    type: Required[Literal["web_search_20250305"]]
    name: Required[Literal["web_search"]]
    max_uses: int
    allowed_domains: list[str]
    blocked_domains: list[str]
    user_location: UserLocation


class GoogleImageConfig(TypedDict, total=False):
    aspectRatio: str
    imageSize: Literal["512", "1K", "2K", "4K"]
    outputMimeType: Literal["image/png", "image/jpeg", "image/webp"]
    outputCompressionQuality: int


@dataclass(frozen=True, repr=False)
class ToolCompilation:
    payload: ResponseRequest
    native_response_tools: list[ToolParam] | None
    anthropic_search: AnthropicSearch | None
    google_search: bool
    google_image: GoogleImageConfig | None
    client_owned: tuple[BuiltinToolSetting, ...]


class _GoogleGenerationConfig(TypedDict):
    imageConfig: GoogleImageConfig


class _GoogleImageBody(TypedDict):
    generationConfig: _GoogleGenerationConfig


class _GoogleSearchOptions(TypedDict):
    """An explicit empty SDK option activates native unrestricted search."""


class BridgeControls(TypedDict, total=False):
    tools: list[ChatCompletionToolParam | AnthropicSearch]
    web_search_options: _GoogleSearchOptions
    modalities: list[Literal["text", "image"]]
    extra_body: _GoogleImageBody
    include_server_side_tool_invocations: Literal[True]


T = TypeVar("T")


def _decode(adapter: TypeAdapter[T], config: object) -> T:
    schema = adapter.json_schema()
    _close_protocol_objects(schema)
    try:
        Draft202012Validator(schema).validate(config)
        return adapter.validate_python(config)
    except ValidationError, SchemaValidationError:
        raise FidelityUnavailable(
            "Selected tool configuration is unavailable."
        ) from None


def _native_search(selected: BuiltinToolSetting) -> WebSearchToolParam:
    parsed = _decode(
        TypeAdapter(_NativeSearch), {"type": "web_search", **selected.config}
    )
    result: WebSearchToolParam = {"type": "web_search"}
    if "search_context_size" in parsed:
        result["search_context_size"] = parsed["search_context_size"]
    if "user_location" in parsed:
        result["user_location"] = parsed["user_location"]
    if "external_web_access" in parsed:
        result["external_web_access"] = parsed["external_web_access"]
    if "filters" in parsed:
        result["filters"] = parsed["filters"]
    return result


def _portable_search(tool: WebSearchTool, *, xai: bool) -> WebSearchToolParam:
    if tool.max_uses is not None:
        raise FidelityUnavailable("Selected search restriction is unavailable.")
    result: WebSearchToolParam = {"type": "web_search"}
    if not xai:
        result["search_context_size"] = tool.search_context_size
    if tool.user_location is not None:
        result["user_location"] = {"type": "approximate", **tool.user_location}
    filters: _Filters = {}
    if tool.allowed_domains is not None:
        filters["allowed_domains"] = list(tool.allowed_domains)
    if tool.blocked_domains is not None:
        filters["blocked_domains"] = list(tool.blocked_domains)
    if filters:
        result["filters"] = filters
    if tool.external_web_access is not None:
        result["external_web_access"] = tool.external_web_access
    return result


def _anthropic_search(tool: WebSearchTool) -> AnthropicSearch:
    if tool.external_web_access is False:
        raise FidelityUnavailable("Selected search restriction is unavailable.")
    result: AnthropicSearch = {"type": "web_search_20250305", "name": "web_search"}
    if tool.max_uses is not None:
        result["max_uses"] = tool.max_uses
    if tool.allowed_domains is not None:
        result["allowed_domains"] = list(tool.allowed_domains)
    if tool.blocked_domains is not None:
        result["blocked_domains"] = list(tool.blocked_domains)
    if tool.user_location is not None:
        result["user_location"] = {"type": "approximate", **tool.user_location}
    return result


def _google_image(tool: ImageGenerationTool, *, vertex: bool) -> GoogleImageConfig:
    result: GoogleImageConfig = {}
    if tool.aspect_ratio is not None:
        result["aspectRatio"] = tool.aspect_ratio
    if tool.size is not None:
        match tool.size:
            case "512" | "1K" | "2K" | "4K":
                result["imageSize"] = tool.size
            case _:
                raise FidelityUnavailable("Selected image size is unavailable.")
    if vertex:
        match tool.output_format:
            case "png":
                result["outputMimeType"] = "image/png"
            case "jpeg":
                result["outputMimeType"] = "image/jpeg"
            case "webp":
                result["outputMimeType"] = "image/webp"
            case None:
                pass
            case _:
                raise FidelityUnavailable("Selected image format is unavailable.")
        if tool.output_compression is not None:
            if not 0 <= tool.output_compression <= 100 or tool.output_format not in {
                None,
                "jpeg",
            }:
                raise FidelityUnavailable("Selected image compression is unavailable.")
            result["outputCompressionQuality"] = tool.output_compression
            result.setdefault("outputMimeType", "image/jpeg")
    return result


def compile_tools(payload: ResponseRequest, binding: TargetBinding) -> ToolCompilation:
    """Keep client tools caller-owned; inject only current saved hosted choices."""
    functions: list[ToolParam] = []
    for tool in payload.get("tools") or ():
        if tool["type"] != "function":
            raise UnsupportedRequest("Hosted tools are selected by Agent settings.")
        functions.append(tool)
    native_tools = list(functions)
    native_search = False
    anthropic: AnthropicSearch | None = None
    google_search = False
    google_image: GoogleImageConfig | None = None
    client_owned: list[BuiltinToolSetting] = []
    credential = binding.credential
    protocol = binding.configuration.protocol
    for selected in binding.configuration.builtin_tools:
        match selected.name:
            case "web_search":
                if protocol == "native_responses":
                    native_tools.append(_native_search(selected))
                    native_search = True
                    continue
                search = _decode(TypeAdapter(WebSearchTool), selected.config)
                if protocol == "anthropic":
                    anthropic = _anthropic_search(search)
                    native_tools.append({"type": "web_search"})
                elif protocol == "google":
                    if search.restricting_settings:
                        raise FidelityUnavailable(
                            "Selected search restriction is unavailable."
                        )
                    google_search = True
                    native_tools.append({"type": "web_search"})
                elif protocol == "responses":
                    xai = isinstance(credential, XaiCredential) or (
                        isinstance(credential, ApiKeyCredential)
                        and credential.provider == "xai"
                    )
                    if not xai:
                        raise FidelityUnavailable(
                            "Selected hosted search mapping is unavailable."
                        )
                    native_tools.append(_portable_search(search, xai=True))
                    native_search = True
                else:
                    raise FidelityUnavailable(
                        "Selected hosted search mapping is unavailable."
                    )
            case "image_generation":
                client_image = isinstance(
                    credential, ChatGPTCredential | XaiCredential
                ) or (
                    isinstance(credential, ApiKeyCredential)
                    and credential.provider in {"openai", "xai"}
                )
                if client_image:
                    client_owned.append(selected)
                elif protocol == "google":
                    image = _decode(TypeAdapter(ImageGenerationTool), selected.config)
                    google_image = _google_image(
                        image, vertex=credential.kind == "google_vertex_ai"
                    )
                    native_tools.append({"type": "image_generation"})
                else:
                    raise FidelityUnavailable(
                        "Selected hosted image mapping is unavailable."
                    )
    # Construct the SDK record without a raw JSON roundtrip or new kwargs source.
    normalized = payload.copy()
    if "tools" in payload or native_tools:
        normalized["tools"] = native_tools
    return ToolCompilation(
        payload=normalized,
        native_response_tools=native_tools if native_search else None,
        anthropic_search=anthropic,
        google_search=google_search,
        google_image=google_image,
        client_owned=tuple(client_owned),
    )


def bridge_controls(
    compiled: ToolCompilation, existing_tools: object
) -> BridgeControls:
    """Use advertised pre-deployment SDK parameters, not provider HTTP calls."""
    controls: BridgeControls = {}
    functions: list[ChatCompletionToolParam] = []
    if compiled.anthropic_search is not None or compiled.google_search:
        try:
            functions = TypeAdapter(list[ChatCompletionToolParam]).validate_python(
                [] if existing_tools is None else existing_tools
            )
        except ValidationError:
            raise FidelityUnavailable(
                "SDK function tool preparation is unavailable."
            ) from None
    if compiled.anthropic_search is not None:
        controls["tools"] = [*functions, compiled.anthropic_search]
    if compiled.google_search:
        controls["web_search_options"] = {}
        if functions:
            controls["include_server_side_tool_invocations"] = True
    if compiled.google_image is not None:
        controls["modalities"] = ["text", "image"]
        controls["extra_body"] = {
            "generationConfig": {"imageConfig": compiled.google_image}
        }
    return controls
