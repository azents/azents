"""Durable External Channel ingress queue repository tests."""

import datetime
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, MagicMock

from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    ExternalChannelConversationScopeKind,
    ExternalChannelIngressAuthorityKind,
    ExternalChannelIngressItemState,
    ExternalChannelIngressProfile,
    ExternalChannelProvider,
)
from azents.rdb.models.external_channel_ingress import (
    RDBExternalChannelIngressItem,
)
from azents.repos.external_channel.ingress_queue import (
    ExternalChannelIngressQueueRepository,
)

_NOW = datetime.datetime(2026, 8, 10, 1, tzinfo=datetime.UTC)


class _ExpiredUpdatedAtItem(SimpleNamespace):
    """Raise when DTO conversion reads updated_at before an explicit refresh."""

    updated_at_loaded: bool = True

    def __getattribute__(self, name: str) -> object:
        if name == "updated_at" and not super().__getattribute__("updated_at_loaded"):
            raise RuntimeError("updated_at remains expired")
        return super().__getattribute__(name)


def _drain(
    *,
    first_batch_pending: bool,
    lease_owner: str | None = "owner-1",
    lease_generation: int = 1,
    lease_expires_at: datetime.datetime | None = None,
) -> SimpleNamespace:
    """Build one mutable ORM-shaped drain row."""
    return SimpleNamespace(
        session_id="session-1",
        lease_owner=lease_owner,
        lease_generation=lease_generation,
        lease_acquired_at=_NOW if lease_owner is not None else None,
        lease_expires_at=lease_expires_at
        if lease_expires_at is not None
        else (_NOW + datetime.timedelta(minutes=5) if lease_owner else None),
        first_batch_pending=first_batch_pending,
        current_batch_id=None,
        current_batch_started_at=None,
        created_at=_NOW,
        updated_at=_NOW,
    )


def _item(index: int) -> SimpleNamespace:
    """Build one mutable ORM-shaped active queue row."""
    position = f"{index:020d}"
    return SimpleNamespace(
        id=f"item-{index}",
        session_id="session-1",
        queue_key=f"{index:032d}",
        deduplication_key=f"{index:064d}",
        provider_event_id=f"event-{index}",
        connection_id="connection-1",
        provider=ExternalChannelProvider.SLACK,
        ingress_profile=ExternalChannelIngressProfile.SLACK_HTTP,
        configuration_generation=1,
        authority_kind=ExternalChannelIngressAuthorityKind.CONFIGURATION,
        authority_lease_owner=None,
        authority_lease_generation=None,
        provider_event_type="message",
        provider_tenant_id="tenant-1",
        scope_kind=ExternalChannelConversationScopeKind.THREAD,
        provider_channel_id="channel-1",
        provider_parent_channel_id=None,
        provider_thread_key="thread-1",
        delivery_thread_key="thread-1",
        provider_resource_key="resource-1",
        resource_id="resource-1",
        binding_id="binding-1",
        conversation_position_id="position-1",
        principal_id="principal-1",
        trigger_provider_message_key=f"message-{index}",
        trigger_provider_message_id=str(index),
        trigger_position=position,
        provider_user_id="user-1",
        invocation=True,
        invocation_id=f"invocation-{index}",
        initial_title_eligible=False,
        state=ExternalChannelIngressItemState.PENDING,
        attempt_count=0,
        next_attempt_at=None,
        processing_owner=None,
        processing_generation=None,
        batch_id=None,
        created_at=_NOW,
        updated_at=_NOW,
    )


def _session() -> MagicMock:
    """Build one AsyncSession-shaped mock with transactional methods."""
    session = MagicMock(spec=AsyncSession)
    session.scalar = AsyncMock()
    session.scalars = AsyncMock()
    session.execute = AsyncMock()
    session.flush = AsyncMock()
    session.refresh = AsyncMock()
    return session


async def test_claim_due_batch_uses_one_then_ten_item_limits() -> None:
    """The first execution is single-item and later claims are capped at ten."""
    repository = ExternalChannelIngressQueueRepository()

    first_session = _session()
    first_drain = _drain(first_batch_pending=True)
    first_row = _item(0)
    first_session.scalar.return_value = first_drain
    first_session.scalars.return_value = [first_row]

    first = await repository.claim_due_batch(
        first_session,
        session_id="session-1",
        lease_owner="owner-1",
        lease_generation=1,
        now=_NOW,
    )

    assert first is not None
    assert len(first.items) == 1
    assert first_row.state is ExternalChannelIngressItemState.PROCESSING
    assert first_row.attempt_count == 1
    assert first_drain.first_batch_pending is False
    first_statement = first_session.scalars.await_args.args[0]
    assert first_statement._limit_clause.value == 1  # noqa: SLF001

    later_session = _session()
    later_drain = _drain(first_batch_pending=False)
    later_rows = [_item(index) for index in range(10)]
    later_session.scalar.return_value = later_drain
    later_session.scalars.return_value = later_rows

    later = await repository.claim_due_batch(
        later_session,
        session_id="session-1",
        lease_owner="owner-1",
        lease_generation=1,
        now=_NOW,
    )

    assert later is not None
    assert len(later.items) == 10
    assert all(
        row.state is ExternalChannelIngressItemState.PROCESSING for row in later_rows
    )
    later_statement = later_session.scalars.await_args.args[0]
    assert later_statement._limit_clause.value == 10  # noqa: SLF001


async def test_claim_due_batch_refreshes_updated_at_before_dto_conversion() -> None:
    """A flush-expired onupdate timestamp is loaded before Pydantic reads it."""
    repository = ExternalChannelIngressQueueRepository()
    session = _session()
    drain = _drain(first_batch_pending=True)
    item = _ExpiredUpdatedAtItem(**vars(_item(0)))
    item.updated_at_loaded = False
    session.scalar.return_value = drain
    session.scalars.return_value = [item]

    async def refresh_updated_at(
        refreshed: _ExpiredUpdatedAtItem,
        *,
        attribute_names: list[str],
    ) -> None:
        assert refreshed is item
        assert attribute_names == ["updated_at"]
        refreshed.updated_at_loaded = True

    session.refresh.side_effect = refresh_updated_at

    claimed = await repository.claim_due_batch(
        session,
        session_id="session-1",
        lease_owner="owner-1",
        lease_generation=1,
        now=_NOW,
    )

    assert claimed is not None
    assert claimed.items[0].updated_at == _NOW
    session.refresh.assert_awaited_once_with(item, attribute_names=["updated_at"])


async def test_expired_lease_is_reclaimed_and_current_lease_is_released() -> None:
    """A stale owner is fenced by generation and explicit release clears ownership."""
    repository = ExternalChannelIngressQueueRepository()
    claim_session = _session()
    drain = _drain(
        first_batch_pending=False,
        lease_owner="stale-owner",
        lease_generation=4,
        lease_expires_at=_NOW - datetime.timedelta(seconds=1),
    )
    claim_session.scalar.return_value = drain

    claim = await repository.claim_lease(
        claim_session,
        session_id="session-1",
        lease_owner="owner-2",
        now=_NOW,
        lease_expires_at=_NOW + datetime.timedelta(minutes=5),
    )

    assert claim is not None
    assert claim.session.lease_owner == "owner-2"
    assert claim.session.lease_generation == 5
    assert drain.current_batch_id is None
    reset_statement = claim_session.execute.await_args.args[0]
    reset_sql = str(
        reset_statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )
    assert "state='processing'" in reset_sql.replace(" ", "")

    release_session = _session()
    release_result = MagicMock()
    release_result.scalar_one_or_none.return_value = "session-1"
    release_session.execute.return_value = release_result

    released = await repository.release_lease(
        release_session,
        session_id="session-1",
        lease_owner="owner-2",
        lease_generation=5,
    )

    assert released is True
    release_sql = str(
        release_session.execute.await_args.args[0].compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )
    assert "lease_owner=NULL" in release_sql.replace(" ", "")
    assert "lease_generation = 5" in release_sql


async def test_retry_moves_same_item_and_original_age_to_queue_tail() -> None:
    """Retry preserves durable identity/age while assigning a fresh tail key."""
    repository = ExternalChannelIngressQueueRepository()
    session = _session()
    item = _item(1)
    item.queue_key = "0" * 32
    item.state = ExternalChannelIngressItemState.PROCESSING
    item.attempt_count = 2
    item.processing_owner = "owner-1"
    item.processing_generation = 1
    item.batch_id = "batch-1"
    item_id = item.id
    created_at = item.created_at
    next_attempt_at = _NOW + datetime.timedelta(seconds=30)

    await repository.move_to_retry_tail(
        session,
        item=cast(RDBExternalChannelIngressItem, item),
        next_attempt_at=next_attempt_at,
    )

    assert item.id == item_id
    assert item.created_at == created_at
    assert item.queue_key != "0" * 32
    assert item.state is ExternalChannelIngressItemState.RETRY_WAITING
    assert item.attempt_count == 2
    assert item.next_attempt_at == next_attempt_at
    assert item.processing_owner is None
    assert item.processing_generation is None
    assert item.batch_id is None
    session.flush.assert_awaited_once()


async def test_recovery_query_includes_unowned_processing_rows() -> None:
    """Crash recovery can reclaim processing work after lease ownership is cleared."""
    repository = ExternalChannelIngressQueueRepository()
    session = _session()
    session.scalars.return_value = [_drain(first_batch_pending=False, lease_owner=None)]

    recovered = await repository.list_recoverable_sessions(
        session,
        now=_NOW,
        limit=100,
    )

    assert [drain.session_id for drain in recovered] == ["session-1"]
    assert recovered[0].created_at == _NOW
    statement = session.scalars.await_args.args[0]
    sql = str(
        statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )
    assert "'processing'" in sql
    assert "external_channel_ingress_sessions.lease_owner IS NULL" in sql


async def test_active_diagnostics_are_bounded_and_content_free() -> None:
    """Inspection exposes active ownership and timing without provider content."""
    repository = ExternalChannelIngressQueueRepository()
    session = _session()
    item = _item(1)
    item.state = ExternalChannelIngressItemState.RETRY_WAITING
    item.attempt_count = 2
    item.next_attempt_at = _NOW + datetime.timedelta(seconds=30)
    drain = _drain(first_batch_pending=False)
    drain.current_batch_id = "batch-1"
    drain.current_batch_started_at = _NOW - datetime.timedelta(seconds=2)

    summary_result = MagicMock()
    summary_result.one.return_value = (
        1,
        0,
        0,
        1,
        _NOW - datetime.timedelta(seconds=10),
        1,
    )
    rows_result = MagicMock()
    rows_result.tuples.return_value = [(item, drain)]
    session.execute.side_effect = [summary_result, rows_result]

    snapshot = await repository.inspect_active(
        session,
        now=_NOW,
        limit=10,
    )

    assert snapshot.session_count == 1
    assert snapshot.counts.pending == 0
    assert snapshot.counts.processing == 0
    assert snapshot.counts.retry_waiting == 1
    assert snapshot.counts.total == 1
    assert snapshot.oldest_queue_age_seconds == 10
    assert snapshot.truncated is False
    assert snapshot.items[0].connection_id == "connection-1"
    assert snapshot.items[0].attempt_count == 2
    assert snapshot.items[0].next_attempt_at == item.next_attempt_at
    assert snapshot.items[0].lease_owner == "owner-1"
    serialized = snapshot.model_dump_json()
    for forbidden in (
        "deduplication_key",
        "provider_event_id",
        "trigger_provider_message_key",
        "provider_user_id",
        "principal_id",
    ):
        assert forbidden not in serialized
