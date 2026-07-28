"""Deterministic Discord event-processor persistence tests."""

import datetime
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    ExternalChannelEventEligibilityState,
    ExternalChannelEventStatus,
    ExternalChannelHydrationStatus,
    ExternalChannelProvider,
    ExternalChannelResourceStatus,
)
from azents.repos.external_channel.data import (
    ExternalChannelConnectionConfiguration,
    ExternalChannelEvent,
    ExternalChannelResource,
    ExternalChannelResourceCreate,
)
from azents.repos.external_channel.work import ExternalChannelWorkRepository
from azents.services.external_channel.channel_action import (
    ExternalChannelActionService,
)
from azents.services.external_channel.credentials import ExternalChannelCredentialsCodec
from azents.services.external_channel.discord_events import (
    DiscordEventExcluded,
    DiscordNormalizedMessage,
)
from azents.services.external_channel.discord_history import (
    DiscordConversationHistoryClient,
)
from azents.services.external_channel.event_processor import (
    ExternalChannelEventProcessorService,
    ExternalChannelPersistedMessage,
    ExternalChannelPersistedRevision,
)
from azents.services.external_channel.slack_events import (
    SlackConversationClient,
    SlackNormalizedMessage,
)
from azents.services.mailbox import MailboxService
from azents.services.root_agent_session_creation import RootAgentSessionCreationService
from azents.worker.session.lifecycle import SessionLifecycleService

_NOW = datetime.datetime(2026, 7, 26, tzinfo=datetime.UTC)


class _Repository:
    """Capture Discord canonical-persistence operations without database I/O."""

    def __init__(self, *, resource: ExternalChannelResource | None) -> None:
        self.resource = resource
        self.created: list[ExternalChannelResourceCreate] = []
        self.lookups: list[str] = []

    async def lock_connection_for_routing(
        self,
        _session: AsyncSession,
        *,
        connection_id: str,
    ) -> object:
        return SimpleNamespace(id=connection_id)

    async def get_resource_by_provider_key(
        self,
        _session: AsyncSession,
        *,
        connection_id: str,
        provider_resource_key: str,
    ) -> ExternalChannelResource | None:
        assert connection_id == "connection-1"
        assert provider_resource_key.startswith("discord:guild-1:")
        self.lookups.append(provider_resource_key)
        return self.resource

    async def create_resource_idempotent(
        self,
        _session: AsyncSession,
        create: ExternalChannelResourceCreate,
    ) -> ExternalChannelResource:
        self.created.append(create)
        return cast(
            ExternalChannelResource,
            SimpleNamespace(
                id="resource-1",
                status=ExternalChannelResourceStatus.ACTIVE,
            ),
        )


class _Processor(ExternalChannelEventProcessorService):
    """Capture canonical revision persistence and terminal event completion."""

    def __init__(self, *, repository: _Repository) -> None:
        self.session = MagicMock(spec=AsyncSession)
        self.session.commit = AsyncMock()

        @asynccontextmanager
        async def session_manager() -> AsyncIterator[AsyncSession]:
            yield self.session

        super().__init__(
            session_manager=session_manager,
            repository=repository,  # type: ignore[arg-type]
            work_repository=cast(ExternalChannelWorkRepository, MagicMock()),
            action_service=cast(ExternalChannelActionService, MagicMock()),
            credentials_codec=cast(ExternalChannelCredentialsCodec, MagicMock()),
            slack_client=cast(SlackConversationClient, MagicMock()),
            discord_history_client=cast(
                DiscordConversationHistoryClient,
                MagicMock(spec=DiscordConversationHistoryClient),
            ),
            agent_repository=MagicMock(),
            agent_session_repository=MagicMock(),
            root_agent_session_creation_service=cast(
                RootAgentSessionCreationService,
                MagicMock(),
            ),
            workspace_repository=MagicMock(),
            config=MagicMock(),
            mailbox_item_service=cast(MailboxService, MagicMock()),
            session_lifecycle=cast(SessionLifecycleService, MagicMock()),
        )
        self.persisted: list[dict[str, object]] = []
        self.completed: list[dict[str, object]] = []

    async def _persist_normalized_message(
        self,
        session: AsyncSession,
        *,
        resource: ExternalChannelResource,
        message: SlackNormalizedMessage | DiscordNormalizedMessage,
        source_event_id: str | None,
        now: datetime.datetime,
        original_url: str | None,
        reference_mappings: dict[str, dict[str, str]],
        provider: ExternalChannelProvider = ExternalChannelProvider.SLACK,
    ) -> ExternalChannelPersistedRevision:
        del session
        self.persisted.append(
            {
                "resource": resource,
                "message": message,
                "source_event_id": source_event_id,
                "now": now,
                "original_url": original_url,
                "reference_mappings": reference_mappings,
                "provider": provider,
            }
        )
        return cast(ExternalChannelPersistedRevision, object())

    async def _persist_discord_message_event(
        self,
        *,
        session: AsyncSession,
        event: ExternalChannelEvent,
        configuration: ExternalChannelConnectionConfiguration,
        connection: object,
        resource: ExternalChannelResource,
        message: DiscordNormalizedMessage,
        now: datetime.datetime,
    ) -> ExternalChannelPersistedMessage:
        """Keep resource-persistence tests focused below the routing boundary."""
        del configuration, connection
        await self._persist_normalized_message(
            session,
            resource=resource,
            message=message,
            source_event_id=event.id,
            now=now,
            original_url=None,
            reference_mappings={},
            provider=ExternalChannelProvider.DISCORD,
        )
        await session.commit()
        return ExternalChannelPersistedMessage(
            resource_id=resource.id,
            hydration_required=False,
            control_delivery_attempt_id=None,
            activity_delivery_attempt_id=None,
            wake_up=None,
        )

    async def _complete_event(
        self,
        event: ExternalChannelEvent,
        *,
        eligibility_state: ExternalChannelEventEligibilityState,
        status: ExternalChannelEventStatus,
        purge_envelope: bool,
    ) -> None:
        self.completed.append(
            {
                "event": event,
                "eligibility_state": eligibility_state,
                "status": status,
                "purge_envelope": purge_envelope,
            }
        )


def _event(
    *,
    content: str,
    mentioned: bool,
    received_at: datetime.datetime,
) -> ExternalChannelEvent:
    """Build one Gateway-admitted projected Discord message event."""
    return ExternalChannelEvent.model_construct(
        id="event-1",
        connection_id="connection-1",
        provider_event_id="discord-gateway:session-1:5",
        transport_envelope_id="discord-gateway:session-1:5",
        event_type="discord_message_create",
        provider_app_id="app-1",
        provider_tenant_id="guild-1",
        provider_enterprise_id=None,
        resource_correlation_key="guild-1:200",
        eligibility_state=ExternalChannelEventEligibilityState.UNCLASSIFIED,
        envelope={
            "message": {
                "id": "100",
                "channel_id": "200",
                "guild_id": "guild-1",
                "content": content,
                "author": {"id": "300"},
                **({"mentions": [{"id": "900"}]} if mentioned else {}),
            }
        },
        status=ExternalChannelEventStatus.ACCEPTED,
        attempt_count=1,
        claim_owner="processor-1",
        claim_until=None,
        error_kind=None,
        error_summary=None,
        provider_occurred_at=None,
        received_at=received_at,
        processing_started_at=None,
        processed_at=None,
        created_at=_NOW,
        updated_at=_NOW,
    )


def _configuration() -> ExternalChannelConnectionConfiguration:
    """Build only the Discord configuration fields used by the processor branch."""
    return cast(
        ExternalChannelConnectionConfiguration,
        SimpleNamespace(
            provider=ExternalChannelProvider.DISCORD,
            provider_tenant_id="guild-1",
            provider_bot_user_id="900",
        ),
    )


@pytest.mark.asyncio
async def test_persists_mention_as_prospective_discord_thread_source() -> None:
    """A parent-channel mention creates canonical source state before provisioning."""
    repository = _Repository(resource=None)
    processor = _Processor(repository=repository)

    await processor._process_discord_claimed_event(  # pyright: ignore[reportPrivateUsage]
        event=_event(content="Please help", mentioned=True, received_at=_NOW),
        configuration=_configuration(),
    )

    assert len(repository.created) == 1
    create = repository.created[0]
    assert create.provider_resource_key == "discord:guild-1:100"
    assert create.hydration_status is ExternalChannelHydrationStatus.PENDING
    assert len(processor.persisted) == 1
    assert processor.persisted[0]["provider"] is ExternalChannelProvider.DISCORD
    assert len(processor.completed) == 1
    assert processor.completed[0]["status"] is ExternalChannelEventStatus.PROCESSED
    processor.session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_unlinked_non_mention_is_excluded_after_wait_window() -> None:
    """Ordinary parent-channel traffic cannot create an arbitrary Discord resource."""
    repository = _Repository(resource=None)
    processor = _Processor(repository=repository)
    event = _event(
        content="ordinary traffic",
        mentioned=False,
        received_at=_NOW - datetime.timedelta(minutes=6),
    )

    with pytest.raises(DiscordEventExcluded, match="not linked"):
        await processor._process_discord_claimed_event(  # pyright: ignore[reportPrivateUsage]
            event=event,
            configuration=_configuration(),
        )

    assert repository.created == []
    assert processor.persisted == []
    assert processor.completed == []


@pytest.mark.asyncio
async def test_mention_reuses_existing_thread_before_prospective_root() -> None:
    """A Gateway mention inside a known thread cannot create a second resource."""
    resource = cast(
        ExternalChannelResource,
        SimpleNamespace(
            id="resource-1",
            status=ExternalChannelResourceStatus.ACTIVE,
        ),
    )
    repository = _Repository(resource=resource)
    processor = _Processor(repository=repository)

    await processor._process_discord_claimed_event(  # pyright: ignore[reportPrivateUsage]
        event=_event(content="Follow up", mentioned=True, received_at=_NOW),
        configuration=_configuration(),
    )

    assert repository.lookups == ["discord:guild-1:200"]
    assert repository.created == []
    assert processor.persisted[0]["resource"] is resource
