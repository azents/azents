"""Deterministic External Channel automatic-title proxy tests."""

import json
from pathlib import Path
from typing import Self

import pytest

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


def test_discord_title_barrier_requires_committed_direct_create_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Release title output only for the exact second message-delivery barrier."""

    class _Response:
        def __enter__(self) -> Self:
            return self

        def __exit__(self, *_: object) -> None:
            return None

        @staticmethod
        def read() -> bytes:
            return json.dumps(
                {
                    "operation": "create_message",
                    "occurrence": 2,
                    "request_count": 2,
                    "reached": True,
                    "released": False,
                }
            ).encode()

    def urlopen(*_args: object, **_kwargs: object) -> _Response:
        return _Response()

    monkeypatch.setattr(
        proxy.urllib.request,
        "urlopen",
        urlopen,
    )

    assert proxy.wait_for_external_channel_discord_title_barrier()
