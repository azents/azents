"""External conversation foundation contract tests."""

import datetime

import pytest

from azents.core.enums import ExternalChannelConversationScopeKind
from azents.services.external_channel.conversation import (
    ExternalChannelConversationScope,
    ExternalChannelHistoryRange,
    ExternalChannelOperationDeadline,
)


def test_scope_digest_and_repr_do_not_expose_provider_identifiers() -> None:
    scope = ExternalChannelConversationScope(
        connection_id="connection-private",
        kind=ExternalChannelConversationScopeKind.THREAD,
        provider_channel_id="channel-private",
        provider_thread_key="thread-private",
    )

    assert len(scope.lock_digest) == 64
    assert scope.lock_digest == scope.lock_digest
    assert "connection-private" not in repr(scope)
    assert "channel-private" not in repr(scope)
    assert "thread-private" not in repr(scope)


def test_scope_requires_the_identity_shape_for_its_kind() -> None:
    with pytest.raises(ValueError, match="cannot have a thread key"):
        ExternalChannelConversationScope(
            connection_id="connection",
            kind=ExternalChannelConversationScopeKind.PARENT_CHANNEL,
            provider_channel_id="channel",
            provider_thread_key="thread",
        )

    with pytest.raises(ValueError, match="requires a provider thread key"):
        ExternalChannelConversationScope(
            connection_id="connection",
            kind=ExternalChannelConversationScopeKind.THREAD,
            provider_channel_id="channel",
            provider_thread_key=None,
        )


def test_deadline_requires_timezone_awareness_and_clamps_remaining_budget() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        ExternalChannelOperationDeadline(datetime.datetime(2026, 7, 29))

    deadline = ExternalChannelOperationDeadline(
        datetime.datetime(2026, 7, 29, 12, 0, tzinfo=datetime.UTC)
    )

    assert (
        deadline.remaining_seconds(
            now=datetime.datetime(2026, 7, 29, 11, 59, 58, tzinfo=datetime.UTC)
        )
        == 2.0
    )
    assert (
        deadline.remaining_seconds(
            now=datetime.datetime(2026, 7, 29, 12, 0, 1, tzinfo=datetime.UTC)
        )
        == 0.0
    )


def test_history_range_requires_the_exact_trigger_and_sanitized_counts() -> None:
    history = ExternalChannelHistoryRange(
        messages=("first", "trigger"),
        trigger="trigger",
        context_omitted=True,
        range_start_position="0001",
        trigger_position="0003",
        provider_request_count=2,
        scanned_message_count=3,
        elapsed_seconds=0.25,
        discord_root_thread_observation=None,
    )

    assert history.messages == ("first", "trigger")

    with pytest.raises(ValueError, match="exact trigger"):
        ExternalChannelHistoryRange(
            messages=("first",),
            trigger="trigger",
            context_omitted=False,
            range_start_position=None,
            trigger_position="0003",
            provider_request_count=1,
            scanned_message_count=1,
            elapsed_seconds=0.1,
            discord_root_thread_observation=None,
        )
