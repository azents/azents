"""Durable External Channel ingress drain tests."""

import asyncio
import datetime
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    AgentSessionStatus,
    ExternalChannelConversationScopeKind,
    ExternalChannelDeliveryOperation,
    ExternalChannelIngressAuthorityKind,
    ExternalChannelIngressItemState,
    ExternalChannelIngressProfile,
    ExternalChannelMessageLifecycle,
    ExternalChannelMessageRevisionKind,
    ExternalChannelPrincipalAuthorType,
    ExternalChannelProvider,
    ExternalChannelResourceStatus,
    ExternalChannelResourceType,
    ExternalChannelResponseMode,
)
from azents.rdb.session import SessionManager
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.external_channel.data import (
    ExternalChannelBinding,
    ExternalChannelConnection,
    ExternalChannelResource,
)
from azents.repos.external_channel.ingress_queue import (
    ExternalChannelIngressQueueRepository,
)
from azents.repos.external_channel.ingress_queue_data import (
    ExternalChannelIngressBatch,
    ExternalChannelIngressCorrelation,
    ExternalChannelIngressItem,
    ExternalChannelIngressLeaseClaim,
    ExternalChannelIngressOwner,
)
from azents.repos.external_channel.repository import ExternalChannelRepository
from azents.repos.external_channel.work import ExternalChannelWorkRepository
from azents.repos.mailbox.data import MailboxItem
from azents.services.external_channel.conversation import (
    ExternalChannelHistoryPermissionDenied,
    ExternalChannelHistoryRange,
)
from azents.services.external_channel.ingestion import (
    ExternalChannelCanonicalHistoryMessage,
)
from azents.services.external_channel.ingress_metrics import (
    ExternalChannelIngressMetrics,
)
from azents.services.external_channel.ingress_provisioning import (
    ExternalChannelIngressProvisioningService,
)
from azents.services.external_channel.ingress_queue import (
    ExternalChannelIngressDrainService,
    ExternalChannelIngressFailureCategory,
    ExternalChannelIngressProviderPolicyRegistry,
    _PreparedFailure,
    _PreparedSuccess,
    _provider_failure,
    _retry_transition,
    build_external_channel_ingress_job_request,
)
from azents.services.external_channel.mailbox_ingestion_store import (
    ExternalChannelConfiguredBindingResult,
)
from azents.services.external_channel.mailbox_wake import (
    ExternalChannelMailboxWakeDispatcher,
)
from azents.services.external_channel.provider_control import (
    ExternalChannelProviderControlService,
)
from azents.services.mailbox import (
    MailboxAdmissionResult,
    MailboxService,
)
from azents.testing.external_channel import make_provider_effect_plan

_NOW = datetime.datetime(2026, 8, 10, 2, tzinfo=datetime.UTC)


def test_job_request_coalesces_one_drain_lifecycle_and_separates_recreation() -> None:
    """A recreated drain cannot coalesce into the task ending its predecessor."""
    first = build_external_channel_ingress_job_request(
        owner_id="owner-1",
        drain_created_at=_NOW,
        now=_NOW,
    )
    same_lifecycle = build_external_channel_ingress_job_request(
        owner_id="owner-1",
        drain_created_at=_NOW,
        now=_NOW + datetime.timedelta(seconds=1),
    )
    recreated = build_external_channel_ingress_job_request(
        owner_id="owner-1",
        drain_created_at=_NOW + datetime.timedelta(microseconds=1),
        now=_NOW + datetime.timedelta(seconds=1),
    )

    assert first.execution_key == same_lifecycle.execution_key
    assert first.execution_key != recreated.execution_key
    assert first.payload == recreated.payload == {"owner_id": "owner-1"}


class _Session:
    """Minimal transactional AsyncSession-shaped test value."""

    def __init__(self) -> None:
        self.commit = AsyncMock()
        self.rollback = AsyncMock()


def _session_manager(
    *sessions: _Session,
) -> SessionManager[AsyncSession]:
    """Yield a fixed sequence of transaction test values."""
    remaining = iter(sessions)

    @asynccontextmanager
    async def manager() -> AsyncIterator[AsyncSession]:
        yield cast(AsyncSession, next(remaining))

    return manager


def _item(
    *,
    item_id: str,
    trigger_key: str,
    trigger_position: str,
    attempt_count: int = 1,
    created_at: datetime.datetime = _NOW,
    invocation: bool = True,
    initial_title_eligible: bool = False,
    provider: ExternalChannelProvider = ExternalChannelProvider.SLACK,
) -> ExternalChannelIngressItem:
    """Build one complete content-free active queue item."""
    return ExternalChannelIngressItem.model_construct(
        id=item_id,
        owner_id="owner-1",
        queue_key=item_id,
        deduplication_key=f"dedupe-{item_id}",
        provider_event_id=f"event-{item_id}",
        connection_id="connection-1",
        provider=provider,
        ingress_profile=(
            ExternalChannelIngressProfile.DISCORD_GATEWAY_HTTP
            if provider is ExternalChannelProvider.DISCORD
            else ExternalChannelIngressProfile.SLACK_HTTP
        ),
        configuration_generation=1,
        authority_kind=(
            ExternalChannelIngressAuthorityKind.LEASE
            if provider is ExternalChannelProvider.DISCORD
            else ExternalChannelIngressAuthorityKind.CONFIGURATION
        ),
        authority_lease_owner=(
            "gateway-1" if provider is ExternalChannelProvider.DISCORD else None
        ),
        authority_lease_generation=(
            1 if provider is ExternalChannelProvider.DISCORD else None
        ),
        provider_event_type="message",
        provider_tenant_id="tenant-1",
        scope_kind=ExternalChannelConversationScopeKind.THREAD,
        provider_channel_id="channel-1",
        provider_parent_channel_id=None,
        provider_thread_key="thread-1",
        delivery_thread_key="thread-1",
        provider_resource_key="resource-1",
        source_resource_id="resource-1",
        conversation_position_id="position-1",
        principal_id="principal-1",
        trigger_provider_message_key=trigger_key,
        trigger_provider_message_id=trigger_position,
        trigger_position=trigger_position,
        provider_user_id="user-1",
        invocation=invocation,
        invocation_id=f"invocation-{item_id}",
        initial_title_eligible=initial_title_eligible,
        state=ExternalChannelIngressItemState.PROCESSING,
        attempt_count=attempt_count,
        next_attempt_at=None,
        processing_owner="owner-1",
        processing_generation=1,
        batch_id="batch-1",
        created_at=created_at,
        updated_at=_NOW,
    )


def _message(
    *,
    key: str,
    position: str,
    body: str,
) -> ExternalChannelCanonicalHistoryMessage:
    """Build one canonical retained provider message."""
    return ExternalChannelCanonicalHistoryMessage(
        provider_message_key=key,
        provider_position=position,
        revision_key=f"{key}:original",
        revision_kind=ExternalChannelMessageRevisionKind.ORIGINAL,
        lifecycle=ExternalChannelMessageLifecycle.CURRENT,
        author_type=ExternalChannelPrincipalAuthorType.HUMAN,
        provider_user_id="user-1",
        sender_display_name="Participant",
        normalized_body=body,
        attachment_metadata=None,
        reference_mappings=None,
        normalized_size=len(body),
        provider_created_at=_NOW,
        provider_updated_at=None,
        original_url=None,
    )


def _history(
    *,
    trigger_key: str,
    trigger_position: str,
    include_context: bool = False,
    body: str = "provider message",
) -> ExternalChannelHistoryRange[ExternalChannelCanonicalHistoryMessage]:
    """Build one valid provider range ending at the selected trigger."""
    trigger = _message(
        key=trigger_key,
        position=trigger_position,
        body=body,
    )
    messages = (
        (
            _message(
                key="context-message",
                position="00000000000000000001",
                body="older context",
            ),
            trigger,
        )
        if include_context
        else (trigger,)
    )
    return ExternalChannelHistoryRange(
        messages=messages,
        trigger=trigger,
        context_omitted=include_context,
        range_start_position=None,
        trigger_position=trigger_position,
        provider_request_count=1,
        scanned_message_count=len(messages),
        elapsed_seconds=0,
    )


def _batch(*items: ExternalChannelIngressItem) -> ExternalChannelIngressBatch:
    """Build one fenced claimed batch."""
    return ExternalChannelIngressBatch(
        owner_id="owner-1",
        target_resource_id="resource-1",
        binding_id="binding-1",
        session_id="session-1",
        batch_id="batch-1",
        lease_owner="owner-1",
        lease_generation=1,
        items=items,
    )


def _resource() -> ExternalChannelResource:
    return ExternalChannelResource.model_construct(
        id="resource-1",
        connection_id="connection-1",
        resource_type=ExternalChannelResourceType.THREAD,
        provider_resource_key="resource-1",
        labels={
            "provider": "slack",
            "tenant_id": "tenant-1",
            "channel_id": "channel-1",
            "thread_ts": "thread-1",
        },
        status=ExternalChannelResourceStatus.ACTIVE,
    )


def _binding() -> ExternalChannelBinding:
    return ExternalChannelBinding.model_construct(
        id="binding-1",
        resource_id="resource-1",
        route_id="route-1",
        agent_session_id="session-1",
        response_mode=ExternalChannelResponseMode.ALL_MESSAGES,
        disconnected_at=None,
    )


def _service(
    *,
    session_manager: SessionManager[AsyncSession],
    repository: MagicMock,
    queue_repository: MagicMock,
    mailbox_service: MagicMock,
    agent_session_repository: MagicMock,
    wake_dispatcher: MagicMock,
    work_repository: MagicMock | None = None,
    provider_control: MagicMock | None = None,
) -> ExternalChannelIngressDrainService:
    """Construct the drain with isolated collaborators."""
    work = work_repository or MagicMock()
    if work_repository is None:
        work.ensure_active_work = AsyncMock(
            return_value=SimpleNamespace(work_cycle_id="work-1")
        )
        work.prepare_direct_control = AsyncMock(return_value=None)
        work.prepare_initial_progress = AsyncMock(return_value=None)
    control = provider_control or MagicMock()
    if provider_control is None:
        control.attempt = AsyncMock()
    return ExternalChannelIngressDrainService(
        session_manager=session_manager,
        repository=cast(ExternalChannelRepository, repository),
        queue_repository=cast(
            ExternalChannelIngressQueueRepository,
            queue_repository,
        ),
        agent_session_repository=cast(
            AgentSessionRepository,
            agent_session_repository,
        ),
        provider_policies=cast(
            ExternalChannelIngressProviderPolicyRegistry,
            MagicMock(),
        ),
        provisioning_service=cast(
            ExternalChannelIngressProvisioningService,
            MagicMock(),
        ),
        work_repository=cast(ExternalChannelWorkRepository, work),
        mailbox_service=cast(MailboxService, mailbox_service),
        wake_dispatcher=cast(
            ExternalChannelMailboxWakeDispatcher,
            wake_dispatcher,
        ),
        provider_control=cast(ExternalChannelProviderControlService, control),
        metrics=ExternalChannelIngressMetrics(),
    )


def _collaborators(
    *,
    locked_rows: list[SimpleNamespace],
    mailbox_created: bool = True,
) -> tuple[MagicMock, MagicMock, MagicMock, MagicMock, MagicMock, SimpleNamespace]:
    """Build successful finalization collaborators for one claimed batch."""
    drain = SimpleNamespace(session_id="session-1")
    repository = MagicMock()
    repository.lock_connection_for_routing = AsyncMock(
        return_value=ExternalChannelConnection.model_construct(
            id="connection-1",
            provider=ExternalChannelProvider.SLACK,
            provider_tenant_id="tenant-1",
            ingress_profile=ExternalChannelIngressProfile.SLACK_HTTP,
            configuration_generation=1,
        )
    )
    repository.lock_conversation_position = AsyncMock(
        return_value=SimpleNamespace(read_through_position=None)
    )
    repository.lock_resource = AsyncMock(return_value=_resource())
    repository.lock_binding = AsyncMock(return_value=_binding())
    repository.advance_conversation_position_if_current = AsyncMock(return_value=True)

    queue_repository = MagicMock()
    queue_repository.lock_claimed_batch = AsyncMock(return_value=(drain, locked_rows))
    queue_repository.list_active_correlations = AsyncMock(return_value={})
    queue_repository.reset_batch_for_coordination = AsyncMock()
    queue_repository.move_to_retry_tail = AsyncMock()
    queue_repository.finish_batch = AsyncMock()

    mailbox_service = MagicMock()

    async def enqueue_many(
        _session: AsyncSession,
        enqueues: list[object],
    ) -> list[MailboxAdmissionResult]:
        return [
            MailboxAdmissionResult(
                mailbox_item=MailboxItem.model_construct(
                    id=f"mailbox-{index}",
                    session_id="session-1",
                ),
                created=mailbox_created,
            )
            for index, _enqueue in enumerate(enqueues)
        ]

    mailbox_service.enqueue_many = AsyncMock(side_effect=enqueue_many)
    agent_session_repository = MagicMock()
    agent_session_repository.lock_by_id = AsyncMock()
    agent_session_repository.get_by_id = AsyncMock(
        return_value=SimpleNamespace(
            agent_id="agent-1",
            status=AgentSessionStatus.ACTIVE,
            stop_requested_at=None,
        )
    )
    agent_session_repository.admit_input_wakeup = AsyncMock(
        return_value=SimpleNamespace(agent_id="agent-1")
    )
    wake_dispatcher = MagicMock()
    wake_dispatcher.dispatch = AsyncMock(return_value="dispatched")
    return (
        repository,
        queue_repository,
        mailbox_service,
        agent_session_repository,
        wake_dispatcher,
        drain,
    )


async def test_ownership_check_reads_session_without_a_row_lock() -> None:
    """Ownership filtering defers Session serialization to the final CAS."""
    item = _item(
        item_id="item-1",
        trigger_key="message-1",
        trigger_position="00000000000000000001",
    )
    (
        repository,
        queue_repository,
        mailbox_service,
        agent_session_repository,
        wake_dispatcher,
        _drain,
    ) = _collaborators(locked_rows=[SimpleNamespace(id=item.id)])
    service = _service(
        session_manager=_session_manager(_Session()),
        repository=repository,
        queue_repository=queue_repository,
        mailbox_service=mailbox_service,
        agent_session_repository=agent_session_repository,
        wake_dispatcher=wake_dispatcher,
    )
    connection = await repository.lock_connection_for_routing(
        cast(AsyncSession, MagicMock()),
        connection_id=item.connection_id,
    )

    current = await service._ownership_current(  # noqa: SLF001
        cast(AsyncSession, MagicMock()),
        item=item,
        batch=_batch(item),
        connection=connection,
        now=_NOW,
    )

    assert current is True
    agent_session_repository.get_by_id.assert_awaited_once()
    agent_session_repository.lock_by_id.assert_not_awaited()


async def test_late_cursor_cas_conflict_rolls_back_and_resets_claim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Mailbox/cursor effects roll back and the still-owned claim returns to pending."""
    item = _item(
        item_id="item-1",
        trigger_key="message-1",
        trigger_position="00000000000000000001",
    )
    row = SimpleNamespace(id=item.id)
    (
        repository,
        queue_repository,
        mailbox_service,
        agent_session_repository,
        wake_dispatcher,
        drain,
    ) = _collaborators(locked_rows=[row])
    queue_repository.lock_claimed_batch = AsyncMock(
        side_effect=[(drain, [row]), (drain, [row])]
    )
    repository.advance_conversation_position_if_current = AsyncMock(return_value=False)
    transaction = _Session()
    reset_transaction = _Session()
    service = _service(
        session_manager=_session_manager(transaction, reset_transaction),
        repository=repository,
        queue_repository=queue_repository,
        mailbox_service=mailbox_service,
        agent_session_repository=agent_session_repository,
        wake_dispatcher=wake_dispatcher,
    )
    monkeypatch.setattr(service, "_ownership_current", AsyncMock(return_value=True))

    stale = await service._finalize_batch(  # noqa: SLF001
        _batch(item),
        prepared=[
            _PreparedSuccess(
                item=item,
                durable_cursor=None,
                history=_history(
                    trigger_key=item.trigger_provider_message_key,
                    trigger_position=item.trigger_position,
                ),
            )
        ],
    )

    assert stale is True
    transaction.rollback.assert_awaited_once()
    reset_transaction.commit.assert_awaited_once()
    queue_repository.reset_batch_for_coordination.assert_awaited_once_with(
        reset_transaction,
        owner=drain,
        items=[row],
    )
    queue_repository.finish_batch.assert_not_awaited()
    agent_session_repository.admit_input_wakeup.assert_not_awaited()
    wake_dispatcher.dispatch.assert_not_awaited()


async def test_session_admission_cas_failure_rolls_back_and_resets_claim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A Session that starts stopping cannot commit prepared mailbox input."""
    item = _item(
        item_id="item-1",
        trigger_key="message-1",
        trigger_position="00000000000000000001",
    )
    row = SimpleNamespace(id=item.id)
    (
        repository,
        queue_repository,
        mailbox_service,
        agent_session_repository,
        wake_dispatcher,
        _drain,
    ) = _collaborators(locked_rows=[row])
    agent_session_repository.admit_input_wakeup.return_value = None
    transaction = _Session()
    reset_transaction = _Session()
    service = _service(
        session_manager=_session_manager(transaction, reset_transaction),
        repository=repository,
        queue_repository=queue_repository,
        mailbox_service=mailbox_service,
        agent_session_repository=agent_session_repository,
        wake_dispatcher=wake_dispatcher,
    )
    monkeypatch.setattr(service, "_ownership_current", AsyncMock(return_value=True))

    stale = await service._finalize_batch(  # noqa: SLF001
        _batch(item),
        prepared=[
            _PreparedSuccess(
                item=item,
                durable_cursor=None,
                history=_history(
                    trigger_key=item.trigger_provider_message_key,
                    trigger_position=item.trigger_position,
                ),
            )
        ],
    )

    assert stale is True
    transaction.rollback.assert_awaited_once()
    reset_transaction.commit.assert_awaited_once()
    queue_repository.finish_batch.assert_not_awaited()
    agent_session_repository.lock_by_id.assert_not_awaited()
    agent_session_repository.admit_input_wakeup.assert_awaited_once_with(
        transaction,
        "session-1",
    )
    wake_dispatcher.dispatch.assert_not_awaited()


async def test_coordination_exhaustion_releases_current_lease(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Four stale finalizations release the lease for producer recovery."""
    item = _item(
        item_id="item-1",
        trigger_key="message-1",
        trigger_position="00000000000000000001",
    )
    batch = _batch(item)
    queue_repository = MagicMock()
    queue_repository.claim_lease = AsyncMock(
        return_value=ExternalChannelIngressLeaseClaim(
            owner=ExternalChannelIngressOwner.model_construct(
                id="owner-1",
                binding_id="binding-1",
                session_id="session-1",
                lease_generation=7,
            )
        )
    )
    queue_repository.claim_due_batch = AsyncMock(
        side_effect=[batch, batch, batch, batch]
    )
    queue_repository.release_lease = AsyncMock(return_value=True)
    transactions = [_Session() for _ in range(6)]
    service = _service(
        session_manager=_session_manager(*transactions),
        repository=MagicMock(),
        queue_repository=queue_repository,
        mailbox_service=MagicMock(),
        agent_session_repository=MagicMock(),
        wake_dispatcher=MagicMock(),
    )
    prepare = AsyncMock(return_value=[])
    finalize = AsyncMock(return_value=True)
    monkeypatch.setattr(service, "_prepare_batch", prepare)
    monkeypatch.setattr(service, "_finalize_batch", finalize)

    await service.drain(
        owner_id="owner-1",
        deadline=_NOW + datetime.timedelta(minutes=20),
    )

    assert queue_repository.claim_due_batch.await_count == 4
    assert prepare.await_count == 4
    assert finalize.await_count == 4
    final_claim_args = queue_repository.claim_due_batch.await_args
    assert final_claim_args is not None
    queue_repository.release_lease.assert_awaited_once_with(
        transactions[-1],
        owner_id="owner-1",
        lease_owner=final_claim_args.kwargs["lease_owner"],
        lease_generation=7,
    )
    assert all(transaction.commit.await_count == 1 for transaction in transactions)


async def test_finalization_connection_first_order_prevents_admission_deadlock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Concurrent callback admission and finalization avoid lock inversion."""
    connection_lock = asyncio.Lock()
    drain_lock = asyncio.Lock()
    admission_holds_connection = asyncio.Event()

    class _LockSession(_Session):
        def __init__(self, role: str) -> None:
            super().__init__()
            self.role = role
            self.held_locks: list[asyncio.Lock] = []

        async def acquire(self, lock: asyncio.Lock) -> None:
            await lock.acquire()
            self.held_locks.append(lock)

        def holds(self, lock: asyncio.Lock) -> bool:
            return lock in self.held_locks

        def release_all(self) -> None:
            for lock in reversed(self.held_locks):
                lock.release()
            self.held_locks.clear()

    @asynccontextmanager
    async def session_manager() -> AsyncIterator[AsyncSession]:
        task = asyncio.current_task()
        assert task is not None
        session = _LockSession(task.get_name())
        try:
            yield cast(AsyncSession, session)
        finally:
            session.release_all()

    connection = ExternalChannelConnection.model_construct(
        id="connection-1",
        provider=ExternalChannelProvider.SLACK,
        provider_tenant_id="tenant-1",
        ingress_profile=ExternalChannelIngressProfile.SLACK_HTTP,
        configuration_generation=1,
    )
    repository = MagicMock()

    async def lock_connection(
        session: AsyncSession,
        *,
        connection_id: str,
    ) -> ExternalChannelConnection:
        assert connection_id == "connection-1"
        lock_session = cast(_LockSession, session)
        await lock_session.acquire(connection_lock)
        if lock_session.role == "callback-admission":
            admission_holds_connection.set()
        return connection

    repository.lock_connection_for_routing = AsyncMock(side_effect=lock_connection)
    repository.lock_conversation_position = AsyncMock(
        return_value=SimpleNamespace(read_through_position=None)
    )
    queue_repository = MagicMock()
    drain = SimpleNamespace(session_id="session-1")
    item = _item(
        item_id="item-1",
        trigger_key="message-1",
        trigger_position="00000000000000000001",
    )
    row = SimpleNamespace(id=item.id)

    async def lock_claimed_batch(
        session: AsyncSession,
        *,
        claim: ExternalChannelIngressBatch,
        now: datetime.datetime,
    ) -> tuple[SimpleNamespace, list[SimpleNamespace]]:
        del claim, now
        lock_session = cast(_LockSession, session)
        await lock_session.acquire(drain_lock)
        if not lock_session.holds(connection_lock):
            # This is the former drain -> connection order. Wait until callback
            # admission owns connection, then model the later ownership lock.
            await admission_holds_connection.wait()
            await lock_session.acquire(connection_lock)
        return drain, [row]

    queue_repository.lock_claimed_batch = AsyncMock(side_effect=lock_claimed_batch)
    queue_repository.list_active_correlations = AsyncMock(return_value={})
    queue_repository.finish_batch = AsyncMock()
    service = _service(
        session_manager=cast(SessionManager[AsyncSession], session_manager),
        repository=repository,
        queue_repository=queue_repository,
        mailbox_service=MagicMock(),
        agent_session_repository=MagicMock(),
        wake_dispatcher=MagicMock(),
    )
    monkeypatch.setattr(service, "_ownership_current", AsyncMock(return_value=True))

    async def callback_admission() -> None:
        async with session_manager() as session:
            await repository.lock_connection_for_routing(
                session,
                connection_id="connection-1",
            )
            await cast(_LockSession, session).acquire(drain_lock)
            await session.commit()

    finalize_task = asyncio.create_task(
        service._finalize_batch(  # noqa: SLF001
            _batch(item),
            prepared=[
                _PreparedFailure(
                    item=item,
                    durable_cursor=None,
                    category=(ExternalChannelIngressFailureCategory.PERMISSION_DENIED),
                    retryable=False,
                    retry_after_seconds=None,
                )
            ],
        ),
        name="batch-finalizer",
    )
    await asyncio.sleep(0)
    admission_task = asyncio.create_task(
        callback_admission(),
        name="callback-admission",
    )

    finalization_stale, _ = await asyncio.wait_for(
        asyncio.gather(finalize_task, admission_task),
        timeout=1,
    )

    assert finalization_stale is False
    assert repository.lock_connection_for_routing.await_args_list[0].args
    assert queue_repository.lock_claimed_batch.await_count == 1


async def test_preparation_locks_connection_before_owner() -> None:
    """Provider completion follows the callback's connection-first lock order."""
    transaction = _Session()
    calls: list[str] = []
    owner = ExternalChannelIngressOwner.model_construct(
        id="owner-1",
        connection_id="connection-1",
        lease_generation=1,
    )
    repository = MagicMock()

    async def lock_connection(
        _session: AsyncSession,
        *,
        connection_id: str,
    ) -> ExternalChannelConnection:
        assert connection_id == owner.connection_id
        calls.append("connection")
        return ExternalChannelConnection.model_construct(id=connection_id)

    repository.lock_connection_for_routing = AsyncMock(side_effect=lock_connection)
    queue_repository = MagicMock()

    async def lock_owner(
        _session: AsyncSession,
        **_kwargs: object,
    ) -> ExternalChannelIngressOwner:
        calls.append("owner")
        return owner

    queue_repository.lock_leased_owner = AsyncMock(side_effect=lock_owner)
    first_item = _item(
        item_id="item-1",
        trigger_key="message-1",
        trigger_position="00000000000000000001",
    )

    async def lock_first_item(
        _session: AsyncSession,
        *,
        owner_id: str,
    ) -> ExternalChannelIngressItem:
        assert owner_id == owner.id
        calls.append("item")
        return first_item

    queue_repository.lock_first_authoritative_item = AsyncMock(
        side_effect=lock_first_item
    )
    queue_repository.mark_owner_ready = AsyncMock()
    provider_control = MagicMock()
    presence_plan = make_provider_effect_plan("joined-presence")
    progress_plan = make_provider_effect_plan("initial-progress")

    async def attempt_control(_plan: object) -> None:
        transaction.commit.assert_awaited_once()

    provider_control.attempt = AsyncMock(side_effect=attempt_control)
    service = _service(
        session_manager=_session_manager(transaction),
        repository=repository,
        queue_repository=queue_repository,
        mailbox_service=MagicMock(),
        agent_session_repository=MagicMock(),
        wake_dispatcher=MagicMock(),
        provider_control=provider_control,
    )
    preparation = object()
    service.provisioning_service.prepare = AsyncMock(return_value=preparation)
    service.provisioning_service.complete = AsyncMock(
        return_value=ExternalChannelConfiguredBindingResult(
            binding=ExternalChannelBinding.model_construct(
                id="binding-1",
                agent_session_id="session-1",
            ),
            session_created=True,
            control_plans=(presence_plan, progress_plan),
        )
    )

    prepared = await service._prepare_owner(  # noqa: SLF001
        owner=owner,
        lease_owner="worker-1",
        lease_generation=1,
    )

    assert prepared
    assert calls == ["connection", "owner", "item"]
    service.provisioning_service.complete.assert_awaited_once_with(
        transaction,
        owner=owner,
        preparation=preparation,
        initial_provider=ExternalChannelProvider.SLACK,
        initial_invocation=True,
    )
    transaction.commit.assert_awaited_once()
    queue_repository.mark_owner_ready.assert_awaited_once_with(
        transaction,
        owner=owner,
        binding_id="binding-1",
        session_id="session-1",
        initial_title_eligible=True,
    )
    assert provider_control.attempt.await_args_list == [
        ((presence_plan,), {}),
        ((progress_plan,), {}),
    ]


async def test_unready_discord_nonmention_starts_hidden_without_progress() -> None:
    """First queued Discord all-messages input creates hidden Work without Tracker."""
    transaction = _Session()
    owner = ExternalChannelIngressOwner.model_construct(
        id="owner-1",
        connection_id="connection-1",
        lease_generation=1,
    )
    first_item = _item(
        item_id="item-1",
        trigger_key="message-1",
        trigger_position="00000000000000000001",
        provider=ExternalChannelProvider.DISCORD,
        invocation=False,
    )
    repository = MagicMock()
    repository.lock_connection_for_routing = AsyncMock(
        return_value=ExternalChannelConnection.model_construct(id="connection-1")
    )
    queue_repository = MagicMock()
    queue_repository.lock_leased_owner = AsyncMock(return_value=owner)
    queue_repository.lock_first_authoritative_item = AsyncMock(return_value=first_item)
    queue_repository.mark_owner_ready = AsyncMock()
    provider_control = MagicMock()
    provider_control.attempt = AsyncMock()
    service = _service(
        session_manager=_session_manager(transaction),
        repository=repository,
        queue_repository=queue_repository,
        mailbox_service=MagicMock(),
        agent_session_repository=MagicMock(),
        wake_dispatcher=MagicMock(),
        provider_control=provider_control,
    )
    preparation = object()
    service.provisioning_service.prepare = AsyncMock(return_value=preparation)
    service.provisioning_service.complete = AsyncMock(
        return_value=ExternalChannelConfiguredBindingResult(
            binding=ExternalChannelBinding.model_construct(
                id="binding-1",
                agent_session_id="session-1",
            ),
            session_created=True,
            control_plans=(),
        )
    )

    prepared = await service._prepare_owner(  # noqa: SLF001
        owner=owner,
        lease_owner="worker-1",
        lease_generation=1,
    )

    assert prepared
    service.provisioning_service.complete.assert_awaited_once_with(
        transaction,
        owner=owner,
        preparation=preparation,
        initial_provider=ExternalChannelProvider.DISCORD,
        initial_invocation=False,
    )
    provider_control.attempt.assert_not_awaited()
    transaction.commit.assert_awaited_once()


async def test_success_covers_earlier_retry_and_dispatches_one_batch_wake(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A later range deletes covered retry work and sends one post-commit wake."""
    failed_item = _item(
        item_id="item-1",
        trigger_key="message-1",
        trigger_position="00000000000000000001",
    )
    successful_item = _item(
        item_id="item-2",
        trigger_key="message-2",
        trigger_position="00000000000000000002",
    )
    failed_row = SimpleNamespace(id=failed_item.id)
    successful_row = SimpleNamespace(id=successful_item.id)
    (
        repository,
        queue_repository,
        mailbox_service,
        agent_session_repository,
        wake_dispatcher,
        _drain,
    ) = _collaborators(locked_rows=[failed_row, successful_row])
    transaction = _Session()
    service = _service(
        session_manager=_session_manager(transaction),
        repository=repository,
        queue_repository=queue_repository,
        mailbox_service=mailbox_service,
        agent_session_repository=agent_session_repository,
        wake_dispatcher=wake_dispatcher,
    )
    monkeypatch.setattr(service, "_ownership_current", AsyncMock(return_value=True))

    stale = await service._finalize_batch(  # noqa: SLF001
        _batch(failed_item, successful_item),
        prepared=[
            _PreparedFailure(
                item=failed_item,
                durable_cursor=None,
                category=ExternalChannelIngressFailureCategory.TEMPORARY_FAILURE,
                retryable=True,
                retry_after_seconds=None,
            ),
            _PreparedSuccess(
                item=successful_item,
                durable_cursor=None,
                history=_history(
                    trigger_key=successful_item.trigger_provider_message_key,
                    trigger_position=successful_item.trigger_position,
                    include_context=True,
                ),
            ),
        ],
    )

    assert stale is False
    queue_repository.move_to_retry_tail.assert_not_awaited()
    finish_args = queue_repository.finish_batch.await_args
    assert finish_args.kwargs["deleted_items"] == [failed_row, successful_row]
    assert mailbox_service.enqueue_many.await_count == 1
    assert len(mailbox_service.enqueue_many.await_args.args[1]) == 2
    repository.advance_conversation_position_if_current.assert_awaited_once_with(
        transaction,
        position_id="position-1",
        expected_read_through_position=None,
        read_through_position="00000000000000000002",
    )
    agent_session_repository.lock_by_id.assert_not_awaited()
    agent_session_repository.admit_input_wakeup.assert_awaited_once_with(
        transaction,
        "session-1",
    )
    transaction.commit.assert_awaited_once()
    wake_dispatcher.dispatch.assert_awaited_once()


async def test_missing_trigger_warns_and_is_ignored_while_batch_continues(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A missing trigger is deleted without mailbox input or blocking later work."""
    missing_item = _item(
        item_id="item-1",
        trigger_key="message-1",
        trigger_position="00000000000000000001",
    )
    successful_item = _item(
        item_id="item-2",
        trigger_key="message-2",
        trigger_position="00000000000000000002",
    )
    missing_row = SimpleNamespace(id=missing_item.id)
    successful_row = SimpleNamespace(id=successful_item.id)
    (
        repository,
        queue_repository,
        mailbox_service,
        agent_session_repository,
        wake_dispatcher,
        _drain,
    ) = _collaborators(locked_rows=[missing_row, successful_row])
    transaction = _Session()
    service = _service(
        session_manager=_session_manager(transaction),
        repository=repository,
        queue_repository=queue_repository,
        mailbox_service=mailbox_service,
        agent_session_repository=agent_session_repository,
        wake_dispatcher=wake_dispatcher,
    )
    monkeypatch.setattr(service, "_ownership_current", AsyncMock(return_value=True))

    with caplog.at_level(
        logging.WARNING,
        logger="azents.services.external_channel.ingress_queue",
    ):
        stale = await service._finalize_batch(  # noqa: SLF001
            _batch(missing_item, successful_item),
            prepared=[
                _PreparedFailure(
                    item=missing_item,
                    durable_cursor=None,
                    category=ExternalChannelIngressFailureCategory.TRIGGER_MISSING,
                    retryable=False,
                    retry_after_seconds=None,
                ),
                _PreparedSuccess(
                    item=successful_item,
                    durable_cursor=None,
                    history=_history(
                        trigger_key=successful_item.trigger_provider_message_key,
                        trigger_position=successful_item.trigger_position,
                    ),
                ),
            ],
        )

    assert stale is False
    queue_repository.move_to_retry_tail.assert_not_awaited()
    finish_args = queue_repository.finish_batch.await_args
    assert finish_args.kwargs["deleted_items"] == [missing_row, successful_row]
    enqueues = mailbox_service.enqueue_many.await_args.args[1]
    assert len(enqueues) == 1
    assert (
        enqueues[0]
        .payload.items[0]
        .metadata["external_channel_message"]["provider_message_key"]
        == successful_item.trigger_provider_message_key
    )
    warning = next(
        record
        for record in caplog.records
        if record.message
        == "External Channel ingress trigger was missing; item ignored"
    )
    assert warning.__dict__["external_channel_ingress_id"] == missing_item.id
    assert warning.__dict__["external_channel_failure_category"] == "trigger_missing"
    transaction.commit.assert_awaited_once()
    wake_dispatcher.dispatch.assert_awaited_once()


@pytest.mark.parametrize(
    "provider",
    [ExternalChannelProvider.SLACK, ExternalChannelProvider.DISCORD],
)
async def test_admitted_all_messages_trigger_is_invocation_with_retained_context(
    monkeypatch: pytest.MonkeyPatch,
    provider: ExternalChannelProvider,
) -> None:
    """A provider-neutral ordinary trigger stays invocation after correlation."""
    item = _item(
        item_id="item-2",
        trigger_key="message-2",
        trigger_position="00000000000000000002",
        invocation=False,
        provider=provider,
    )
    row = SimpleNamespace(id=item.id)
    (
        repository,
        queue_repository,
        mailbox_service,
        agent_session_repository,
        wake_dispatcher,
        _drain,
    ) = _collaborators(locked_rows=[row])
    queue_repository.list_active_correlations.return_value = {
        item.trigger_provider_message_key: ExternalChannelIngressCorrelation(
            invocation_id=item.invocation_id,
            principal_id=item.principal_id,
        )
    }
    transaction = _Session()
    service = _service(
        session_manager=_session_manager(transaction),
        repository=repository,
        queue_repository=queue_repository,
        mailbox_service=mailbox_service,
        agent_session_repository=agent_session_repository,
        wake_dispatcher=wake_dispatcher,
    )
    monkeypatch.setattr(service, "_ownership_current", AsyncMock(return_value=True))

    stale = await service._finalize_batch(  # noqa: SLF001
        _batch(item),
        prepared=[
            _PreparedSuccess(
                item=item,
                durable_cursor=None,
                history=_history(
                    trigger_key=item.trigger_provider_message_key,
                    trigger_position=item.trigger_position,
                    include_context=True,
                ),
            )
        ],
    )

    assert stale is False
    enqueues = mailbox_service.enqueue_many.await_args.args[1]
    messages = [
        enqueue.payload.items[0].metadata["external_channel_message"]
        for enqueue in enqueues
    ]
    assert [
        (message["provider_message_key"], message["prompt_role"])
        for message in messages
    ] == [
        ("context-message", "context"),
        ("message-2", "invocation"),
    ]
    assert messages[0]["principal_id"] is None
    assert messages[1]["principal_id"] == item.principal_id
    assert messages[1]["provider"] == provider.value


async def test_explicit_followup_settings_and_tracker_precede_wake(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An explicit bound follow-up attempts settings then Tracker before wake."""
    item = _item(
        item_id="item-1",
        trigger_key="message-1",
        trigger_position="00000000000000000001",
    )
    row = SimpleNamespace(id=item.id)
    (
        repository,
        queue_repository,
        mailbox_service,
        agent_session_repository,
        wake_dispatcher,
        _drain,
    ) = _collaborators(locked_rows=[row])
    transaction = _Session()
    work_repository = MagicMock()
    work_repository.ensure_active_work = AsyncMock(
        return_value=SimpleNamespace(work_cycle_id="work-followup")
    )
    settings_plan = make_provider_effect_plan("followup-settings")
    work_repository.prepare_direct_control = AsyncMock(return_value=settings_plan)
    progress_plan = make_provider_effect_plan("followup-progress")
    work_repository.prepare_initial_progress = AsyncMock(return_value=progress_plan)
    provider_control = MagicMock()

    async def attempt_control(_plan: object) -> None:
        transaction.commit.assert_awaited_once()
        wake_dispatcher.dispatch.assert_not_awaited()

    provider_control.attempt = AsyncMock(side_effect=attempt_control)
    service = _service(
        session_manager=_session_manager(transaction),
        repository=repository,
        queue_repository=queue_repository,
        mailbox_service=mailbox_service,
        agent_session_repository=agent_session_repository,
        wake_dispatcher=wake_dispatcher,
        work_repository=work_repository,
        provider_control=provider_control,
    )
    monkeypatch.setattr(service, "_ownership_current", AsyncMock(return_value=True))

    stale = await service._finalize_batch(  # noqa: SLF001
        _batch(item),
        prepared=[
            _PreparedSuccess(
                item=item,
                durable_cursor=None,
                history=_history(
                    trigger_key=item.trigger_provider_message_key,
                    trigger_position=item.trigger_position,
                ),
            )
        ],
    )

    assert stale is False
    work_repository.ensure_active_work.assert_awaited_once()
    ensure_call = work_repository.ensure_active_work.await_args
    assert ensure_call is not None
    desired_progress = ensure_call.kwargs["desired_progress"]
    assert desired_progress.state == "checking"
    assert ensure_call.kwargs["tracker_visibility"] == "visible"
    work_repository.prepare_direct_control.assert_awaited_once_with(
        transaction,
        connection_id="connection-1",
        resource_id="resource-1",
        route_id="route-1",
        binding_id="binding-1",
        operation=ExternalChannelDeliveryOperation.CONTROL_MESSAGE,
        request_payload={
            "tenant_id": "tenant-1",
            "channel_id": "channel-1",
            "thread_ts": "thread-1",
            "control_kind": "binding_settings_on_demand",
            "control_version": 3,
        },
        operation_seed="binding-settings:binding-1",
    )
    work_repository.prepare_initial_progress.assert_awaited_once_with(
        transaction,
        agent_id="agent-1",
        session_id="session-1",
        binding_id="binding-1",
        work_cycle_id="work-followup",
    )
    assert provider_control.attempt.await_args_list == [
        ((settings_plan,), {}),
        ((progress_plan,), {}),
    ]
    wake_dispatcher.dispatch.assert_awaited_once()


@pytest.mark.parametrize(
    ("invocation", "initial_title_eligible"),
    [
        (False, False),
        (True, True),
    ],
)
async def test_non_invocation_or_new_binding_does_not_repeat_settings(
    monkeypatch: pytest.MonkeyPatch,
    invocation: bool,
    initial_title_eligible: bool,
) -> None:
    """Continuation and new-Binding ingress retain their existing controls."""
    item = _item(
        item_id="item-1",
        trigger_key="message-1",
        trigger_position="00000000000000000001",
        invocation=invocation,
        initial_title_eligible=initial_title_eligible,
    )
    row = SimpleNamespace(id=item.id)
    (
        repository,
        queue_repository,
        mailbox_service,
        agent_session_repository,
        wake_dispatcher,
        _drain,
    ) = _collaborators(locked_rows=[row])
    transaction = _Session()
    work_repository = MagicMock()
    work_repository.ensure_active_work = AsyncMock(
        return_value=SimpleNamespace(work_cycle_id="work-followup")
    )
    work_repository.prepare_direct_control = AsyncMock()
    work_repository.prepare_initial_progress = AsyncMock(return_value=None)
    service = _service(
        session_manager=_session_manager(transaction),
        repository=repository,
        queue_repository=queue_repository,
        mailbox_service=mailbox_service,
        agent_session_repository=agent_session_repository,
        wake_dispatcher=wake_dispatcher,
        work_repository=work_repository,
    )
    monkeypatch.setattr(service, "_ownership_current", AsyncMock(return_value=True))

    stale = await service._finalize_batch(  # noqa: SLF001
        _batch(item),
        prepared=[
            _PreparedSuccess(
                item=item,
                durable_cursor=None,
                history=_history(
                    trigger_key=item.trigger_provider_message_key,
                    trigger_position=item.trigger_position,
                ),
            )
        ],
    )

    assert stale is False
    work_repository.prepare_direct_control.assert_not_awaited()
    ensure_call = work_repository.ensure_active_work.await_args
    assert ensure_call is not None
    assert ensure_call.kwargs["tracker_visibility"] == "visible"
    wake_dispatcher.dispatch.assert_awaited_once()


async def test_unmentioned_discord_input_requests_hidden_tracker_visibility(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Discord all-messages input starts hidden after canonical mailbox admission."""
    item = _item(
        item_id="item-1",
        trigger_key="message-1",
        trigger_position="00000000000000000001",
        invocation=False,
        provider=ExternalChannelProvider.DISCORD,
    )
    row = SimpleNamespace(id=item.id)
    (
        repository,
        queue_repository,
        mailbox_service,
        agent_session_repository,
        wake_dispatcher,
        _drain,
    ) = _collaborators(locked_rows=[row])
    transaction = _Session()
    work_repository = MagicMock()
    work_repository.ensure_active_work = AsyncMock(
        return_value=SimpleNamespace(work_cycle_id="work-hidden")
    )
    work_repository.prepare_direct_control = AsyncMock(return_value=None)
    work_repository.prepare_initial_progress = AsyncMock(return_value=None)
    service = _service(
        session_manager=_session_manager(transaction),
        repository=repository,
        queue_repository=queue_repository,
        mailbox_service=mailbox_service,
        agent_session_repository=agent_session_repository,
        wake_dispatcher=wake_dispatcher,
        work_repository=work_repository,
    )
    monkeypatch.setattr(service, "_ownership_current", AsyncMock(return_value=True))

    stale = await service._finalize_batch(  # noqa: SLF001
        _batch(item),
        prepared=[
            _PreparedSuccess(
                item=item,
                durable_cursor=None,
                history=_history(
                    trigger_key=item.trigger_provider_message_key,
                    trigger_position=item.trigger_position,
                ),
            )
        ],
    )

    assert stale is False
    ensure_call = work_repository.ensure_active_work.await_args
    assert ensure_call is not None
    assert ensure_call.kwargs["tracker_visibility"] == "hidden"
    work_repository.prepare_initial_progress.assert_awaited_once()


async def test_late_discord_mention_requests_visible_tracker_promotion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One newly admitted Discord mention promotes the finalized active Work."""
    ordinary = _item(
        item_id="item-ordinary",
        trigger_key="message-ordinary",
        trigger_position="00000000000000000001",
        invocation=False,
        provider=ExternalChannelProvider.DISCORD,
    )
    mention = _item(
        item_id="item-mention",
        trigger_key="message-mention",
        trigger_position="00000000000000000002",
        invocation=True,
        provider=ExternalChannelProvider.DISCORD,
    )
    rows = [SimpleNamespace(id=ordinary.id), SimpleNamespace(id=mention.id)]
    (
        repository,
        queue_repository,
        mailbox_service,
        agent_session_repository,
        wake_dispatcher,
        _drain,
    ) = _collaborators(locked_rows=rows)
    transaction = _Session()
    work_repository = MagicMock()
    work_repository.ensure_active_work = AsyncMock(
        return_value=SimpleNamespace(work_cycle_id="work-promoted")
    )
    work_repository.prepare_direct_control = AsyncMock(return_value=None)
    work_repository.prepare_initial_progress = AsyncMock(return_value=None)
    service = _service(
        session_manager=_session_manager(transaction),
        repository=repository,
        queue_repository=queue_repository,
        mailbox_service=mailbox_service,
        agent_session_repository=agent_session_repository,
        wake_dispatcher=wake_dispatcher,
        work_repository=work_repository,
    )
    monkeypatch.setattr(service, "_ownership_current", AsyncMock(return_value=True))

    stale = await service._finalize_batch(  # noqa: SLF001
        _batch(ordinary, mention),
        prepared=[
            _PreparedSuccess(
                item=ordinary,
                durable_cursor=None,
                history=_history(
                    trigger_key=ordinary.trigger_provider_message_key,
                    trigger_position=ordinary.trigger_position,
                ),
            ),
            _PreparedSuccess(
                item=mention,
                durable_cursor=None,
                history=_history(
                    trigger_key=mention.trigger_provider_message_key,
                    trigger_position=mention.trigger_position,
                ),
            ),
        ],
    )

    assert stale is False
    ensure_call = work_repository.ensure_active_work.await_args
    assert ensure_call is not None
    assert ensure_call.kwargs["tracker_visibility"] == "visible"
    work_repository.prepare_initial_progress.assert_awaited_once()


async def test_duplicate_explicit_invocation_does_not_repeat_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A duplicate mailbox admission cannot repeat the settings control."""
    item = _item(
        item_id="item-1",
        trigger_key="message-1",
        trigger_position="00000000000000000001",
    )
    row = SimpleNamespace(id=item.id)
    (
        repository,
        queue_repository,
        mailbox_service,
        agent_session_repository,
        wake_dispatcher,
        _drain,
    ) = _collaborators(locked_rows=[row], mailbox_created=False)
    transaction = _Session()
    work_repository = MagicMock()
    work_repository.prepare_direct_control = AsyncMock()
    work_repository.ensure_active_work = AsyncMock()
    work_repository.prepare_initial_progress = AsyncMock()
    service = _service(
        session_manager=_session_manager(transaction),
        repository=repository,
        queue_repository=queue_repository,
        mailbox_service=mailbox_service,
        agent_session_repository=agent_session_repository,
        wake_dispatcher=wake_dispatcher,
        work_repository=work_repository,
    )
    monkeypatch.setattr(service, "_ownership_current", AsyncMock(return_value=True))

    stale = await service._finalize_batch(  # noqa: SLF001
        _batch(item),
        prepared=[
            _PreparedSuccess(
                item=item,
                durable_cursor=None,
                history=_history(
                    trigger_key=item.trigger_provider_message_key,
                    trigger_position=item.trigger_position,
                ),
            )
        ],
    )

    assert stale is False
    work_repository.prepare_direct_control.assert_not_awaited()
    work_repository.ensure_active_work.assert_not_awaited()
    work_repository.prepare_initial_progress.assert_not_awaited()
    wake_dispatcher.dispatch.assert_awaited_once()


async def test_duplicate_discord_mention_does_not_request_tracker_promotion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A duplicate Discord mention cannot promote Work without new mailbox input."""
    item = _item(
        item_id="item-1",
        trigger_key="message-1",
        trigger_position="00000000000000000001",
        provider=ExternalChannelProvider.DISCORD,
    )
    row = SimpleNamespace(id=item.id)
    (
        repository,
        queue_repository,
        mailbox_service,
        agent_session_repository,
        wake_dispatcher,
        _drain,
    ) = _collaborators(locked_rows=[row], mailbox_created=False)
    transaction = _Session()
    work_repository = MagicMock()
    work_repository.prepare_direct_control = AsyncMock()
    work_repository.ensure_active_work = AsyncMock()
    work_repository.prepare_initial_progress = AsyncMock()
    service = _service(
        session_manager=_session_manager(transaction),
        repository=repository,
        queue_repository=queue_repository,
        mailbox_service=mailbox_service,
        agent_session_repository=agent_session_repository,
        wake_dispatcher=wake_dispatcher,
        work_repository=work_repository,
    )
    monkeypatch.setattr(service, "_ownership_current", AsyncMock(return_value=True))

    stale = await service._finalize_batch(  # noqa: SLF001
        _batch(item),
        prepared=[
            _PreparedSuccess(
                item=item,
                durable_cursor=None,
                history=_history(
                    trigger_key=item.trigger_provider_message_key,
                    trigger_position=item.trigger_position,
                ),
            )
        ],
    )

    assert stale is False
    work_repository.ensure_active_work.assert_not_awaited()
    work_repository.prepare_initial_progress.assert_not_awaited()


async def test_settings_control_failure_does_not_gate_tracker_or_wake(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed settings effect remains post-commit and non-blocking."""
    item = _item(
        item_id="item-1",
        trigger_key="message-1",
        trigger_position="00000000000000000001",
    )
    row = SimpleNamespace(id=item.id)
    (
        repository,
        queue_repository,
        mailbox_service,
        agent_session_repository,
        wake_dispatcher,
        _drain,
    ) = _collaborators(locked_rows=[row])
    transaction = _Session()
    work_repository = MagicMock()
    work_repository.ensure_active_work = AsyncMock(
        return_value=SimpleNamespace(work_cycle_id="work-followup")
    )
    settings_plan = make_provider_effect_plan("followup-settings")
    progress_plan = make_provider_effect_plan("followup-progress")
    work_repository.prepare_direct_control = AsyncMock(return_value=settings_plan)
    work_repository.prepare_initial_progress = AsyncMock(return_value=progress_plan)
    provider_control = MagicMock()
    provider_control.attempt = AsyncMock(
        side_effect=[RuntimeError("provider unavailable"), None]
    )
    service = _service(
        session_manager=_session_manager(transaction),
        repository=repository,
        queue_repository=queue_repository,
        mailbox_service=mailbox_service,
        agent_session_repository=agent_session_repository,
        wake_dispatcher=wake_dispatcher,
        work_repository=work_repository,
        provider_control=provider_control,
    )
    monkeypatch.setattr(service, "_ownership_current", AsyncMock(return_value=True))

    stale = await service._finalize_batch(  # noqa: SLF001
        _batch(item),
        prepared=[
            _PreparedSuccess(
                item=item,
                durable_cursor=None,
                history=_history(
                    trigger_key=item.trigger_provider_message_key,
                    trigger_position=item.trigger_position,
                ),
            )
        ],
    )

    assert stale is False
    transaction.commit.assert_awaited_once()
    assert provider_control.attempt.await_args_list == [
        ((settings_plan,), {}),
        ((progress_plan,), {}),
    ]
    wake_dispatcher.dispatch.assert_awaited_once()


async def test_stale_ownership_does_not_enqueue_or_advance_cursor_and_logs_safely(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A stale prepared success is deleted without cursor loss or content logging."""
    private_body = "private inbound content must not be logged"
    item = _item(
        item_id="item-1",
        trigger_key="message-1",
        trigger_position="00000000000000000001",
    )
    row = SimpleNamespace(id=item.id)
    (
        repository,
        queue_repository,
        mailbox_service,
        agent_session_repository,
        wake_dispatcher,
        _drain,
    ) = _collaborators(locked_rows=[row])
    transaction = _Session()
    service = _service(
        session_manager=_session_manager(transaction),
        repository=repository,
        queue_repository=queue_repository,
        mailbox_service=mailbox_service,
        agent_session_repository=agent_session_repository,
        wake_dispatcher=wake_dispatcher,
    )
    monkeypatch.setattr(service, "_ownership_current", AsyncMock(return_value=False))

    with caplog.at_level(logging.WARNING):
        stale = await service._finalize_batch(  # noqa: SLF001
            _batch(item),
            prepared=[
                _PreparedSuccess(
                    item=item,
                    durable_cursor=None,
                    history=_history(
                        trigger_key=item.trigger_provider_message_key,
                        trigger_position=item.trigger_position,
                        body=private_body,
                    ),
                )
            ],
        )

    assert stale is False
    mailbox_service.enqueue_many.assert_not_awaited()
    repository.advance_conversation_position_if_current.assert_not_awaited()
    agent_session_repository.admit_input_wakeup.assert_not_awaited()
    wake_dispatcher.dispatch.assert_not_awaited()
    assert private_body not in caplog.text
    record = next(
        record
        for record in caplog.records
        if getattr(record, "external_channel_failure_category", None)
        == ExternalChannelIngressFailureCategory.OWNERSHIP_STALE.value
    )
    assert {key for key in record.__dict__ if key.startswith("external_channel_")} == {
        "external_channel_ingress_id",
        "external_channel_provider",
        "external_channel_failure_category",
        "external_channel_attempt_count",
        "external_channel_age_seconds",
    }
    assert record.__dict__["external_channel_ingress_id"] == "item-1"
    assert record.__dict__["external_channel_provider"] == "slack"
    assert record.__dict__["external_channel_attempt_count"] == 1
    age_seconds = record.__dict__["external_channel_age_seconds"]
    assert isinstance(age_seconds, int)
    assert age_seconds >= 0


def test_retry_transition_bounds_attempt_age_and_provider_delay() -> None:
    """Retry timing preserves bounded attempts and the original five-minute age."""
    item = _item(
        item_id="item-1",
        trigger_key="message-1",
        trigger_position="00000000000000000001",
        created_at=_NOW - datetime.timedelta(minutes=1),
    )
    failure = _PreparedFailure(
        item=item,
        durable_cursor=None,
        category=ExternalChannelIngressFailureCategory.TEMPORARY_FAILURE,
        retryable=True,
        retry_after_seconds=None,
    )

    transition = _retry_transition(failure, now=_NOW)

    assert transition is not None
    assert _NOW + datetime.timedelta(seconds=1) < transition
    assert transition < _NOW + datetime.timedelta(seconds=3)
    assert (
        _retry_transition(
            _PreparedFailure(
                item=item.model_copy(update={"attempt_count": 5}),
                durable_cursor=None,
                category=failure.category,
                retryable=True,
                retry_after_seconds=None,
            ),
            now=_NOW,
        )
        is None
    )
    assert (
        _retry_transition(
            _PreparedFailure(
                item=item.model_copy(
                    update={"created_at": _NOW - datetime.timedelta(minutes=5)}
                ),
                durable_cursor=None,
                category=failure.category,
                retryable=True,
                retry_after_seconds=None,
            ),
            now=_NOW,
        )
        is None
    )
    assert (
        _retry_transition(
            _PreparedFailure(
                item=item,
                durable_cursor=None,
                category=failure.category,
                retryable=True,
                retry_after_seconds=300,
            ),
            now=_NOW,
        )
        is None
    )


def test_provider_failure_classification_drops_raw_exception_text() -> None:
    """Failure state retains only the closed category, never provider text."""
    private_text = "provider response contained private inbound content"
    failure = _provider_failure(
        item=_item(
            item_id="item-1",
            trigger_key="message-1",
            trigger_position="00000000000000000001",
        ),
        durable_cursor=None,
        error=ExternalChannelHistoryPermissionDenied(private_text),
    )

    assert failure.category is ExternalChannelIngressFailureCategory.PERMISSION_DENIED
    assert private_text not in repr(failure)
