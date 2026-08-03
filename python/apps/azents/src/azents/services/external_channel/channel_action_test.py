"""Focused direct provider outcome tests for External Channel actions."""

from azents.services.external_channel.channel_action import (
    _provider_mutation_outcome,  # pyright: ignore[reportPrivateUsage]
)
from azents.services.external_channel.discord_delivery import DiscordDeliveryResult
from azents.services.external_channel.slack_events import SlackControlMessageResult


def test_slack_result_normalizes_without_persistent_identifiers() -> None:
    outcome = _provider_mutation_outcome(
        SlackControlMessageResult(
            status="failed",
            provider_message_key=None,
            error_kind="provider_rejected",
            error_summary="The provider rejected the request.",
        )
    )

    assert outcome.status == "failed"
    assert outcome.provider_message_key is None
    assert outcome.error_kind == "provider_rejected"


def test_discord_ambiguity_remains_unknown() -> None:
    outcome = _provider_mutation_outcome(
        DiscordDeliveryResult(
            status="unknown",
            provider_message_key=None,
            error_kind="provider_timeout",
            error_summary="The provider outcome is unknown.",
        )
    )

    assert outcome.status == "unknown"
    assert outcome.error_kind == "provider_timeout"
