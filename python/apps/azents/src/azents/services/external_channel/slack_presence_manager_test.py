"""Deterministic Slack Work presence reconciliation tests."""

import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from azents.repos.external_channel.data import SlackWorkPresenceTarget
from azents.services.external_channel.slack_presence import SlackPresenceOutcome
from azents.services.external_channel.slack_presence_manager import (
    SlackWorkPresenceManagerService,
    _ObservedPresence,
    _presence_key,
)

_NOW = datetime.datetime(2026, 8, 29, tzinfo=datetime.UTC)


def _target(
    *,
    kind: str = "channel_loading",
    desired_state: str = "processing",
    work_cycle_id: str = "work-1",
    status_text: str | None = "Investigating…",
) -> SlackWorkPresenceTarget:
    return SlackWorkPresenceTarget(
        binding_id="binding-1",
        work_cycle_id=work_cycle_id,
        kind=kind,  # ty: ignore[invalid-argument-type] — parameters intentionally exercise the closed provider variants.
        desired_state=desired_state,  # ty: ignore[invalid-argument-type] — parameters intentionally exercise the closed provider variants.
        channel_id="C1",
        thread_ts="1721600000.000100",
        initiator_user_id="U1" if desired_state == "processing" else None,
        status_text=status_text if desired_state == "processing" else None,
        agent_name="Research Agent",
        customize_messages=True,
    )


def _service(client: AsyncMock) -> SlackWorkPresenceManagerService:
    return SlackWorkPresenceManagerService(
        session_manager=MagicMock(),
        repository=MagicMock(),
        credentials_codec=MagicMock(),
        presence_client=client,
        manager_id="manager-1",
        config=None,
    )


@pytest.mark.asyncio
async def test_active_channel_status_is_deduplicated_and_refreshed_before_expiry() -> (
    None
):
    """Unchanged loading is quiet until the configured provider refresh window."""
    client = AsyncMock()
    client.set_presence.return_value = SlackPresenceOutcome(
        status="delivered",
        error_kind=None,
    )
    service = _service(client)
    target = _target()
    observed: dict[tuple[str, str, str], _ObservedPresence] = {}

    await service._reconcile(
        connection_id="connection-1",
        bot_token="xoxb-secret",
        targets=(target,),
        observed=observed,
        now=_NOW,
    )
    await service._reconcile(
        connection_id="connection-1",
        bot_token="xoxb-secret",
        targets=(target,),
        observed=observed,
        now=_NOW + datetime.timedelta(seconds=89),
    )
    await service._reconcile(
        connection_id="connection-1",
        bot_token="xoxb-secret",
        targets=(target,),
        observed=observed,
        now=_NOW + datetime.timedelta(seconds=90),
    )

    assert client.set_presence.await_count == 2
    assert observed[_presence_key(target)].delivered_at == _NOW + datetime.timedelta(
        seconds=90
    )


@pytest.mark.asyncio
async def test_fresh_owner_applies_finished_thread_idle_once() -> None:
    """Retained finished Work clears a stale native Agent Session after handover."""
    client = AsyncMock()
    client.set_presence.return_value = SlackPresenceOutcome(
        status="delivered",
        error_kind=None,
    )
    service = _service(client)
    target = _target(
        kind="thread_agent",
        desired_state="idle",
        status_text=None,
    )
    observed: dict[tuple[str, str, str], _ObservedPresence] = {}

    await service._reconcile(
        connection_id="connection-1",
        bot_token="xoxb-secret",
        targets=(target,),
        observed=observed,
        now=_NOW,
    )
    await service._reconcile(
        connection_id="connection-1",
        bot_token="xoxb-secret",
        targets=(target,),
        observed=observed,
        now=_NOW + datetime.timedelta(seconds=5),
    )

    client.set_presence.assert_awaited_once_with(
        bot_token="xoxb-secret",
        target=target,
    )


@pytest.mark.asyncio
async def test_removed_active_target_is_cleared_from_observed_state() -> None:
    """Canonical target removal sends one idle projection and forgets the target."""
    client = AsyncMock()
    client.set_presence.return_value = SlackPresenceOutcome(
        status="delivered",
        error_kind=None,
    )
    service = _service(client)
    target = _target()
    key = _presence_key(target)
    observed = {
        key: _ObservedPresence(
            target=target,
            delivered_at=_NOW,
        )
    }

    await service._reconcile(
        connection_id="connection-1",
        bot_token="xoxb-secret",
        targets=(),
        observed=observed,
        now=_NOW + datetime.timedelta(seconds=5),
    )

    cleared = client.set_presence.await_args.kwargs["target"]
    assert cleared.desired_state == "idle"
    assert cleared.initiator_user_id is None
    assert cleared.status_text is None
    assert observed == {}


@pytest.mark.asyncio
async def test_failed_projection_remains_unobserved_for_later_retry() -> None:
    """A confirmed provider failure never masquerades as synchronized state."""
    client = AsyncMock()
    client.set_presence.return_value = SlackPresenceOutcome(
        status="failed",
        error_kind="feature_disabled",
    )
    service = _service(client)
    target = _target(kind="thread_agent")
    observed: dict[tuple[str, str, str], _ObservedPresence] = {}

    await service._reconcile(
        connection_id="connection-1",
        bot_token="xoxb-secret",
        targets=(target,),
        observed=observed,
        now=_NOW,
    )

    assert observed == {}
