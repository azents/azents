"""Channel Action commit-before-delivery orchestration tests."""

import datetime
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    ExternalChannelDeliveryOperation,
    ExternalChannelDeliveryStatus,
    ExternalChannelProvider,
    ExternalChannelWorkStatus,
)
from azents.rdb.session import SessionManager
from azents.repos.external_channel.work import ExternalChannelWorkRepository
from azents.repos.external_channel.work_data import (
    ChannelActionCommit,
    ChannelDeliveryTarget,
    ChannelWorkDelivery,
)
from azents.services.external_channel.channel_action import (
    ExternalChannelActionService,
)
from azents.services.external_channel.credentials import ExternalChannelCredentialsCodec
from azents.services.external_channel.data import SlackConnectionCredentials
from azents.services.external_channel.slack_events import (
    SlackControlMessageResult,
    SlackConversationClient,
)


def _at(second: int) -> datetime.datetime:
    return datetime.datetime(2026, 7, 22, 0, 0, second, tzinfo=datetime.UTC)


class _SessionDouble:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    async def commit(self) -> None:
        self.events.append("commit")


class _RepositoryDouble:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.finished: list[
            tuple[ExternalChannelDeliveryStatus, str | None, str | None]
        ] = []
        self.target = ChannelDeliveryTarget(
            delivery_attempt_id="delivery-1",
            operation=ExternalChannelDeliveryOperation.REPLY,
            status=ExternalChannelDeliveryStatus.PENDING,
            binding_id="binding-1",
            connection_id="connection-1",
            provider=ExternalChannelProvider.SLACK,
            encrypted_credentials="ciphertext",
            provider_tenant_id="T1",
            request_payload={
                "channel_id": "C1",
                "thread_ts": "1.000001",
                "text": "Reply",
            },
        )

    async def get_delivery_target(
        self,
        session: AsyncSession,
        *,
        delivery_attempt_id: str,
    ) -> ChannelDeliveryTarget | None:
        del session
        assert delivery_attempt_id == "delivery-1"
        return self.target

    async def start_delivery(
        self,
        session: AsyncSession,
        *,
        delivery_attempt_id: str,
        now: datetime.datetime,
    ) -> bool:
        del session, delivery_attempt_id, now
        self.events.append("start")
        return True

    async def finish_delivery(
        self,
        session: AsyncSession,
        *,
        delivery_attempt_id: str,
        status: ExternalChannelDeliveryStatus,
        provider_message_key: str | None,
        error_kind: str | None,
        error_summary: str | None,
        now: datetime.datetime,
    ) -> None:
        del session, delivery_attempt_id, error_summary, now
        self.events.append("finish")
        self.finished.append((status, provider_message_key, error_kind))

    async def recover_archive_cleanup(
        self,
        session: AsyncSession,
        *,
        current_delivery_ids: list[str],
        now: datetime.datetime,
    ) -> None:
        del session, now
        assert current_delivery_ids == ["delivery-1"]
        self.events.append("recover")

    async def list_archive_cleanup_ids(
        self,
        session: AsyncSession,
        *,
        delivery_ids: list[str],
    ) -> list[str]:
        del session
        assert delivery_ids == ["delivery-1"]
        return list(delivery_ids)


class _CredentialsCodec:
    def decrypt(self, encrypted: str) -> SlackConnectionCredentials:
        assert encrypted == "ciphertext"
        return SlackConnectionCredentials(
            bot_token="xoxb-secret",
            signing_secret="signing-secret",
            app_token=None,
        )


class _SlackClient:
    def __init__(self, events: list[str], result: SlackControlMessageResult) -> None:
        self.events = events
        self.result = result
        self.bot_tokens: list[str] = []

    async def post_message(self, **kwargs: str) -> SlackControlMessageResult:
        self.events.append("provider")
        self.bot_tokens.append(kwargs["bot_token"])
        assert kwargs["channel_id"] == "C1"
        assert kwargs["thread_ts"] == "1.000001"
        assert kwargs["text"] == "Reply"
        return self.result


@asynccontextmanager
async def _session_manager(
    events: list[str],
) -> AsyncGenerator[AsyncSession]:
    yield cast(AsyncSession, _SessionDouble(events))


def _service(
    events: list[str],
    repository: _RepositoryDouble,
    slack_client: _SlackClient,
) -> ExternalChannelActionService:
    return ExternalChannelActionService(
        session_manager=cast(
            SessionManager[AsyncSession],
            lambda: _session_manager(events),
        ),
        repository=cast(ExternalChannelWorkRepository, repository),
        credentials_codec=cast(
            ExternalChannelCredentialsCodec,
            _CredentialsCodec(),
        ),
        slack_client=cast(SlackConversationClient, slack_client),
    )


@pytest.mark.asyncio
async def test_delivery_crosses_attempting_commit_before_provider_call() -> None:
    """The provider sees a call only after attempting is durably committed."""
    events: list[str] = []
    repository = _RepositoryDouble(events)
    slack_client = _SlackClient(
        events,
        SlackControlMessageResult(
            status="delivered",
            provider_message_key="slack:T1:C1:2.000001",
            error_kind=None,
            error_summary=None,
        ),
    )
    service = _service(events, repository, slack_client)

    await service.attempt_delivery("delivery-1")

    assert events == ["start", "commit", "provider", "finish", "commit"]
    assert repository.finished == [
        (
            ExternalChannelDeliveryStatus.DELIVERED,
            "slack:T1:C1:2.000001",
            None,
        )
    ]
    assert slack_client.bot_tokens == ["xoxb-secret"]


@pytest.mark.asyncio
async def test_prepared_delivery_survives_connection_secret_purge() -> None:
    """Disconnect cleanup uses the in-memory target captured before terminalization."""
    events: list[str] = []
    repository = _RepositoryDouble(events)
    slack_client = _SlackClient(
        events,
        SlackControlMessageResult(
            status="delivered",
            provider_message_key=None,
            error_kind=None,
            error_summary=None,
        ),
    )
    service = _service(events, repository, slack_client)

    target = await service.prepare_delivery("delivery-1")
    assert target is not None
    repository.target = repository.target.model_copy(
        update={
            "encrypted_credentials": None,
            "provider_tenant_id": None,
        }
    )

    await service.attempt_prepared_delivery(target)

    assert events == ["start", "commit", "provider", "finish", "commit"]
    assert slack_client.bot_tokens == ["xoxb-secret"]


@pytest.mark.asyncio
async def test_failed_delivery_is_terminal_and_not_reported_as_success() -> None:
    """A provider failure remains failed with its safe reason."""
    events: list[str] = []
    repository = _RepositoryDouble(events)
    service = _service(
        events,
        repository,
        _SlackClient(
            events,
            SlackControlMessageResult(
                status="failed",
                provider_message_key=None,
                error_kind="resource_unavailable",
                error_summary="Slack cannot post to the linked conversation.",
            ),
        ),
    )

    await service.attempt_delivery("delivery-1")

    assert repository.finished == [
        (ExternalChannelDeliveryStatus.FAILED, None, "resource_unavailable")
    ]
    assert events.count("provider") == 1


@pytest.mark.asyncio
async def test_archive_cleanup_consumes_each_pending_intent_once() -> None:
    """Post-archive cleanup delegates each durable pending row to the same fence."""
    events: list[str] = []
    repository = _RepositoryDouble(events)
    service = _service(
        events,
        repository,
        _SlackClient(
            events,
            SlackControlMessageResult(
                status="delivered",
                provider_message_key="slack:T1:C1:2.000001",
                error_kind=None,
                error_summary=None,
            ),
        ),
    )

    count = await service.drain_archive_cleanup(["delivery-1"])

    assert count == 1
    assert events == [
        "recover",
        "commit",
        "start",
        "commit",
        "provider",
        "finish",
        "commit",
    ]


def test_action_commit_fixture_preserves_transparent_outcomes() -> None:
    """The service-facing commit record distinguishes failed from delivered."""
    commit = ChannelActionCommit(
        action_id="action-1",
        binding_id="binding-1",
        work_id="work-1",
        work_status=ExternalChannelWorkStatus.ACTIVE,
        state_revision=2,
        deliveries=[
            ChannelWorkDelivery(
                id="delivery-1",
                operation=ExternalChannelDeliveryOperation.REPLY,
                status=ExternalChannelDeliveryStatus.UNKNOWN,
                provider_message_key=None,
                error_kind="provider_ambiguous",
                error_summary="Slack delivery outcome is unknown.",
                created_at=_at(1),
                completed_at=_at(2),
            )
        ],
    )

    assert commit.deliveries[0].status is ExternalChannelDeliveryStatus.UNKNOWN
