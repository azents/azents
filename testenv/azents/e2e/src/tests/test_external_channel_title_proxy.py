"""Deterministic External Channel automatic-title proxy tests."""

import json
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
