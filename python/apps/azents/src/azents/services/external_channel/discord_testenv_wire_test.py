"""Deterministic fixture ingress validates once without narrowing compatibility."""

import pytest
from pydantic import ValidationError

from azents.services.external_channel.discord_testenv_wire import (
    AttachmentResult,
    CommandResult,
    GatewayAttempt,
    GatewayGuild,
    GatewayIgnoredDispatch,
    GatewayMessage,
    LoginResult,
    ThreadLookupResult,
)


@pytest.mark.parametrize("value", [None, False, 1, ""])
def test_required_identities_are_nonempty_strict_strings(value: object) -> None:
    with pytest.raises(ValidationError):
        LoginResult.model_validate({"bot_user_id": value})


@pytest.mark.parametrize("value", [True, "1", 1.0, None])
def test_command_kind_is_a_real_integer(value: object) -> None:
    with pytest.raises(ValidationError):
        CommandResult.model_validate({"id": "1", "name": "test", "type": value})


def test_optional_fields_and_unknown_extensions_keep_existing_contract() -> None:
    command = CommandResult.model_validate(
        {"id": "1", "name": "test", "type": 1, "description": {}, "future": True}
    )
    assert command.description is None
    assert ThreadLookupResult.model_validate({}).thread is None
    assert ThreadLookupResult.model_validate({"thread": None}).thread is None


@pytest.mark.parametrize("value", [True, -1, "4", 1.0])
def test_attachment_size_cannot_coerce_invalid_wire_values(value: object) -> None:
    with pytest.raises(ValidationError):
        AttachmentResult.model_validate(
            {
                "attachment_id": "a",
                "filename": "name",
                "size": value,
                "download_url": "https://example.test/file",
            }
        )


def test_gateway_decodes_known_dispatches_and_keeps_message_body_opaque() -> None:
    message = {"channel_id": "c", "mention_roles": ["r", 1], "future": {"x": 1}}
    attempt = GatewayAttempt.decode(
        {
            "scenario": "open",
            "dispatches": [
                {
                    "event_type": "GUILD_CREATE",
                    "payload": {
                        "channels": [None, {"id": "c", "name": "channel"}],
                        "roles": [{"id": "r", "tags": {"bot_id": "bot"}}],
                    },
                },
                {"event_type": "MESSAGE_CREATE", "payload": message},
                {"event_type": "FUTURE_EVENT", "payload": {"opaque": True}},
            ],
        }
    )
    guild, projected, extension = attempt.dispatches
    assert isinstance(guild, GatewayGuild)
    assert guild.channels == {"c": "channel"}
    assert guild.managed_roles == {"r": "bot"}
    assert isinstance(projected, GatewayMessage)
    assert projected.raw is message
    assert projected.channel_id == "c"
    assert projected.mention_roles == ("r",)
    assert isinstance(extension, GatewayIgnoredDispatch)


def test_reconnect_does_not_require_open_dispatch_shape() -> None:
    assert GatewayAttempt.decode({"scenario": "reconnect"}).dispatches == ()
