"""Signed Discord conversation-settings component scope tests."""

import datetime

import pytest

from azents.services.external_channel.discord_settings_scope import (
    DiscordSettingsScope,
    build_discord_settings_custom_id,
    parse_discord_settings_custom_id,
)

_UPDATED_AT = datetime.datetime(2026, 8, 1, tzinfo=datetime.UTC)
_ORIGIN_INTERACTION_ID = "01a03c28f6137b60b35e68ba50ce5319"
_BINDING_ID = "01a03bfcc50a7891a94d3328bdbd88bf"


def test_setup_settings_scope_round_trips_with_current_source_fences() -> None:
    """Authenticate the setup claim generation and source revision."""
    custom_id = build_discord_settings_custom_id(
        secret="secret",
        action="setup_threads",
        origin_interaction_id="interaction-1",
        setup_claim_id="claim-1",
        claim_generation=2,
        source_revision=4,
    )

    assert parse_discord_settings_custom_id(
        custom_id=custom_id,
        secret="secret",
    ) == DiscordSettingsScope(
        action="setup_threads",
        origin_interaction_id="interaction-1",
        setup_claim_id="claim-1",
        claim_generation=2,
        source_revision=4,
        setting_id=None,
        settings_generation=None,
        binding_id=None,
        binding_version=None,
    )


def test_parent_settings_scope_round_trips_with_current_generation() -> None:
    """Authenticate the durable command origin, setting identity, and generation."""
    custom_id = build_discord_settings_custom_id(
        secret="secret",
        action="parent_all_messages",
        origin_interaction_id="interaction-1",
        setting_id="setting-1",
        settings_generation=3,
    )

    assert len(custom_id) <= 100
    assert parse_discord_settings_custom_id(
        custom_id=custom_id,
        secret="secret",
    ) == DiscordSettingsScope(
        action="parent_all_messages",
        origin_interaction_id="interaction-1",
        setup_claim_id=None,
        claim_generation=None,
        source_revision=None,
        setting_id="setting-1",
        settings_generation=3,
        binding_id=None,
        binding_version=None,
    )


def test_thread_settings_scope_round_trips_with_binding_revision() -> None:
    """Authenticate one connected Binding and its compact revision fence."""
    custom_id = build_discord_settings_custom_id(
        secret="secret",
        action="thread_mention_only",
        origin_interaction_id=_ORIGIN_INTERACTION_ID,
        binding_id=_BINDING_ID,
        binding_updated_at=_UPDATED_AT,
    )

    scope = parse_discord_settings_custom_id(
        custom_id=custom_id,
        secret="secret",
    )

    assert len(custom_id) == 90
    assert scope.origin_interaction_id == _ORIGIN_INTERACTION_ID
    assert scope.binding_id == _BINDING_ID
    assert scope.binding_version is not None
    assert len(scope.binding_version) == 16


@pytest.mark.parametrize(
    ("origin_interaction_id", "binding_id"),
    [
        ("interaction-1", _BINDING_ID),
        (_ORIGIN_INTERACTION_ID, "binding-1"),
        (_ORIGIN_INTERACTION_ID.upper(), _BINDING_ID),
    ],
)
def test_thread_settings_scope_requires_canonical_internal_ids(
    origin_interaction_id: str,
    binding_id: str,
) -> None:
    """Reject thread scopes that cannot use the fixed compact identifier encoding."""
    with pytest.raises(ValueError, match="scope is invalid"):
        build_discord_settings_custom_id(
            secret="secret",
            action="thread_all_messages",
            origin_interaction_id=origin_interaction_id,
            binding_id=binding_id,
            binding_updated_at=_UPDATED_AT,
        )


@pytest.mark.parametrize("mutation", ["payload", "signature"])
def test_settings_scope_rejects_tampering(mutation: str) -> None:
    """Reject modified state before resolving or mutating a conversation."""
    custom_id = build_discord_settings_custom_id(
        secret="secret",
        action="setup_channel",
        origin_interaction_id="interaction-1",
        setup_claim_id="claim-1",
        claim_generation=1,
        source_revision=2,
    )
    fields = custom_id.split(":")
    if mutation == "payload":
        fields[1] = "st"
    else:
        fields[-1] = ("A" if fields[-1][-1] != "A" else "B") + fields[-1][1:]

    with pytest.raises(ValueError, match="scope is invalid"):
        parse_discord_settings_custom_id(
            custom_id=":".join(fields),
            secret="secret",
        )
