"""Shortcut source interaction-state materialization tests."""

import datetime
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any, cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    ExternalChannelAppMode,
    ExternalChannelInteractionStatus,
    ExternalChannelInteractionType,
    ExternalChannelProvider,
    ExternalChannelResourceStatus,
)
from azents.rdb.session import SessionManager
from azents.repos.external_channel.data import (
    ExternalChannelInteraction,
    ExternalChannelTrigger,
)
from azents.repos.external_channel.repository import ExternalChannelRepository
from azents.services.external_channel.selector_state import (
    projection_with_selector_state,
    selector_state_from_interaction,
)
from azents.services.external_channel.shortcut_source import (
    ExternalChannelShortcutSourceService,
)
from azents.services.external_channel.slack_events import SlackEventExcluded

_NOW = datetime.datetime(2026, 7, 31, tzinfo=datetime.UTC)


class _Session:
    def __init__(self) -> None:
        self.commit_count = 0

    async def commit(self) -> None:
        self.commit_count += 1


class _Repository:
    """Narrow double with no message, admission, Session, mailbox, or wake API."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.provider = ExternalChannelProvider.SLACK
        self.resource_creates: list[object] = []
        self.position_creates: list[object] = []
        self.resource_status = ExternalChannelResourceStatus.ACTIVE
        self.interaction = ExternalChannelInteraction.model_construct(
            id="interaction-1",
            connection_id="connection-1",
            interaction_type=ExternalChannelInteractionType.SHORTCUT,
            principal_id="principal-actor",
            projection={},
            status=ExternalChannelInteractionStatus.PROCESSING,
            expires_at=_NOW + datetime.timedelta(minutes=10),
        )

    async def create_conversation_position_idempotent(
        self,
        session: object,
        create: object,
    ) -> object:
        del session
        self.calls.append("position")
        self.position_creates.append(create)
        return SimpleNamespace(id="position-1", read_through_position=None)

    async def lock_interaction(
        self,
        session: object,
        *,
        interaction_id: str,
    ) -> ExternalChannelInteraction | None:
        del session
        self.calls.append("interaction")
        return self.interaction if interaction_id == self.interaction.id else None

    async def lock_connection_for_routing(
        self,
        session: object,
        *,
        connection_id: str,
    ) -> object | None:
        del session
        self.calls.append("connection")
        if connection_id != "connection-1":
            return None
        return SimpleNamespace(
            id="connection-1",
            app_mode=ExternalChannelAppMode.MULTI,
            provider=self.provider,
            provider_bot_user_id="UBOT",
        )

    async def create_resource_idempotent(
        self,
        session: object,
        create: object,
    ) -> object:
        del session
        self.calls.append("resource_create")
        self.resource_creates.append(create)
        return SimpleNamespace(id="resource-1")

    async def lock_resource(
        self,
        session: object,
        *,
        resource_id: str,
    ) -> object | None:
        del session
        self.calls.append("resource_lock")
        if resource_id != "resource-1":
            return None
        return SimpleNamespace(id=resource_id, status=self.resource_status)

    async def lock_connected_binding_by_resource(
        self,
        session: object,
        *,
        resource_id: str,
    ) -> None:
        del session
        self.calls.append("binding")
        assert resource_id == "resource-1"
        return None

    async def replace_interaction_projection(
        self,
        session: object,
        *,
        interaction_id: str,
        projection: dict[str, object],
    ) -> ExternalChannelInteraction | None:
        del session
        self.calls.append("projection_replace")
        if interaction_id != self.interaction.id:
            return None
        self.interaction = self.interaction.model_copy(
            update={"projection": projection}
        )
        return self.interaction


def _source_event() -> ExternalChannelTrigger:
    return ExternalChannelTrigger(
        connection_id="connection-1",
        provider_event_id="shortcut-http-1",
        transport_envelope_id=None,
        event_type="app_mention",
        provider_app_id="A-1",
        provider_tenant_id="T-1",
        provider_enterprise_id=None,
        resource_correlation_key="C-1:100.0001",
        envelope={
            "event": {
                "type": "app_mention",
                "channel": "C-1",
                "user": "U-source",
                "ts": "100.0001",
                "thread_ts": "100.0001",
                "text": "source text",
            }
        },
        provider_occurred_at=_NOW,
        received_at=_NOW,
    )


def _discord_source_event() -> ExternalChannelTrigger:
    return ExternalChannelTrigger(
        connection_id="connection-1",
        provider_event_id="discord-interaction-source:interaction-1:100",
        transport_envelope_id=None,
        event_type="discord_message_create",
        provider_app_id="app-1",
        provider_tenant_id="guild-1",
        provider_enterprise_id=None,
        resource_correlation_key="guild-1:channel-1",
        envelope={
            "message": {
                "id": "100",
                "channel_id": "channel-1",
                "guild_id": "guild-1",
                "content": "source text",
                "author": {"id": "user-source"},
            }
        },
        provider_occurred_at=_NOW,
        received_at=_NOW,
    )


def _service(
    session: _Session,
    repository: _Repository,
) -> ExternalChannelShortcutSourceService:
    @asynccontextmanager
    async def session_manager() -> AsyncGenerator[AsyncSession, None]:
        yield cast(AsyncSession, session)

    return ExternalChannelShortcutSourceService(
        session_manager=cast(SessionManager[AsyncSession], session_manager),
        repository=cast(ExternalChannelRepository, repository),
    )


@pytest.mark.asyncio
async def test_shortcut_source_commits_content_free_selector_state() -> None:
    session = _Session()
    repository = _Repository()

    result = await _service(session, repository).ensure(
        shortcut_source_event=_source_event(),
        interaction_id="interaction-1",
        now=_NOW,
    )

    assert result.selector_interaction is not None
    state = selector_state_from_interaction(result.selector_interaction)
    assert state.connection_id == "connection-1"
    assert state.resource_id == "resource-1"
    assert state.principal_id == "principal-actor"
    assert state.conversation_position_id == "position-1"
    assert state.trigger_provider_message_key == "slack:T-1:C-1:100.0001"
    assert state.trigger_position == "00000000000000000100.000100"
    assert state.selected_route_id is None
    create = cast(Any, repository.resource_creates[0])
    assert create.labels["provider_event_type"] == "app_mention"
    assert session.commit_count == 1
    assert repository.calls == [
        "interaction",
        "connection",
        "position",
        "resource_create",
        "resource_lock",
        "binding",
        "projection_replace",
    ]


@pytest.mark.asyncio
async def test_shortcut_source_retry_reuses_the_same_interaction() -> None:
    session = _Session()
    repository = _Repository()
    service = _service(session, repository)

    first = await service.ensure(
        shortcut_source_event=_source_event(),
        interaction_id="interaction-1",
        now=_NOW,
    )
    second = await service.ensure(
        shortcut_source_event=_source_event(),
        interaction_id="interaction-1",
        now=_NOW,
    )

    assert first.selector_interaction is not None
    assert second.selector_interaction is not None
    assert first.selector_interaction.id == second.selector_interaction.id
    assert repository.calls.count("projection_replace") == 1
    assert session.commit_count == 2
    assert not any(
        forbidden in " ".join(repository.calls)
        for forbidden in (
            "message",
            "revision",
            "admission",
            "access_request",
            "binding_create",
            "session",
            "mailbox_item",
            "wake",
        )
    )


@pytest.mark.asyncio
async def test_shortcut_source_retry_preserves_selected_route() -> None:
    session = _Session()
    repository = _Repository()
    service = _service(session, repository)

    first = await service.ensure(
        shortcut_source_event=_source_event(),
        interaction_id="interaction-1",
        now=_NOW,
    )
    assert first.selector_interaction is not None
    selected_state = selector_state_from_interaction(
        first.selector_interaction
    ).model_copy(update={"selected_route_id": "route-1"})
    repository.interaction = repository.interaction.model_copy(
        update={
            "projection": projection_with_selector_state(
                repository.interaction.projection,
                selected_state,
            )
        }
    )

    repeated = await service.ensure(
        shortcut_source_event=_source_event(),
        interaction_id="interaction-1",
        now=_NOW,
    )

    assert repeated.selector_interaction is not None
    assert (
        selector_state_from_interaction(repeated.selector_interaction).selected_route_id
        == "route-1"
    )
    assert repository.calls.count("projection_replace") == 1


@pytest.mark.asyncio
async def test_shortcut_source_rejects_inactive_resource() -> None:
    repository = _Repository()
    repository.resource_status = ExternalChannelResourceStatus.DELETED

    with pytest.raises(SlackEventExcluded, match="unavailable"):
        await _service(_Session(), repository).ensure(
            shortcut_source_event=_source_event(),
            interaction_id="interaction-1",
            now=_NOW,
        )

    assert "binding" not in repository.calls
    assert "projection_replace" not in repository.calls


@pytest.mark.asyncio
async def test_discord_message_command_source_preserves_thread_identity() -> None:
    session = _Session()
    repository = _Repository()
    repository.provider = ExternalChannelProvider.DISCORD

    result = await _service(session, repository).ensure(
        shortcut_source_event=_discord_source_event(),
        interaction_id="interaction-1",
        now=_NOW,
    )

    assert result.selector_interaction is not None
    create = cast(Any, repository.resource_creates[0])
    assert create.provider_resource_key == "discord:guild-1:100"
    assert create.labels == {
        "provider": "discord",
        "provider_event_type": "discord_message_create",
        "guild_id": "guild-1",
        "source_channel_id": "channel-1",
        "channel_id": "channel-1",
        "thread_id": "100",
        "parent_channel_id": "channel-1",
        "root_message_id": "100",
    }
    position = cast(Any, repository.position_creates[0])
    assert position.provider_channel_id == "channel-1"
    assert position.provider_thread_key is None
    state = selector_state_from_interaction(result.selector_interaction)
    assert state.trigger_provider_message_key == "discord:guild-1:100"
    assert state.trigger_position == "00000000000000000100"
