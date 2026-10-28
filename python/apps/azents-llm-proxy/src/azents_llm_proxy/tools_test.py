"""Selected tool settings retain ownership, restrictions and native image controls."""

import pytest
from azents_llm_contract.authority import (
    ApiKeyCredential,
    TargetBinding,
    VertexCredential,
)
from azents_llm_contract.settings import BuiltinToolSetting
from pydantic import JsonValue, SecretStr

from azents_llm_proxy.authority_test import binding
from azents_llm_proxy.provider_test import vertex
from azents_llm_proxy.request import decode_request
from azents_llm_proxy.request_test import request
from azents_llm_proxy.settings import (
    FidelityUnavailable,
    UnsupportedRequest,
    normalize_request,
)
from azents_llm_proxy.tools import bridge_controls, compile_tools

FUNCTION = {
    "type": "function",
    "name": "image_generation",
    "parameters": {"type": "object", "properties": {}},
    "strict": False,
}
CHAT_FUNCTION = {
    "type": "function",
    "function": {
        "name": "image_generation",
        "parameters": {"type": "object", "properties": {}},
        "strict": False,
    },
}


def selected(protocol: str, name: str, config: dict[str, JsonValue]) -> TargetBinding:
    value = binding()
    if protocol == "google":
        value = value.model_copy(
            update={
                "credential": ApiKeyCredential(
                    kind="api_key",
                    provider="google_gemini",
                    api_key=SecretStr("call-token"),
                )
            }
        )
    elif protocol == "anthropic":
        value = value.model_copy(
            update={
                "credential": ApiKeyCredential(
                    kind="api_key",
                    provider="anthropic",
                    api_key=SecretStr("call-token"),
                )
            }
        )
    return value.model_copy(
        update={
            "configuration": value.configuration.model_copy(
                update={
                    "protocol": protocol,
                    "builtin_tools": (
                        BuiltinToolSetting.model_validate(
                            {"name": name, "config": config}
                        ),
                    ),
                    "supported_features": (
                        "input:text",
                        "function_calling",
                        "builtin:web_search",
                        "builtin:image_generation",
                        "output:image",
                    ),
                }
            )
        }
    )


def test_native_search_preserves_closed_config_and_blocked_domain_extension() -> None:
    value = selected(
        "native_responses",
        "web_search",
        {
            "search_context_size": "high",
            "filters": {
                "allowed_domains": ["example.com"],
                "blocked_domains": ["blocked.example"],
            },
            "external_web_access": False,
        },
    )
    payload = normalize_request(
        decode_request({**request(), "tools": [FUNCTION]}), value
    )
    compiled = compile_tools(payload, value)
    assert compiled.native_response_tools == [
        FUNCTION,
        {
            "type": "web_search",
            "search_context_size": "high",
            "filters": {
                "allowed_domains": ["example.com"],
                "blocked_domains": ["blocked.example"],
            },
            "external_web_access": False,
        },
    ]
    assert compiled.anthropic_search is None and not compiled.google_search
    assert "private-prompt" not in repr(compiled)


@pytest.mark.parametrize(
    "config",
    [
        {"api_key": "tool-secret-sentinel"},
        {"user_config": {}},
        {"filters": {"api_base": "https://foreign.invalid"}},
        {"max_uses": 2},
    ],
)
def test_native_search_config_cannot_become_transport_or_unsupported_controls(
    config: dict[str, JsonValue],
) -> None:
    value = selected("native_responses", "web_search", config)
    with pytest.raises(FidelityUnavailable) as caught:
        compile_tools(decode_request(request()).payload, value)
    assert "tool-secret-sentinel" not in str(caught.value)


def test_xai_portable_search_keeps_domains_external_and_function_coexistence() -> None:
    value = selected(
        "responses",
        "web_search",
        {
            "blocked_domains": ["blocked.example"],
            "external_web_access": False,
            "search_context_size": "high",
            "user_location": {"city": "Seoul"},
        },
    )
    value = value.model_copy(
        update={
            "credential": ApiKeyCredential(
                kind="api_key", provider="xai", api_key=SecretStr("call-token")
            )
        }
    )
    compiled = compile_tools(
        decode_request({**request(), "tools": [FUNCTION]}).payload, value
    )
    assert compiled.native_response_tools == [
        FUNCTION,
        {
            "type": "web_search",
            "filters": {"blocked_domains": ["blocked.example"]},
            "external_web_access": False,
            "user_location": {"type": "approximate", "city": "Seoul"},
        },
    ]


def test_anthropic_search_retains_native_restrictions_and_all_function_tools() -> None:
    value = selected(
        "anthropic",
        "web_search",
        {
            "allowed_domains": ["example.com"],
            "max_uses": 2,
            "user_location": {"country": "KR"},
        },
    )
    compiled = compile_tools(
        decode_request({**request(), "tools": [FUNCTION]}).payload, value
    )
    controls = bridge_controls(compiled, [CHAT_FUNCTION])
    assert controls["tools"] == [
        CHAT_FUNCTION,
        {
            "type": "web_search_20250305",
            "name": "web_search",
            "allowed_domains": ["example.com"],
            "max_uses": 2,
            "user_location": {"type": "approximate", "country": "KR"},
        },
    ]
    assert "web_search_options" not in controls


@pytest.mark.parametrize(
    "protocol,config",
    [
        ("anthropic", {"external_web_access": False}),
        ("google", {"allowed_domains": ["example.com"]}),
        ("google", {"blocked_domains": []}),
        ("google", {"max_uses": 2}),
        ("google", {"external_web_access": False}),
    ],
)
def test_required_restrictions_are_never_replaced_by_unrestricted_search(
    protocol: str, config: dict[str, JsonValue]
) -> None:
    value = selected(protocol, "web_search", config)
    with pytest.raises(FidelityUnavailable):
        compile_tools(decode_request(request()).payload, value)


def test_google_search_uses_native_activation_with_no_invented_restrictions() -> None:
    value = selected("google", "web_search", {})
    compiled = compile_tools(decode_request(request()).payload, value)
    assert bridge_controls(compiled, None) == {"web_search_options": {}}
    assert compiled.native_response_tools is None


@pytest.mark.parametrize("vertex_route", [False, True])
def test_google_image_keeps_activation_size_and_aspect(vertex_route: bool) -> None:
    value = selected(
        "google",
        "image_generation",
        {
            "size": "2K",
            "aspect_ratio": "16:9",
            "output_format": "jpeg",
            "output_compression": 80,
        },
    )
    if vertex_route:
        value = value.model_copy(update={"credential": vertex("global")})
    compiled = compile_tools(decode_request(request()).payload, value)
    image = {"imageSize": "2K", "aspectRatio": "16:9"}
    if vertex_route:
        image.update({"outputMimeType": "image/jpeg", "outputCompressionQuality": 80})
    assert bridge_controls(compiled, None) == {
        "modalities": ["text", "image"],
        "extra_body": {"generationConfig": {"imageConfig": image}},
    }


@pytest.mark.parametrize(
    "config",
    [
        {"size": "1024x1024"},
        {"output_format": "png", "output_compression": 50},
        {"output_compression": 101},
    ],
)
def test_unsupported_google_image_controls_fail_before_dispatch(
    config: dict[str, JsonValue],
) -> None:
    value = selected("google", "image_generation", config)
    value = value.model_copy(update={"credential": vertex("global")})
    assert isinstance(value.credential, VertexCredential)
    with pytest.raises(FidelityUnavailable):
        compile_tools(decode_request(request()).payload, value)


def test_client_image_selection_does_not_become_a_native_provider_tool() -> None:
    value = selected(
        "native_responses",
        "image_generation",
        {"model_identifier": "gpt-image-fixture"},
    )
    payload = normalize_request(
        decode_request({**request(), "tools": [FUNCTION]}), value
    )
    compiled = compile_tools(payload, value)
    assert list(compiled.payload["tools"]) == [FUNCTION]
    assert compiled.client_owned == value.configuration.builtin_tools
    assert compiled.native_response_tools is None and compiled.google_image is None


def test_caller_hosted_tool_cannot_override_saved_selection() -> None:
    value = binding()
    with pytest.raises(UnsupportedRequest):
        compile_tools(
            decode_request({**request(), "tools": [{"type": "web_search"}]}).payload,
            value,
        )
