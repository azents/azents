"""Shared LiteLLM Responses helper tests."""

from pytest import MonkeyPatch

import azents.engine.responses as responses_module
from azents.core.enums import LLMProvider
from azents.engine.responses import call_responses_model, extract_response_text


async def test_call_responses_model_builds_standard_payload(
    monkeypatch: MonkeyPatch,
) -> None:
    """Shared helper validates input and calls LiteLLM Responses consistently."""
    calls: list[dict[str, object]] = []

    async def fake_aresponses(**kwargs: object) -> object:
        calls.append(kwargs)
        return {"output_text": "Insurance option comparison"}

    monkeypatch.setattr(responses_module, "aresponses", fake_aresponses)

    response = await call_responses_model(
        provider=LLMProvider.ANTHROPIC,
        model="anthropic/test",
        credential_kwargs={},
        input_items=[{"role": "user", "content": "Compare two insurance options"}],
        instructions="Generate a title",
        stream=False,
        max_output_tokens=80,
    )

    assert await extract_response_text(response) == "Insurance option comparison"
    assert calls == [
        {
            "model": "anthropic/test",
            "input": [{"role": "user", "content": "Compare two insurance options"}],
            "instructions": "Generate a title",
            "stream": False,
            "max_output_tokens": 80,
            "text": {"format": {"type": "text"}, "verbosity": "low"},
            "custom_llm_provider": None,
            "store": None,
            "api_key": None,
            "api_base": None,
            "base_url": None,
        }
    ]


async def test_call_responses_model_uses_openai_compatible_options(
    monkeypatch: MonkeyPatch,
) -> None:
    """OpenAI-compatible providers use Responses endpoint conventions."""
    calls: list[dict[str, object]] = []

    async def fake_aresponses(**kwargs: object) -> object:
        calls.append(kwargs)
        return {"output_text": "Config review"}

    monkeypatch.setattr(responses_module, "aresponses", fake_aresponses)

    response = await call_responses_model(
        provider=LLMProvider.CHATGPT_OAUTH,
        model="gpt-5.1-codex",
        credential_kwargs={
            "api_key": "token",
            "base_url": "https://chatgpt.com/backend-api/codex",
            "api_base": "https://chatgpt.com/backend-api/codex",
        },
        input_items=[{"role": "user", "content": "look at @config.json"}],
        instructions="Generate a title",
        stream=False,
        max_output_tokens=80,
    )

    assert await extract_response_text(response) == "Config review"
    assert calls[0]["custom_llm_provider"] == "openai"
    assert calls[0]["store"] is False
    assert calls[0]["max_output_tokens"] is None
    assert calls[0]["api_key"] == "token"
    assert calls[0]["base_url"] == "https://chatgpt.com/backend-api/codex"
    assert calls[0]["api_base"] == "https://chatgpt.com/backend-api/codex"


async def test_extract_response_text_reads_response_output_text() -> None:
    """Output text extraction supports raw Responses dictionaries."""
    response = {
        "output": [
            {
                "type": "message",
                "content": [
                    {"type": "output_text", "text": "Insurance option comparison"}
                ],
            }
        ]
    }

    assert await extract_response_text(response) == "Insurance option comparison"
