"""ChatGPT Responses Lite standalone web-search tests."""

import json

import httpx
import pytest

from azents.core.enums import LLMProvider
from azents.engine.events.chatgpt_web_search import (
    create_chatgpt_web_search_tool,
    responses_lite_web_search_enabled,
    without_hosted_web_search,
)
from azents.engine.run.types import BuiltinToolSpec, FunctionToolError


def _credentials() -> dict[str, object]:
    return {
        "api_key": "synthetic-access-token",
        "base_url": "https://chatgpt.example/backend-api/codex",
        "extra_headers": {
            "originator": "azents",
            "ChatGPT-Account-Id": "account-id",
        },
    }


def test_responses_lite_web_search_replaces_only_chatgpt_hosted_tool() -> None:
    """Use standalone execution only for enabled ChatGPT Responses Lite search."""
    tools = [
        BuiltinToolSpec(name="web_search", config={}),
        BuiltinToolSpec(name="image_generation", config={}),
    ]

    assert responses_lite_web_search_enabled(
        provider=LLMProvider.CHATGPT_OAUTH,
        responses_lite=True,
        builtin_tools=tools,
    )
    assert not responses_lite_web_search_enabled(
        provider=LLMProvider.OPENAI,
        responses_lite=True,
        builtin_tools=tools,
    )
    assert not responses_lite_web_search_enabled(
        provider=LLMProvider.CHATGPT_OAUTH,
        responses_lite=False,
        builtin_tools=tools,
    )
    assert without_hosted_web_search(tools) == [tools[1]]


async def test_standalone_web_search_posts_codex_search_contract() -> None:
    """Execute model commands through the authenticated alpha/search endpoint."""
    captured: dict[str, object] = {}

    async def respond(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["authorization"] = request.headers.get("authorization")
        captured["version"] = request.headers.get("version")
        captured["account_id"] = request.headers.get("chatgpt-account-id")
        captured["body"] = json.loads((await request.aread()).decode())
        return httpx.Response(
            200,
            json={
                "encrypted_output": "must-not-be-retained",
                "output": "Search result with https://example.com/source",
            },
            request=request,
        )

    tool = create_chatgpt_web_search_tool(
        credential_kwargs=_credentials(),
        session_id="session-1",
        model="gpt-5.4",
        builtin_config={"search_context_size": "low"},
        transport=httpx.MockTransport(respond),
    )

    result = await tool.handler(
        json.dumps(
            {
                "search_query": [
                    {
                        "q": "OpenAI news",
                        "recency": 7,
                        "domains": ["openai.com"],
                    }
                ],
                "response_length": "short",
            }
        )
    )

    assert tool.spec.name == "web_search"
    assert captured == {
        "url": "https://chatgpt.example/backend-api/codex/alpha/search",
        "authorization": "Bearer synthetic-access-token",
        "version": "0.144.0",
        "account_id": "account-id",
        "body": {
            "id": "session-1",
            "model": "gpt-5.4",
            "commands": {
                "search_query": [
                    {
                        "q": "OpenAI news",
                        "recency": 7,
                        "domains": ["openai.com"],
                    }
                ],
                "response_length": "short",
            },
            "settings": {
                "search_context_size": "low",
                "allowed_callers": ["direct"],
                "external_web_access": True,
            },
            "max_output_tokens": 10_000,
        },
    }
    assert result == "Search result with https://example.com/source"


async def test_standalone_web_search_sanitizes_provider_failure() -> None:
    """Do not surface provider response bodies or credentials on search failure."""

    async def respond(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            500,
            text="provider secret body",
            request=request,
        )

    tool = create_chatgpt_web_search_tool(
        credential_kwargs=_credentials(),
        session_id="session-1",
        model="gpt-5.4",
        builtin_config={},
        transport=httpx.MockTransport(respond),
    )

    with pytest.raises(
        FunctionToolError,
        match="^Web search request failed\\.$",
    ) as exc:
        await tool.handler('{"search_query":[{"q":"hello"}]}')

    assert "provider secret body" not in str(exc.value)
    assert "synthetic-access-token" not in str(exc.value)


@pytest.mark.parametrize(
    "arguments",
    [
        "not-json",
        "[]",
        '{"unsupported":"value"}',
    ],
)
async def test_standalone_web_search_rejects_invalid_commands(arguments: str) -> None:
    """Reject malformed or unsupported command envelopes before HTTP dispatch."""
    called = False

    async def respond(request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(200, json={"output": "unexpected"}, request=request)

    tool = create_chatgpt_web_search_tool(
        credential_kwargs=_credentials(),
        session_id="session-1",
        model="gpt-5.4",
        builtin_config={},
        transport=httpx.MockTransport(respond),
    )

    with pytest.raises(FunctionToolError):
        await tool.handler(arguments)

    assert called is False
