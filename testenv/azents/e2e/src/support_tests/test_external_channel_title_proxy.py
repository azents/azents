"""Deterministic External Channel automatic-title proxy tests."""

import json
from pathlib import Path

from support import image_generation_openai_proxy as proxy


def test_discord_title_request_match_is_specific() -> None:
    """Only the Discord Gateway title prompt activates provider synchronization."""
    request: dict[str, object] = {
        "messages": [
            {
                "role": "system",
                "content": (
                    "<task>Create a brief title from the request so the user can "
                    "find it later.</task>"
                ),
            },
            {
                "role": "user",
                "content": "<@&350> Private Discord Gateway invocation",
            },
        ]
    }

    assert proxy.is_external_channel_discord_title_request(request)
    assert not proxy.is_external_channel_discord_title_request(
        {
            "messages": [
                {"role": "system", "content": "You are a normal assistant."},
                {
                    "role": "user",
                    "content": "<@&350> Private Discord Gateway invocation",
                },
            ]
        }
    )


def test_discord_title_response_preserves_the_existing_structured_fixture() -> None:
    """Return the same structured title without an upstream proxy round trip."""
    fixture_path = (
        Path(proxy.__file__).parent / "aimock_fixtures" / "agents_md_loader.json"
    )
    fixture_document = json.loads(fixture_path.read_text())
    matching_fixture_responses = [
        fixture["response"]["content"]
        for fixture in fixture_document["fixtures"]
        if fixture["match"]
        == {
            "endpoint": "chat",
            "systemMessage": "Create a brief title from the request",
        }
    ]

    assert matching_fixture_responses == [
        proxy._EXTERNAL_CHANNEL_DISCORD_TITLE_RESPONSE
    ]
    assert json.loads(proxy._EXTERNAL_CHANNEL_DISCORD_TITLE_RESPONSE) == {
        "title": "Upload session initialized."
    }


def test_slack_response_mode_title_request_match_is_specific() -> None:
    """Only the response-mode title prompt uses the local deterministic response."""
    request: dict[str, object] = {
        "instructions": (
            "<task>Create a brief title from the request so the user can "
            "find it later.</task>"
        ),
        "input": [
            {
                "role": "user",
                "content": (
                    "Create a title from this request:\n"
                    "Initial response-mode invocation"
                ),
            }
        ],
    }

    assert proxy.is_external_channel_slack_response_mode_title_request(request)
    assert not proxy.is_external_channel_slack_response_mode_title_request(
        {
            **request,
            "input": [
                {
                    "role": "user",
                    "content": (
                        "Create a title from this request:\n"
                        "Another External Channel invocation"
                    ),
                }
            ],
        }
    )


def test_provider_title_retry_fixture_honors_both_output_modes() -> None:
    """Keep the retry failure and emit an envelope matching the captured mode."""
    fixture_path = (
        Path(proxy.__file__).parent / "aimock_fixtures" / "agents_md_loader.json"
    )
    document = json.loads(fixture_path.read_text())
    attempts = {
        fixture["match"]["sequenceIndex"]: fixture["response"]
        for fixture in document["fixtures"]
        if fixture["match"].get("userMessage") == "Provider title retry"
        and fixture["match"].get("systemMessage")
        == "Create a brief title from the request"
    }
    assert attempts[0]["status"] == 429
    assert attempts[0]["error"]["type"] == "rate_limit_error"
    assert json.loads(attempts[1]["content"]) == {
        "title": "Provider title retry recovered"
    }
    plain_instruction = (
        "Return only the title as plain text without JSON, labels, quotes"
    )
    plain = [
        fixture
        for fixture in document["fixtures"]
        if fixture["match"].get("userMessage") == "Provider title retry"
        and fixture["match"].get("systemMessage") == plain_instruction
    ]
    assert len(plain) == 2
    assert [fixture["match"]["sequenceIndex"] for fixture in plain] == [0, 1]
    assert plain[0]["response"]["status"] == 429
    assert plain[1]["response"]["content"] == "Provider title retry recovered"
    assert {
        key: value for key, value in plain[0]["match"].items() if key != "sequenceIndex"
    } == {
        key: value for key, value in plain[1]["match"].items() if key != "sequenceIndex"
    }
    structured = next(
        fixture
        for fixture in document["fixtures"]
        if fixture["match"].get("userMessage") == "Provider title retry"
        and fixture["match"].get("systemMessage")
        == "Create a brief title from the request"
        and fixture["match"].get("sequenceIndex") == 1
    )
    structured_first = next(
        fixture
        for fixture in document["fixtures"]
        if fixture["match"].get("userMessage") == "Provider title retry"
        and fixture["match"].get("systemMessage")
        == "Create a brief title from the request"
        and fixture["match"].get("sequenceIndex") == 0
    )
    assert document["fixtures"].index(plain[1]) < document["fixtures"].index(
        structured_first
    )
    assert document["fixtures"].index(structured_first) < document["fixtures"].index(
        structured
    )
    known_unsupported = [
        fixture
        for fixture in document["fixtures"]
        if fixture["match"].get("userMessage") == "Structured title fallback"
        and fixture["match"].get("systemMessage") is not None
    ]
    assert len(known_unsupported) == 1
    assert known_unsupported[0]["match"]["systemMessage"] == plain_instruction
    assert "error" not in known_unsupported[0]["response"]
