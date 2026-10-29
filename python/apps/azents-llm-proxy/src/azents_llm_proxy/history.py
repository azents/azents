"""Bounded generated-image replay correction before LiteLLM's generic bridge."""

import base64
import binascii
import copy
from typing import Literal

from openai.types.responses.response_input_param import ResponseInputItemParam
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from azents_llm_proxy.request import ResponseRequest
from azents_llm_proxy.settings import FidelityUnavailable


class _GeneratedImage(BaseModel):
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True)
    result: str = Field(repr=False)
    status: Literal["completed"]


def _data_url(encoded: str) -> str:
    try:
        content = base64.b64decode(encoded, validate=True)
    except binascii.Error, ValueError:
        raise FidelityUnavailable("Generated-image history is invalid.") from None
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        mime = "image/png"
    elif content.startswith(b"\xff\xd8\xff"):
        mime = "image/jpeg"
    elif content.startswith((b"GIF87a", b"GIF89a")):
        mime = "image/gif"
    elif content.startswith(b"RIFF") and content[8:12] == b"WEBP":
        mime = "image/webp"
    else:
        raise FidelityUnavailable("Generated-image media format is unavailable.")
    return f"data:{mime};base64,{encoded}"


def bridge_image_history(payload: ResponseRequest) -> ResponseRequest:
    """Retain call order and explicit image bytes without stored resource lookup.

    The existing Worker projects provider-tool results as a user-content message
    with a provider-tool provenance marker and inline media. Use that established
    semantic projection only for the generic bridge that drops native image-call
    items. Native Responses routes retain their original history unchanged.
    """
    history = payload.get("input")
    if history is None or isinstance(history, str):
        return payload
    rewritten: list[ResponseInputItemParam] = []
    for item in history:
        if isinstance(item, dict) and item.get("type") == "image_generation_call":
            try:
                image = _GeneratedImage.model_validate(item)
            except ValidationError:
                raise FidelityUnavailable(
                    "Generated-image history is incomplete."
                ) from None
            rewritten.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": "[Provider tool call: image_generation completed]",
                        },
                        {
                            "type": "input_image",
                            "image_url": _data_url(image.result),
                            "detail": "auto",
                        },
                    ],
                }
            )
        else:
            rewritten.append(item)
    result = copy.deepcopy(payload)
    result["input"] = rewritten
    return result
