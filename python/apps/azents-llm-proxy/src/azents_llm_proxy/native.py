"""Finite native Responses corrections through LiteLLM's public extra_body seam."""

from typing import Literal, TypedDict

from azents_llm_contract.authority import ChatGPTCredential, ProviderCredential
from openai.types.responses import ToolParam
from openai.types.responses.response_text_config_param import ResponseTextConfigParam

from azents_llm_proxy.request import ResponseRequest


class NativeCorrections(TypedDict, total=False):
    """Only admitted inference controls; never provider/credential/transport kwargs."""

    prompt_cache_key: str
    service_tier: Literal[
        "auto", "default", "flex", "scale", "priority", "fast", "ultrafast"
    ]
    max_output_tokens: int | None
    temperature: float | None
    top_p: float | None
    text: ResponseTextConfigParam
    tools: list[ToolParam]


def native_corrections(
    payload: ResponseRequest,
    credential: ProviderCredential,
) -> NativeCorrections | None:
    """Preserve existing controls dropped by the pinned ChatGPT transformer.

    LiteLLM merges internally supplied extra_body after provider transformation
    for both native Responses transports. No provider class or transport is
    replaced. The caller decoder rejects extra_body; this value is fresh and
    built only after current candidate settings/capability normalization.
    """
    if not isinstance(credential, ChatGPTCredential):
        return None
    result: NativeCorrections = {}
    key = payload.get("prompt_cache_key")
    if key is not None:
        result["prompt_cache_key"] = key
    tier = payload.get("service_tier")
    if tier is not None:
        result["service_tier"] = tier
    if "max_output_tokens" in payload:
        result["max_output_tokens"] = payload["max_output_tokens"]
    if "temperature" in payload:
        result["temperature"] = payload["temperature"]
    if "top_p" in payload:
        result["top_p"] = payload["top_p"]
    if "text" in payload:
        result["text"] = payload["text"]
    return result or None
