"""Signed Discord conversation-settings component scope tests."""

import datetime
from collections.abc import Callable

import pytest

from azents.core.enums import (
    ExternalChannelConversationLocation,
    ExternalChannelResponseMode,
)
from azents.services.external_channel.discord_settings_scope import (
    DiscordAccountLinkScope,
    DiscordModelSettingsScope,
    DiscordSettingsScope,
    build_discord_account_link_custom_id,
    build_discord_model_settings_custom_id,
    build_discord_settings_custom_id,
    parse_discord_account_link_custom_id,
    parse_discord_model_settings_custom_id,
    parse_discord_settings_custom_id,
    settings_selected_location,
    settings_selected_response_mode,
)

_UPDATED_AT = datetime.datetime(2026, 8, 1, tzinfo=datetime.UTC)
_ORIGIN_INTERACTION_ID = "01a03c28f6137b60b35e68ba50ce5319"
_BINDING_ID = "01a03bfcc50a7891a94d3328bdbd88bf"
_DRAFT_ID = "01a03bfcc50a7891a94d3328bdbd8901"


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
        action="parent_response_mode",
        origin_interaction_id="interaction-1",
        setting_id="setting-1",
        settings_generation=3,
    )

    assert len(custom_id) <= 100
    assert parse_discord_settings_custom_id(
        custom_id=custom_id,
        secret="secret",
    ) == DiscordSettingsScope(
        action="parent_response_mode",
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
        action="thread_response_mode",
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
    ("value", "expected"),
    [
        ("channel", ExternalChannelConversationLocation.CHANNEL),
        ("threads", ExternalChannelConversationLocation.THREADS),
        ("invalid", None),
        (None, None),
    ],
)
def test_settings_location_select_values_are_closed(
    value: str | None,
    expected: ExternalChannelConversationLocation | None,
) -> None:
    """Map only the two provider-visible parent location values."""
    assert settings_selected_location(value) is expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("mention_only", ExternalChannelResponseMode.MENTION_ONLY),
        ("all_messages", ExternalChannelResponseMode.ALL_MESSAGES),
        ("invalid", None),
        (None, None),
    ],
)
def test_settings_response_mode_select_values_are_closed(
    value: str | None,
    expected: ExternalChannelResponseMode | None,
) -> None:
    """Map only the two provider-visible response-mode values."""
    assert settings_selected_response_mode(value) is expected


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
            action="thread_response_mode",
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


def test_account_link_scopes_round_trip_without_account_authority() -> None:
    """Sign only opaque origin locators for start and code-entry actions."""
    start = build_discord_account_link_custom_id(
        secret="secret",
        action="start",
        origin_interaction_id="interaction-1",
        origin_id=None,
    )
    enter = build_discord_account_link_custom_id(
        secret="secret",
        action="enter_code",
        origin_interaction_id=None,
        origin_id="origin-1",
    )

    assert parse_discord_account_link_custom_id(
        custom_id=start,
        secret="secret",
    ) == DiscordAccountLinkScope(
        action="start",
        origin_interaction_id="interaction-1",
        origin_id=None,
    )
    assert parse_discord_account_link_custom_id(
        custom_id=enter,
        secret="secret",
    ) == DiscordAccountLinkScope(
        action="enter_code",
        origin_interaction_id=None,
        origin_id="origin-1",
    )
    assert len(start) <= 100
    assert len(enter) <= 100


def test_model_scope_round_trips_opaque_draft_and_page_only() -> None:
    """Keep model labels and permissions outside Discord custom IDs."""
    custom_id = build_discord_model_settings_custom_id(
        secret="secret",
        action="select_execution",
        draft_id=_DRAFT_ID,
        offset=20,
        selection_fingerprint=None,
    )

    assert parse_discord_model_settings_custom_id(
        custom_id=custom_id,
        secret="secret",
    ) == DiscordModelSettingsScope(
        action="select_execution",
        draft_id=_DRAFT_ID,
        offset=20,
        selection_fingerprint=None,
    )
    assert len(custom_id) <= 100
    assert "model" not in custom_id


@pytest.mark.parametrize(
    ("builder", "parser"),
    [
        (
            lambda: build_discord_account_link_custom_id(
                secret="secret",
                action="enter_code",
                origin_interaction_id=None,
                origin_id="origin-1",
            ),
            parse_discord_account_link_custom_id,
        ),
        (
            lambda: build_discord_model_settings_custom_id(
                secret="secret",
                action="apply",
                draft_id=_DRAFT_ID,
                offset=0,
                selection_fingerprint="0123456789abcdef",
            ),
            parse_discord_model_settings_custom_id,
        ),
    ],
)
def test_private_settings_scopes_reject_tampering(
    builder: Callable[[], str],
    parser: Callable[..., object],
) -> None:
    """A copied private control cannot be modified into another locator."""
    custom_id = builder()
    fields = custom_id.split(":")
    fields[-1] = ("A" if fields[-1][0] != "A" else "B") + fields[-1][1:]

    with pytest.raises(ValueError, match="scope is invalid"):
        parser(custom_id=":".join(fields), secret="secret")
