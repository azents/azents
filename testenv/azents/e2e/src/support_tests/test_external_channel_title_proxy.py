"""Deterministic External Channel automatic-title proxy tests."""

import json
import threading
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


def test_discord_title_barrier_holds_request_until_explicit_release() -> None:
    """The title response waits on an observable test-controlled boundary."""
    barrier = proxy._ExternalChannelDiscordTitleBarrier(timeout_seconds=1)
    barrier.arm()
    result: list[bool] = []
    waiter = threading.Thread(target=lambda: result.append(barrier.wait_for_release()))
    waiter.start()

    assert barrier.wait_until_reached(timeout=1)
    assert barrier.evidence() == {
        "armed": True,
        "reached": True,
        "released": False,
        "timed_out": False,
    }

    barrier.release()
    waiter.join(timeout=1)

    assert not waiter.is_alive()
    assert result == [True]
    assert barrier.evidence() == {
        "armed": True,
        "reached": True,
        "released": True,
        "timed_out": False,
    }


def test_discord_title_barrier_records_missing_arm_and_bounded_timeout() -> None:
    """Missing synchronization fails immediately and unreleased work times out."""
    barrier = proxy._ExternalChannelDiscordTitleBarrier(timeout_seconds=0.01)

    assert barrier.wait_for_release() is False

    barrier.arm()

    assert barrier.wait_for_release() is False
    assert barrier.evidence() == {
        "armed": True,
        "reached": True,
        "released": False,
        "timed_out": True,
    }
