"""Deterministic Slack Work presence reconciliation tests."""

import datetime
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Literal
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from azents.rdb.session_capabilities import ReadOnlySession, ReadSession, WriteSession
from azents.repos.external_channel.data import SlackWorkPresenceTarget
from azents.repos.external_channel.repository import ExternalChannelRepository
from azents.repos.external_channel.slack_presence_operations import (
    SlackPresenceOperationRepository,
)
from azents.services.external_channel.slack_presence import SlackPresenceOutcome
from azents.services.external_channel.slack_presence_manager import (
    SlackPresenceKey,
    SlackWorkPresenceManagerService,
    _ObservedPresence,
    _presence_key,
)

_NOW = datetime.datetime(2026, 8, 29, tzinfo=datetime.UTC)


def _target(
    *,
    kind: Literal["channel_loading", "thread_agent"] = "channel_loading",
    desired_state: Literal["processing", "idle"] = "processing",
    work_cycle_id: str = "work-1",
    status_text: str | None = "Investigating…",
) -> SlackWorkPresenceTarget:
    return SlackWorkPresenceTarget(
        binding_id="binding-1",
        work_cycle_id=work_cycle_id,
        kind=kind,
        desired_state=desired_state,
        channel_id="C1",
        thread_ts="1721600000.000100",
        initiator_user_id="U1" if desired_state == "processing" else None,
        status_text=status_text if desired_state == "processing" else None,
        agent_name="Research Agent",
        customize_messages=True,
    )


def _service(client: AsyncMock) -> SlackWorkPresenceManagerService:
    return SlackWorkPresenceManagerService(
        operations=MagicMock(spec=SlackPresenceOperationRepository),
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
    observed: dict[SlackPresenceKey, _ObservedPresence] = {}

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
    observed: dict[SlackPresenceKey, _ObservedPresence] = {}

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
    observed: dict[SlackPresenceKey, _ObservedPresence] = {}

    await service._reconcile(
        connection_id="connection-1",
        bot_token="xoxb-secret",
        targets=(target,),
        observed=observed,
        now=_NOW,
    )

    assert observed == {}


async def test_presence_read_scope_closes_before_provider_projection() -> None:
    """The actual operation owns its read scope before Slack SDK work starts."""
    open_scopes = 0
    target = _target()

    class TargetsRepository(ExternalChannelRepository):
        async def list_owned_slack_work_presence_targets(
            self,
            session: ReadSession,
            *,
            connection_id: str,
            lease_owner: str,
            required_configuration_generation: int,
            now: datetime.datetime,
        ) -> tuple[SlackWorkPresenceTarget, ...] | None:
            assert open_scopes == 1
            assert isinstance(session, ReadOnlySession)
            assert (connection_id, lease_owner, required_configuration_generation) == (
                "connection-1",
                "manager-1",
                2,
            )
            del now
            return (target,)

    @asynccontextmanager
    async def reads() -> AsyncIterator[ReadSession]:
        nonlocal open_scopes
        open_scopes += 1
        try:
            yield ReadOnlySession(AsyncSession())
        finally:
            open_scopes -= 1

    @asynccontextmanager
    async def forbidden_writes() -> AsyncIterator[WriteSession]:
        raise AssertionError("Target projection must use its independent read scope")
        yield

    async def set_presence(**_kwargs: object) -> SlackPresenceOutcome:
        assert open_scopes == 0
        return SlackPresenceOutcome(status="delivered", error_kind=None)

    client = AsyncMock()
    client.set_presence.side_effect = set_presence
    service = _service(client)
    service.operations = SlackPresenceOperationRepository(
        read_session_manager=reads,
        write_session_manager=forbidden_writes,
        repository=TargetsRepository(),
    )
    targets = await service._load_targets(
        connection_id="connection-1",
        configuration_generation=2,
    )
    assert targets == (target,)
    await service._reconcile(
        connection_id="connection-1",
        bot_token="synthetic-token",
        targets=targets,
        observed={},
        now=_NOW,
    )
    assert open_scopes == 0
