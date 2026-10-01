"""Faithful Discord missing-target error codes without network fixtures."""

from typing import NamedTuple

import pytest

from support import discord_provider_fake as fake


class _HandlerFixture(NamedTuple):
    handler: fake.DiscordHTTPHandler
    state: fake.FakeState
    responses: list[tuple[int, dict[str, object] | None]]


def _handler(
    monkeypatch: pytest.MonkeyPatch,
) -> _HandlerFixture:
    """Capture actual SDK handler responses without opening a listener."""
    state = fake.FakeState()
    handler = fake.DiscordHTTPHandler.__new__(fake.DiscordHTTPHandler)
    handler.command = "POST"
    responses: list[tuple[int, dict[str, object] | None]] = []
    monkeypatch.setattr(handler, "state", state)
    monkeypatch.setattr(
        handler,
        "_json_response",
        lambda status, payload, headers=None: responses.append((status, payload)),
    )
    return _HandlerFixture(handler=handler, state=state, responses=responses)


@pytest.mark.parametrize("operation", ["update_message", "delete_message"])
def test_absent_message_mutation_returns_unknown_message_code(
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
) -> None:
    """A known absent message is not represented as an ambiguous generic 404."""
    handler, state, responses = _handler(monkeypatch)
    handler._sdk_message_mutation(
        operation,
        {
            "guild_id": state.guild_id,
            "channel_id": "400000000000000001",
            "message_id": "500000000000000001",
        },
    )
    assert responses == [(404, {"message": "Unknown Message", "code": 10008})]


def test_absent_message_projection_returns_unknown_message_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fetching a missing message carries Discord's message-specific identity."""
    handler, state, responses = _handler(monkeypatch)
    handler._sdk_message_projection(
        {
            "guild_id": state.guild_id,
            "channel_id": "400000000000000001",
            "message_id": "500000000000000001",
        }
    )
    assert responses == [(404, {"message": "Unknown Message", "code": 10008})]


def test_absent_nonsynthetic_root_returns_unknown_message_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A missing root message does not claim that its parent channel is absent."""
    handler, state, responses = _handler(monkeypatch)
    state.allow_synthetic_roots = False
    handler._sdk_fetch_root_thread(
        {
            "guild_id": state.guild_id,
            "parent_channel_id": "400000000000000001",
            "root_message_id": "500000000000000001",
        }
    )
    assert responses == [(404, {"message": "Unknown Message", "code": 10008})]


@pytest.mark.parametrize("operation", ["fetch_thread", "update_thread_name"])
def test_absent_thread_returns_unknown_channel_code(
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
) -> None:
    """Missing thread-channel targets cannot be classified as missing messages."""
    handler, state, responses = _handler(monkeypatch)
    handler._sdk_thread_title(
        operation,
        {
            "guild_id": state.guild_id,
            "channel_id": "400000000000000001",
            "name": "Updated thread",
        },
    )
    assert responses == [(404, {"message": "Unknown Channel", "code": 10003})]


@pytest.mark.parametrize(
    ("scenario", "expected"),
    [
        ("not_found", {"message": "Not found."}),
        ("message_not_found", {"message": "Unknown Message", "code": 10008}),
    ],
)
def test_controlled_not_found_preserves_generic_ambiguity(
    monkeypatch: pytest.MonkeyPatch,
    scenario: str,
    expected: dict[str, object],
) -> None:
    """Only the explicit missing-message scenario grants confirmed identity."""
    handler, _, responses = _handler(monkeypatch)
    assert handler._controlled_response(scenario) is True
    assert responses == [(404, expected)]


def test_configured_generic_404_on_existing_message_has_no_message_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A controlled rejection cannot turn an existing message into confirmed loss."""
    handler, state, responses = _handler(monkeypatch)
    state.configure({"api_scenarios": {"update_message": "not_found"}})
    channel_id = "400000000000000001"
    created = state.create_message(channel_id=channel_id, nonce=None)
    handler._sdk_message_mutation(
        "update_message",
        {
            "guild_id": state.guild_id,
            "channel_id": channel_id,
            "message_id": created.message_id,
        },
    )
    assert responses == [(404, {"message": "Not found."})]
    assert state.message_exists(channel_id=channel_id, message_id=created.message_id)
