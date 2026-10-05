"""Compatibility rules at the consumed Provider Effect metadata boundary."""

import dataclasses

import pytest

from azents.core.enums import (
    ExternalChannelAppMode,
    ExternalChannelDeliveryOperation,
    ExternalChannelProvider,
)
from azents.core.external_channel_effect_intent import (
    ProviderEffectIntent,
    ProviderReplyPart,
    RetainedDiscordDeliveryIdentity,
)
from azents.core.external_channel_provider_effect import ProviderTarget


def test_intent_omission_preserves_defaults_and_opaque_extensions() -> None:
    """Absent metadata differs from explicit null; extensions stay unconsumed."""
    payload: dict[str, object] = {"future_provider_extension": {"anything": True}}
    intent = ProviderEffectIntent.decode(payload)
    assert intent.part_ordinal == 0
    assert intent.tracker_host_kind == "standalone"
    assert intent.presence_state is None
    assert intent.work_id is None
    assert payload == {"future_provider_extension": {"anything": True}}
    assert "future_provider_extension" not in dataclasses.asdict(intent)


@pytest.mark.parametrize("value", [None, "0", 1.5, [], {}])
def test_explicit_invalid_part_never_becomes_the_omitted_default(value: object) -> None:
    """An explicitly supplied non-int remains ineligible for settlement."""
    assert ProviderEffectIntent.decode({"part_ordinal": value}).part_ordinal is None


@pytest.mark.parametrize("value", [0, 2, -1, True, False])
def test_integer_metadata_retains_existing_bool_and_integer_behavior(
    value: int,
) -> None:
    """Existing isinstance(int) behavior remains visible without coercion."""
    intent = ProviderEffectIntent.decode(
        {"part_ordinal": value, "desired_progress_revision": value}
    )
    assert intent.part_ordinal is value
    assert intent.desired_progress_revision is value


@pytest.mark.parametrize("value", ["", "id"])
def test_string_identity_decoding_does_not_invent_nonempty_rules(value: str) -> None:
    """Existing string-only application guards continue to admit empty strings."""
    intent = ProviderEffectIntent.decode(
        {
            "work_id": value,
            "access_request_id": value,
            "setup_claim_id": value,
            "provider_message_key": value,
            "control_kind": value,
        }
    )
    assert intent.work_id == value
    assert intent.access_request_id == value
    assert intent.setup_claim_id == value
    assert intent.provider_message_key == value
    assert intent.control_kind == value


@pytest.mark.parametrize("value", [None, 0, True, [], {}])
def test_non_string_identities_are_not_application_authority(value: object) -> None:
    """No string coercion turns a malformed field into a repository identity."""
    intent = ProviderEffectIntent.decode(
        {
            "work_id": value,
            "access_request_id": value,
            "setup_claim_id": value,
            "provider_message_key": value,
        }
    )
    assert intent.work_id is None
    assert intent.access_request_id is None
    assert intent.setup_claim_id is None
    assert intent.provider_message_key is None


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("joined", "joined"),
        ("left", "left"),
        ("other", None),
        (None, None),
        (False, None),
    ],
)
def test_presence_has_only_the_existing_two_states(
    value: object, expected: object
) -> None:
    assert (
        ProviderEffectIntent.decode({"presence_state": value}).presence_state
        == expected
    )


@pytest.mark.parametrize("value", [None, "", "standalone", "other", 1])
def test_tracker_host_fallback_and_scheduled_marker_remain_exact(value: object) -> None:
    intent = ProviderEffectIntent.decode(
        {"tracker_host_kind": value, "tracker_kind": value}
    )
    assert intent.tracker_host_kind == "standalone"
    assert intent.scheduled_tracker is False
    current = ProviderEffectIntent.decode(
        {"tracker_host_kind": "reply", "tracker_kind": "scheduled_task"}
    )
    assert current.tracker_host_kind == "reply"
    assert current.scheduled_tracker is True


def test_target_decodes_current_payload_then_detaches_immutable_fields() -> None:
    """Post-construction assembly stays valid without cached stale authority."""
    payload: dict[str, object] = {"access_request_id": "before", "part_ordinal": 1}
    target = ProviderTarget(
        operation=ExternalChannelDeliveryOperation.CONTROL_MESSAGE,
        binding_id=None,
        resource_id=None,
        connection_id="connection",
        provider=ExternalChannelProvider.SLACK,
        app_mode=ExternalChannelAppMode.MULTI,
        encrypted_credentials=None,
        provider_tenant_id=None,
        capabilities=None,
        provider_configuration=None,
        workspace_handle=None,
        agent_id=None,
        agent_session_id=None,
        agent_name=None,
        agent_avatar=None,
        request_payload=payload,
    )
    before = target.decode_intent()
    payload.update({"access_request_id": "after", "part_ordinal": None})
    after = target.decode_intent()
    assert before.access_request_id == "before"
    assert before.part_ordinal == 1
    assert after.access_request_id == "after"
    assert after.part_ordinal is None
    assert ProviderEffectIntent.__dataclass_params__.frozen is True


@pytest.mark.parametrize("value", [None, "", 0, False])
def test_retained_delivery_identity_requires_nonempty_string(value: object) -> None:
    retained = RetainedDiscordDeliveryIdentity.decode(
        {"provider": "discord", "delivery_channel_id": value}
    )
    assert retained.discord is True
    assert retained.delivery_channel_id is None


def test_retained_delivery_identity_keeps_marker_and_reusable_target() -> None:
    assert (
        RetainedDiscordDeliveryIdentity.decode(
            {"provider": "slack", "delivery_channel_id": "channel"}
        ).discord
        is False
    )
    assert (
        RetainedDiscordDeliveryIdentity.decode(
            {"provider": "discord", "delivery_channel_id": "channel"}
        ).delivery_channel_id
        == "channel"
    )


@pytest.mark.parametrize("scope", ["thread", "parent_channel"])
def test_reply_part_has_validated_scope_and_unmodified_provider_payload(
    scope: str,
) -> None:
    payload: dict[str, object] = {"conversation_scope": scope, "opaque": {"value": 1}}
    part = ProviderReplyPart.decode(payload)
    assert part.conversation_scope == scope
    assert part.payload is payload


@pytest.mark.parametrize("scope", [None, "", "other", 1])
def test_reply_part_rejects_an_invalid_internal_scope(scope: object) -> None:
    with pytest.raises(ValueError, match="conversation scope is invalid"):
        ProviderReplyPart.decode({"conversation_scope": scope})
