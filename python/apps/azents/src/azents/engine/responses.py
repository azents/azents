"""Shared settings and safe output errors for existing native Responses calls."""

import dataclasses

from openai.types.responses.response_text_config_param import ResponseTextConfigParam
from pydantic import TypeAdapter

from azents.core.enums import LLMProvider

_RESPONSE_TEXT_ADAPTER = TypeAdapter(ResponseTextConfigParam)
DEFAULT_RESPONSES_TEXT_CONFIG: ResponseTextConfigParam = (
    _RESPONSE_TEXT_ADAPTER.validate_python(
        {"format": {"type": "text"}, "verbosity": "low"}
    )
)


@dataclasses.dataclass(frozen=True)
class ResponsesOutputError(Exception):
    """A native Responses stream reported an explicit failure."""

    event_type: str
    message: str | None = None
    code: object | None = None
    param: object | None = None


def responses_max_output_tokens(
    provider: LLMProvider,
    max_output_tokens: int | None,
) -> int | None:
    """Preserve existing text-operation output limits for each provider."""
    if provider in {LLMProvider.OPENAI, LLMProvider.CHATGPT_OAUTH}:
        return None
    if max_output_tokens is None or max_output_tokens <= 0:
        return None
    return max_output_tokens
