"""ChatGPT Responses Lite standalone web-search tool."""

import dataclasses
import json
from collections.abc import Mapping

import httpx

from azents.core.chatgpt_oauth import CHATGPT_OAUTH_PROTOCOL_VERSION
from azents.core.enums import LLMProvider
from azents.engine.run.types import (
    BuiltinToolSpec,
    FunctionTool,
    FunctionToolError,
    FunctionToolSpec,
)

_TOOL_NAME = "web_search"
_SEARCH_PATH = "alpha/search"
_SEARCH_TIMEOUT_SECONDS = 30.0
_SEARCH_MAX_OUTPUT_TOKENS = 10_000
_ALLOWED_COMMANDS = {
    "search_query",
    "image_query",
    "open",
    "click",
    "find",
    "screenshot",
    "finance",
    "weather",
    "sports",
    "time",
    "response_length",
}

_WEB_SEARCH_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        "search_query": {
            "type": "array",
            "maxItems": 4,
            "items": {
                "type": "object",
                "properties": {
                    "q": {"type": "string"},
                    "recency": {"type": "integer", "minimum": 0},
                    "domains": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
                "required": ["q"],
                "additionalProperties": False,
            },
        },
        "image_query": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"q": {"type": "string"}},
                "required": ["q"],
                "additionalProperties": False,
            },
        },
        "open": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "ref_id": {"type": "string"},
                    "lineno": {"type": "integer", "minimum": 0},
                },
                "required": ["ref_id"],
                "additionalProperties": False,
            },
        },
        "click": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "ref_id": {"type": "string"},
                    "id": {"type": "integer", "minimum": 0},
                },
                "required": ["ref_id", "id"],
                "additionalProperties": False,
            },
        },
        "find": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "ref_id": {"type": "string"},
                    "pattern": {"type": "string"},
                },
                "required": ["ref_id", "pattern"],
                "additionalProperties": False,
            },
        },
        "screenshot": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "ref_id": {"type": "string"},
                    "pageno": {"type": "integer", "minimum": 0},
                },
                "required": ["ref_id", "pageno"],
                "additionalProperties": False,
            },
        },
        "finance": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "ticker": {"type": "string"},
                    "type": {
                        "type": "string",
                        "enum": ["equity", "fund", "crypto", "index"],
                    },
                    "market": {"type": "string"},
                },
                "required": ["ticker", "type"],
                "additionalProperties": False,
            },
        },
        "weather": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "location": {"type": "string"},
                    "start": {"type": "string"},
                    "duration": {"type": "integer", "minimum": 1},
                },
                "required": ["location"],
                "additionalProperties": False,
            },
        },
        "sports": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "tool": {"type": "string", "enum": ["sports"]},
                    "fn": {"type": "string", "enum": ["schedule", "standings"]},
                    "league": {
                        "type": "string",
                        "enum": [
                            "nba",
                            "wnba",
                            "nfl",
                            "nhl",
                            "mlb",
                            "epl",
                            "ncaamb",
                            "ncaawb",
                            "ipl",
                        ],
                    },
                    "team": {"type": "string"},
                    "opponent": {"type": "string"},
                    "date_from": {"type": "string"},
                    "date_to": {"type": "string"},
                    "num_games": {"type": "integer", "minimum": 1},
                    "locale": {"type": "string"},
                },
                "required": ["fn", "league"],
                "additionalProperties": False,
            },
        },
        "time": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"utc_offset": {"type": "string"}},
                "required": ["utc_offset"],
                "additionalProperties": False,
            },
        },
        "response_length": {
            "type": "string",
            "enum": ["short", "medium", "long"],
        },
    },
    "additionalProperties": False,
}

_WEB_SEARCH_DESCRIPTION = """Search and browse current internet sources.

Use search_query for one or more searches. Use open, click, or find with reference IDs
returned by earlier calls. Use response_length to request short, medium, or long output.
Cite final claims with the source URLs returned by this tool.
"""


@dataclasses.dataclass(frozen=True)
class ChatGPTWebSearchConfig:
    """Credential-bearing standalone search configuration."""

    api_key: str
    base_url: str
    headers: dict[str, str]
    session_id: str
    model: str
    settings: dict[str, object]


def responses_lite_web_search_enabled(
    *,
    provider: LLMProvider,
    responses_lite: bool,
    builtin_tools: list[BuiltinToolSpec],
) -> bool:
    """Return whether ChatGPT Responses Lite needs client-executed search."""
    return (
        provider == LLMProvider.CHATGPT_OAUTH
        and responses_lite
        and any(tool.name == _TOOL_NAME for tool in builtin_tools)
    )


def without_hosted_web_search(
    builtin_tools: list[BuiltinToolSpec],
) -> list[BuiltinToolSpec]:
    """Remove web search after replacing it with a client-executed tool."""
    return [tool for tool in builtin_tools if tool.name != _TOOL_NAME]


def create_chatgpt_web_search_tool(
    *,
    credential_kwargs: Mapping[str, object],
    session_id: str,
    model: str,
    builtin_config: Mapping[str, object],
    transport: httpx.AsyncBaseTransport | None,
) -> FunctionTool:
    """Create a Responses Lite standalone web-search function tool."""
    config = _build_config(
        credential_kwargs=credential_kwargs,
        session_id=session_id,
        model=model,
        builtin_config=builtin_config,
    )

    async def execute(arguments: str) -> str:
        commands = _parse_commands(arguments)
        body: dict[str, object] = {
            "id": config.session_id,
            "model": config.model,
            "commands": commands,
            "settings": config.settings,
            "max_output_tokens": _SEARCH_MAX_OUTPUT_TOKENS,
        }
        try:
            async with httpx.AsyncClient(
                base_url=f"{config.base_url.rstrip('/')}/",
                headers={
                    **config.headers,
                    "Authorization": f"Bearer {config.api_key}",
                    "version": CHATGPT_OAUTH_PROTOCOL_VERSION,
                },
                timeout=_SEARCH_TIMEOUT_SECONDS,
                transport=transport,
            ) as client:
                response = await client.post(_SEARCH_PATH, json=body)
                response.raise_for_status()
        except httpx.HTTPError:
            raise FunctionToolError("Web search request failed.") from None
        try:
            payload = response.json()
        except json.JSONDecodeError:
            raise FunctionToolError(
                "Web search returned an invalid response."
            ) from None
        if not isinstance(payload, dict) or not isinstance(payload.get("output"), str):
            raise FunctionToolError("Web search returned an invalid response.")
        return payload["output"]

    return FunctionTool(
        spec=FunctionToolSpec(
            name=_TOOL_NAME,
            description=_WEB_SEARCH_DESCRIPTION,
            input_schema=_WEB_SEARCH_SCHEMA,
        ),
        handler=execute,
    )


def _build_config(
    *,
    credential_kwargs: Mapping[str, object],
    session_id: str,
    model: str,
    builtin_config: Mapping[str, object],
) -> ChatGPTWebSearchConfig:
    """Validate credentials and map semantic tool config to search settings."""
    api_key = credential_kwargs.get("api_key")
    base_url = credential_kwargs.get("base_url") or credential_kwargs.get("api_base")
    raw_headers = credential_kwargs.get("extra_headers")
    if not isinstance(api_key, str) or not api_key:
        raise ValueError("ChatGPT web search requires an access token")
    if not isinstance(base_url, str) or not base_url:
        raise ValueError("ChatGPT web search requires a base URL")
    if raw_headers is None:
        headers: dict[str, str] = {}
    elif isinstance(raw_headers, dict) and all(
        isinstance(key, str) and isinstance(value, str)
        for key, value in raw_headers.items()
    ):
        headers = dict(raw_headers)
    else:
        raise TypeError("ChatGPT web search headers must be dict[str, str]")
    settings = dict(builtin_config)
    settings.setdefault("allowed_callers", ["direct"])
    settings.setdefault("external_web_access", True)
    return ChatGPTWebSearchConfig(
        api_key=api_key,
        base_url=base_url,
        headers=headers,
        session_id=session_id,
        model=model,
        settings=settings,
    )


def _parse_commands(arguments: str) -> dict[str, object]:
    """Validate the client-tool command envelope without retaining its contents."""
    try:
        commands = json.loads(arguments)
    except json.JSONDecodeError:
        raise FunctionToolError("Web search arguments must be valid JSON.") from None
    if not isinstance(commands, dict) or not all(
        isinstance(key, str) and key in _ALLOWED_COMMANDS for key in commands
    ):
        raise FunctionToolError("Web search arguments contain unsupported commands.")
    return commands
