"""Discord HTTP interaction verification tests."""

import json

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from azents.core.enums import ExternalChannelInteractionType
from azents.services.external_channel.discord_interaction import (
    DiscordInteractionInvalidPayload,
    DiscordInteractionUnauthorized,
    discord_interaction_response_type,
    discord_interaction_type,
    parse_discord_interaction,
    verify_discord_interaction_signature,
)


def test_maps_supported_discord_interaction_types() -> None:
    """Discord interaction categories map only to supported canonical callbacks."""
    assert discord_interaction_type(2) is ExternalChannelInteractionType.SHORTCUT
    assert discord_interaction_type(3) is ExternalChannelInteractionType.BLOCK_ACTION
    assert discord_interaction_type(4) is ExternalChannelInteractionType.OPTIONS
    assert discord_interaction_type(5) is ExternalChannelInteractionType.VIEW_SUBMISSION
    assert discord_interaction_type(1) is None


def test_verifies_timestamp_prefixed_raw_body() -> None:
    """Valid signatures authenticate the exact raw JSON bytes."""
    private_key = Ed25519PrivateKey.generate()
    raw_body = b'{"id":"1","type":1,"application_id":"app"}'
    timestamp = "1721984000"
    signature = private_key.sign(timestamp.encode() + raw_body).hex()

    verify_discord_interaction_signature(
        raw_body=raw_body,
        timestamp=timestamp,
        signature=signature,
        public_key=private_key.public_key().public_bytes_raw().hex(),
    )


def test_rejects_tampered_raw_body() -> None:
    """Changing raw JSON after signing fails closed."""
    private_key = Ed25519PrivateKey.generate()
    signed_body = b'{"id":"1","type":1,"application_id":"app"}'
    timestamp = "1721984000"

    with pytest.raises(DiscordInteractionUnauthorized, match="invalid") as error:
        verify_discord_interaction_signature(
            raw_body=b'{"id":"2","type":1,"application_id":"app"}',
            timestamp=timestamp,
            signature=private_key.sign(timestamp.encode() + signed_body).hex(),
            public_key=private_key.public_key().public_bytes_raw().hex(),
        )
    assert error.value.failure_code == "discord_interaction_signature_invalid"


def test_classifies_missing_signature_headers_without_retaining_input() -> None:
    """Missing authentication headers expose one safe operational code."""
    private_key = Ed25519PrivateKey.generate()

    with pytest.raises(DiscordInteractionUnauthorized) as error:
        verify_discord_interaction_signature(
            raw_body=b'{"id":"1","type":1,"application_id":"app"}',
            timestamp=None,
            signature=None,
            public_key=private_key.public_key().public_bytes_raw().hex(),
        )

    assert error.value.failure_code == "discord_interaction_signature_headers_missing"


def test_parses_bounded_routing_facts() -> None:
    """Parser retains only minimal interaction routing facts."""
    envelope = parse_discord_interaction(
        json.dumps(
            {
                "id": "interaction-1",
                "type": 2,
                "application_id": "app-1",
                "guild_id": "guild-1",
                "channel_id": "channel-1",
                "member": {"user": {"id": "user-1"}},
                "token": "must-not-be-projected",
            }
        ).encode()
    )

    assert envelope.interaction_id == "interaction-1"
    assert envelope.guild_id == "guild-1"
    assert envelope.actor_user_id == "user-1"
    assert not hasattr(envelope, "token")


@pytest.mark.parametrize(
    ("interaction_type", "response_type"),
    [(2, 5), (3, 6), (4, 8), (5, 5)],
)
def test_maps_admitted_interactions_to_provider_acknowledgements(
    interaction_type: int,
    response_type: int,
) -> None:
    """Each supported interaction uses Discord's matching acknowledgement shape."""
    assert discord_interaction_response_type(interaction_type) == response_type


def test_rejects_invalid_routing_fields() -> None:
    """Malformed payloads do not produce a routeable envelope."""
    with pytest.raises(DiscordInteractionInvalidPayload, match="invalid routing"):
        parse_discord_interaction(b'{"id":1,"type":2,"application_id":"app"}')
