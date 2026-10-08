"""Preserve retained participation identity predicates at typed label ingress."""

import datetime

import pytest

from azents.core.enums import (
    ExternalChannelProvider,
    ExternalChannelResourceStatus,
    ExternalChannelResourceType,
)
from azents.core.external_channel_participation import (
    ExternalChannelParticipationError,
    _ParticipationThreadLabels,
    _thread_conversation_scope,
    _thread_resource_matches,
)
from azents.repos.external_channel.data import ExternalChannelResource

_LABEL_VALUES: list[object] = [
    None,
    "",
    "thread",
    " ",
    "other",
    False,
    True,
    0,
    1,
    [],
    ["thread"],
    {},
    {"coordinate": "thread"},
]


def _resource(labels: dict[str, object] | None) -> ExternalChannelResource:
    return ExternalChannelResource(
        id="r" * 32,
        connection_id="connection",
        resource_type=ExternalChannelResourceType.THREAD,
        provider_resource_key="resource-key",
        labels=labels,
        status=ExternalChannelResourceStatus.ACTIVE,
        discovered_at=datetime.datetime(2026, 10, 6, tzinfo=datetime.UTC),
        created_at=datetime.datetime(2026, 10, 6, tzinfo=datetime.UTC),
        updated_at=datetime.datetime(2026, 10, 6, tzinfo=datetime.UTC),
        latest_activity_at=None,
        unavailable_at=None,
        deleted_at=None,
    )


@pytest.mark.parametrize("delivery", _LABEL_VALUES)
@pytest.mark.parametrize("fallback", _LABEL_VALUES)
def test_discord_fallback_matches_retained_predicate(
    delivery: object, fallback: object
) -> None:
    labels = {
        "provider": "discord",
        "guild_id": "guild",
        "delivery_channel_id": delivery,
        "thread_id": fallback,
        "uninspected_extension": {"preserved": True},
    }
    resource = _resource(labels)
    # The historical contract chooses by truthiness before checking string type.
    retained = delivery or fallback
    expected_match = retained == "thread"
    assert (
        _thread_resource_matches(
            connection_provider=ExternalChannelProvider.DISCORD,
            connection_id="connection",
            provider_tenant_id="guild",
            provider_thread_resource_key="discord:guild:thread",
            resource=resource,
        )
        is expected_match
    )
    if not isinstance(retained, str) or not retained:
        with pytest.raises(
            ExternalChannelParticipationError,
            match="External Channel thread settings are unavailable",
        ):
            _thread_conversation_scope(
                connection_id="connection",
                connection_provider=ExternalChannelProvider.DISCORD,
                provider_parent_channel_id="parent",
                resource=resource,
            )
    else:
        scope = _thread_conversation_scope(
            connection_id="connection",
            connection_provider=ExternalChannelProvider.DISCORD,
            provider_parent_channel_id="parent",
            resource=resource,
        )
        assert scope.provider_channel_id == retained
        assert scope.provider_thread_key == retained
    assert resource.labels == labels


@pytest.mark.parametrize("provider", ["discord", "slack", "", None, True, 1])
@pytest.mark.parametrize("guild", ["guild", "other", "", None, True, 1])
def test_discord_provider_and_guild_equality_remain_exact(
    provider: object, guild: object
) -> None:
    assert _thread_resource_matches(
        connection_provider=ExternalChannelProvider.DISCORD,
        connection_id="connection",
        provider_tenant_id="guild",
        provider_thread_resource_key="discord:guild:thread",
        resource=_resource(
            {"provider": provider, "guild_id": guild, "thread_id": "thread"}
        ),
    ) is (provider == "discord" and guild == "guild")


@pytest.mark.parametrize("thread", _LABEL_VALUES)
def test_slack_thread_scope_keeps_nonempty_string_predicate(thread: object) -> None:
    resource = _resource({"thread_ts": thread, "unknown": {"arbitrary": [True, 1]}})
    if not isinstance(thread, str) or not thread:
        with pytest.raises(ExternalChannelParticipationError):
            _thread_conversation_scope(
                connection_id="connection",
                connection_provider=ExternalChannelProvider.SLACK,
                provider_parent_channel_id="parent",
                resource=resource,
            )
    else:
        scope = _thread_conversation_scope(
            connection_id="connection",
            connection_provider=ExternalChannelProvider.SLACK,
            provider_parent_channel_id="parent",
            resource=resource,
        )
        assert scope.provider_channel_id == "parent"
        assert scope.provider_thread_key == thread


@pytest.mark.parametrize("labels", [None, {}, {"unknown": "ignored"}])
@pytest.mark.parametrize(
    "provider", [ExternalChannelProvider.SLACK, ExternalChannelProvider.DISCORD]
)
def test_missing_labels_remain_unavailable_for_scope(
    labels: dict[str, object] | None, provider: ExternalChannelProvider
) -> None:
    decoded = _ParticipationThreadLabels.decode(labels)
    assert decoded.slack_thread_key is None
    assert decoded.discord_thread_key is None
    with pytest.raises(ExternalChannelParticipationError):
        _thread_conversation_scope(
            connection_id="connection",
            connection_provider=provider,
            provider_parent_channel_id="parent",
            resource=_resource(labels),
        )


@pytest.mark.parametrize(
    "key", ["discord:guild:", "discord:guild:thread:extra", "discord:other:thread"]
)
def test_discord_canonical_resource_key_fencing_is_unchanged(key: str) -> None:
    assert not _thread_resource_matches(
        connection_provider=ExternalChannelProvider.DISCORD,
        connection_id="connection",
        provider_tenant_id="guild",
        provider_thread_resource_key=key,
        resource=_resource(
            {"provider": "discord", "guild_id": "guild", "thread_id": "thread"}
        ),
    )


def test_connection_type_and_slack_resource_identity_keep_fences() -> None:
    resource = _resource(None)
    assert _thread_resource_matches(
        connection_provider=ExternalChannelProvider.SLACK,
        connection_id="connection",
        provider_tenant_id=None,
        provider_thread_resource_key="resource-key",
        resource=resource,
    )
    for rejected in (
        resource.model_copy(update={"connection_id": "other"}),
        resource.model_copy(
            update={"resource_type": ExternalChannelResourceType.PARENT_CHANNEL}
        ),
        resource.model_copy(update={"provider_resource_key": "other"}),
    ):
        assert not _thread_resource_matches(
            connection_provider=ExternalChannelProvider.SLACK,
            connection_id="connection",
            provider_tenant_id=None,
            provider_thread_resource_key="resource-key",
            resource=rejected,
        )


@pytest.mark.parametrize("guild", [None, ""])
def test_missing_or_empty_discord_tenant_keeps_original_behavior(
    guild: str | None,
) -> None:
    assert _thread_resource_matches(
        connection_provider=ExternalChannelProvider.DISCORD,
        connection_id="connection",
        provider_tenant_id=guild,
        provider_thread_resource_key="discord::thread",
        resource=_resource(
            {"provider": "discord", "guild_id": guild, "thread_id": "thread"}
        ),
    ) is (guild == "")
