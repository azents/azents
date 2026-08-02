"""Provider-neutral Session presence delivery-target tests."""

from azents.core.external_channel_session_presence import (
    session_presence_payload,
    setup_required_payload,
)


def test_discord_parent_presence_targets_the_parent_channel_directly() -> None:
    """A parent Resource presence never carries a Discord thread target."""
    payload = session_presence_payload(
        {
            "provider": "discord",
            "guild_id": "111",
            "parent_channel_id": "222",
            "conversation_scope": "parent_channel",
            "thread_id": "must-not-be-used",
        },
        state="joined",
    )

    assert payload == {
        "control_kind": "session_presence",
        "control_version": 2,
        "presence_state": "joined",
        "guild_id": "111",
        "channel_id": "222",
        "conversation_scope": "parent_channel",
    }


def test_discord_thread_presence_retains_thread_provisioning_target() -> None:
    """A thread Resource presence retains its existing root-thread target."""
    payload = session_presence_payload(
        {
            "provider": "discord",
            "guild_id": "111",
            "parent_channel_id": "222",
            "root_message_id": "333",
            "thread_id": "333",
        },
        state="joined",
    )

    assert payload == {
        "control_kind": "session_presence",
        "control_version": 2,
        "presence_state": "joined",
        "guild_id": "111",
        "channel_id": "333",
        "conversation_scope": "thread",
        "thread_parent_channel_id": "222",
        "thread_root_message_id": "333",
    }


def test_discord_setup_targets_parent_without_provisioning_a_thread() -> None:
    """Setup choices remain in the parent channel until location selection."""
    payload = setup_required_payload(
        {
            "provider": "discord",
            "guild_id": "111",
            "source_channel_id": "222",
            "parent_channel_id": "222",
            "root_message_id": "333",
            "thread_id": "333",
        },
        setup_claim_id="claim-1",
        claim_generation=2,
        source_revision=4,
    )

    assert payload == {
        "control_kind": "setup_required",
        "control_version": 2,
        "setup_claim_id": "claim-1",
        "claim_generation": 2,
        "source_revision": 4,
        "guild_id": "111",
        "channel_id": "222",
        "conversation_scope": "parent_channel",
    }
