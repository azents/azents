"""Tests for provider-neutral synchronous conversation ingestion."""

import datetime
from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass, field, replace

import pytest

from azents.core.enums import (
    ExternalChannelConversationScopeKind,
    ExternalChannelIngressProfile,
    ExternalChannelMessageLifecycle,
    ExternalChannelMessageRevisionKind,
    ExternalChannelPrincipalAuthorType,
    ExternalChannelProvider,
)
from azents.services.external_channel.conversation import (
    ExternalChannelConversationLockError,
    ExternalChannelConversationLockLease,
    ExternalChannelConversationScope,
    ExternalChannelHistoryRange,
    ExternalChannelHistoryTemporaryFailure,
    ExternalChannelOperationDeadline,
)
from azents.services.external_channel.conversation_lock import (
    InMemoryExternalChannelConversationLock,
)
from azents.services.external_channel.ingestion import (
    ExternalChannelCanonicalHistoryMessage,
    ExternalChannelConversationIngestionService,
    ExternalChannelIngestionActivation,
    ExternalChannelIngestionAdmission,
    ExternalChannelIngestionOperation,
    ExternalChannelIngestionOutcome,
    ExternalChannelIngestionOutcomeKind,
    ExternalChannelIngestionPreparation,
    ExternalChannelIngestionReason,
    ExternalChannelIngestionRequest,
    ExternalChannelIngressAuthority,
    ExternalChannelIngressAuthorityKind,
    ExternalChannelReplayBoundary,
    ExternalChannelRequiredDeliveryResult,
    ExternalChannelTriggerLocator,
    ExternalChannelWakeDispatchResult,
)


@dataclass
class _Lease:
    assertions: int = 0

    async def assert_owned(self) -> None:
        self.assertions += 1


@dataclass
class _Lock:
    lease: _Lease = field(default_factory=_Lease)

    def acquire(
        self,
        *,
        scope: ExternalChannelConversationScope,
        deadline: ExternalChannelOperationDeadline,
    ) -> AbstractAsyncContextManager[ExternalChannelConversationLockLease]:
        del scope, deadline

        @asynccontextmanager
        async def owned() -> AsyncIterator[ExternalChannelConversationLockLease]:
            yield self.lease

        return owned()


@dataclass
class _LosingLease:
    assertions: int = 0

    async def assert_owned(self) -> None:
        self.assertions += 1
        if self.assertions >= 3:
            raise ExternalChannelConversationLockError(
                "Conversation authority was lost."
            )


@dataclass
class _AuthorityLossLock:
    lease: _LosingLease = field(default_factory=_LosingLease)

    def acquire(
        self,
        *,
        scope: ExternalChannelConversationScope,
        deadline: ExternalChannelOperationDeadline,
    ) -> AbstractAsyncContextManager[ExternalChannelConversationLockLease]:
        del scope, deadline

        @asynccontextmanager
        async def owned() -> AsyncIterator[ExternalChannelConversationLockLease]:
            yield self.lease

        return owned()


@dataclass
class _History:
    calls: list[str | None] = field(default_factory=list)
    failure: bool = False

    async def read_range(
        self,
        *,
        locator: ExternalChannelTriggerLocator,
        exclusive_start_position: str | None,
        deadline: ExternalChannelOperationDeadline,
    ) -> ExternalChannelHistoryRange[ExternalChannelCanonicalHistoryMessage]:
        del deadline
        self.calls.append(exclusive_start_position)
        if self.failure:
            raise ExternalChannelHistoryTemporaryFailure(
                "Provider history is unavailable."
            )
        message = _message(
            provider_message_key=locator.trigger_provider_message_key,
            provider_position=locator.trigger_position,
        )
        return ExternalChannelHistoryRange(
            messages=(message,),
            trigger=message,
            context_omitted=False,
            range_start_position=exclusive_start_position,
            trigger_position=locator.trigger_position,
            provider_request_count=1,
            scanned_message_count=1,
            elapsed_seconds=0,
        )


@dataclass
class _Store:
    preparations: list[ExternalChannelIngestionPreparation]
    stages: list[ExternalChannelIngestionAdmission]
    acceptances: list[ExternalChannelIngestionActivation]
    staged_starts: list[str | None] = field(default_factory=list)
    finalized_starts: list[str | None] = field(default_factory=list)
    blocked_activation_ids: list[str] = field(default_factory=list)

    async def prepare(
        self,
        *,
        request: ExternalChannelIngestionRequest,
    ) -> ExternalChannelIngestionPreparation:
        del request
        return self.preparations.pop(0)

    async def admit(
        self,
        *,
        request: ExternalChannelIngestionRequest,
        preparation: ExternalChannelIngestionPreparation,
        history: ExternalChannelHistoryRange[ExternalChannelCanonicalHistoryMessage],
    ) -> ExternalChannelIngestionAdmission:
        del request, history
        self.staged_starts.append(preparation.exclusive_start_position)
        return self.stages.pop(0)

    async def activate(
        self,
        *,
        request: ExternalChannelIngestionRequest,
        preparation: ExternalChannelIngestionPreparation,
        history: ExternalChannelHistoryRange[ExternalChannelCanonicalHistoryMessage],
        stage: ExternalChannelIngestionAdmission,
    ) -> ExternalChannelIngestionActivation:
        del request, history, stage
        self.finalized_starts.append(preparation.exclusive_start_position)
        return self.acceptances.pop(0)

    async def block(
        self,
        *,
        stage: ExternalChannelIngestionAdmission,
        reason: ExternalChannelIngestionReason,
    ) -> None:
        del reason
        if stage.activation_id is None:
            raise ValueError("Activation identity is required.")
        self.blocked_activation_ids.append(stage.activation_id)


@dataclass
class _RequiredDeliveryCoordinator:
    results: list[ExternalChannelRequiredDeliveryResult] = field(default_factory=list)
    calls: list[str] = field(default_factory=list)

    async def ensure_delivered(
        self,
        *,
        delivery_attempt_id: str,
        deadline: ExternalChannelOperationDeadline,
    ) -> ExternalChannelRequiredDeliveryResult:
        del deadline
        self.calls.append(delivery_attempt_id)
        return self.results.pop(0) if self.results else "delivered"


class _ExpiringDeadline(ExternalChannelOperationDeadline):
    """Expose budget for memory-lock acquisition, then expire before finalization."""

    calls: int

    def __init__(self) -> None:
        super().__init__(
            datetime.datetime.now(datetime.UTC) + datetime.timedelta(seconds=30)
        )
        object.__setattr__(self, "calls", 0)

    def remaining_seconds(
        self,
        *,
        now: datetime.datetime | None = None,
    ) -> float:
        del now
        calls = self.calls + 1
        object.__setattr__(self, "calls", calls)
        return 30.0 if calls == 1 else 0.0


@dataclass
class _WakeDispatcher:
    results: list[ExternalChannelWakeDispatchResult] = field(
        default_factory=lambda: ["dispatched"]
    )
    calls: list[tuple[str, str]] = field(default_factory=list)

    async def dispatch(
        self,
        *,
        mailbox_item_id: str,
        session_id: str,
        now: datetime.datetime,
        deadline: ExternalChannelOperationDeadline,
    ) -> ExternalChannelWakeDispatchResult:
        del now, deadline
        self.calls.append((mailbox_item_id, session_id))
        return self.results.pop(0)


def _message(
    *,
    provider_message_key: str,
    provider_position: str,
) -> ExternalChannelCanonicalHistoryMessage:
    return ExternalChannelCanonicalHistoryMessage(
        provider_message_key=provider_message_key,
        provider_position=provider_position,
        revision_key=f"{provider_message_key}:original",
        revision_kind=ExternalChannelMessageRevisionKind.ORIGINAL,
        lifecycle=ExternalChannelMessageLifecycle.CURRENT,
        author_type=ExternalChannelPrincipalAuthorType.HUMAN,
        provider_user_id="participant",
        sender_display_name="Participant",
        normalized_body="provider history body",
        attachment_metadata=None,
        reference_mappings=None,
        normalized_size=21,
        provider_created_at=datetime.datetime(2026, 7, 29, tzinfo=datetime.UTC),
        provider_updated_at=None,
        original_url=None,
    )


def _request(
    *,
    operation: ExternalChannelIngestionOperation = (
        ExternalChannelIngestionOperation.CURRENT_TRIGGER
    ),
) -> ExternalChannelIngestionRequest:
    locator = ExternalChannelTriggerLocator(
        connection_id="connection-1",
        provider=ExternalChannelProvider.SLACK,
        provider_tenant_id="tenant-1",
        provider_channel_id="channel-1",
        provider_parent_channel_id=None,
        provider_thread_key="thread-1",
        delivery_thread_key="thread-1",
        provider_resource_key="resource-key-1",
        trigger_provider_message_key="message-key-2",
        trigger_provider_message_id="2.000000",
        trigger_position="00000000000000000002",
        provider_user_id="participant",
        invocation=True,
    )
    return ExternalChannelIngestionRequest(
        locator=locator,
        scope=ExternalChannelConversationScope(
            connection_id=locator.connection_id,
            kind=ExternalChannelConversationScopeKind.THREAD,
            provider_channel_id=locator.provider_channel_id,
            provider_thread_key=locator.provider_thread_key,
        ),
        authority=ExternalChannelIngressAuthority(
            kind=ExternalChannelIngressAuthorityKind.CONFIGURATION,
            ingress_profile=ExternalChannelIngressProfile.SLACK_HTTP,
            configuration_generation=3,
            lease_owner=None,
            lease_generation=None,
        ),
        deadline=ExternalChannelOperationDeadline(
            datetime.datetime.now(datetime.UTC) + datetime.timedelta(seconds=30)
        ),
        operation=operation,
        selected_route_id=("route-1" if operation.value != "current_trigger" else None),
        replay_boundary=(
            None
            if operation is ExternalChannelIngestionOperation.CURRENT_TRIGGER
            else ExternalChannelReplayBoundary(
                connection_id="connection-1",
                resource_id="resource-1",
                principal_id="principal-1",
                trigger_provider_message_key="message-1",
                conversation_position_id="position-1",
                range_start_position="00000000000000000001",
                trigger_position="00000000000000000002",
            )
        ),
    )


@pytest.mark.parametrize(
    ("kind", "profile"),
    [
        (
            ExternalChannelIngressAuthorityKind.CONFIGURATION,
            ExternalChannelIngressProfile.SLACK_SOCKET,
        ),
        (
            ExternalChannelIngressAuthorityKind.CONFIGURATION,
            ExternalChannelIngressProfile.DISCORD_GATEWAY_HTTP,
        ),
        (
            ExternalChannelIngressAuthorityKind.LEASE,
            ExternalChannelIngressProfile.SLACK_HTTP,
        ),
    ],
)
def test_ingress_authority_rejects_invalid_kind_profile_combinations(
    kind: ExternalChannelIngressAuthorityKind,
    profile: ExternalChannelIngressProfile,
) -> None:
    with pytest.raises(ValueError):
        ExternalChannelIngressAuthority(
            kind=kind,
            ingress_profile=profile,
            configuration_generation=1,
            lease_owner=(
                "owner-1" if kind is ExternalChannelIngressAuthorityKind.LEASE else None
            ),
            lease_generation=(
                None
                if profile is ExternalChannelIngressProfile.SLACK_SOCKET
                else 1
                if kind is ExternalChannelIngressAuthorityKind.LEASE
                else None
            ),
        )


async def test_ingestion_restarts_history_after_position_mismatch() -> None:
    lock = _Lock()
    history = _History()
    store = _Store(
        preparations=[
            ExternalChannelIngestionPreparation(
                position_id="position-1",
                exclusive_start_position="00000000000000000000",
                activation_id=None,
                immediate_outcome=None,
                wake_mailbox_item_id=None,
                wake_session_id=None,
            ),
            ExternalChannelIngestionPreparation(
                position_id="position-1",
                exclusive_start_position="00000000000000000001",
                activation_id=None,
                immediate_outcome=None,
                wake_mailbox_item_id=None,
                wake_session_id=None,
            ),
        ],
        stages=[
            ExternalChannelIngestionAdmission(
                status="position_mismatch",
                reason=ExternalChannelIngestionReason.POSITION_CHANGED,
                activation_id=None,
                binding_id=None,
                session_id=None,
                mailbox_item_id=None,
                required_delivery_attempt_ids=(),
                control_delivery_attempt_id=None,
                connection_id=None,
            ),
            ExternalChannelIngestionAdmission(
                status="ready",
                reason=ExternalChannelIngestionReason.ACCEPTED,
                activation_id="activation-1",
                binding_id="binding-1",
                session_id="session-1",
                mailbox_item_id="mailbox-1",
                required_delivery_attempt_ids=("session-link-1", "progress-1"),
                control_delivery_attempt_id=None,
                connection_id=None,
            ),
        ],
        acceptances=[
            ExternalChannelIngestionActivation(
                status="accepted",
                reason=ExternalChannelIngestionReason.ACCEPTED,
                mailbox_item_id="batch-1",
                session_id="session-1",
                control_delivery_attempt_id=None,
                connection_id=None,
            ),
        ],
    )
    wake = _WakeDispatcher()
    service = ExternalChannelConversationIngestionService(
        conversation_lock=lock,
        history_reader=history,
        store=store,
        required_delivery_coordinator=_RequiredDeliveryCoordinator(),
        wake_dispatcher=wake,
    )

    outcome = await service.ingest(_request())

    assert outcome == ExternalChannelIngestionOutcome(
        kind=ExternalChannelIngestionOutcomeKind.ACCEPTED,
        reason=ExternalChannelIngestionReason.ACCEPTED,
        mailbox_item_id="batch-1",
        control_delivery_attempt_id=None,
        connection_id=None,
    )
    assert history.calls == [
        "00000000000000000000",
        "00000000000000000001",
    ]
    assert store.staged_starts == history.calls
    assert store.finalized_starts == ["00000000000000000001"]
    assert wake.calls == [("batch-1", "session-1")]
    assert lock.lease.assertions == 5


async def test_required_delivery_failure_stops_before_finalize_and_wake() -> None:
    store = _Store(
        preparations=[
            ExternalChannelIngestionPreparation(
                position_id="position-1",
                exclusive_start_position=None,
                activation_id=None,
                immediate_outcome=None,
                wake_mailbox_item_id=None,
                wake_session_id=None,
            )
        ],
        stages=[
            ExternalChannelIngestionAdmission(
                status="ready",
                reason=ExternalChannelIngestionReason.ACCEPTED,
                activation_id="activation-1",
                binding_id="binding-1",
                session_id="session-1",
                mailbox_item_id="mailbox-1",
                required_delivery_attempt_ids=("session-link-1", "progress-1"),
                control_delivery_attempt_id=None,
                connection_id=None,
            )
        ],
        acceptances=[],
    )
    delivery = _RequiredDeliveryCoordinator(results=["delivered", "terminal_failure"])
    wake = _WakeDispatcher()
    service = ExternalChannelConversationIngestionService(
        conversation_lock=_Lock(),
        history_reader=_History(),
        store=store,
        required_delivery_coordinator=delivery,
        wake_dispatcher=wake,
    )

    outcome = await service.ingest(_request())

    assert outcome.kind is ExternalChannelIngestionOutcomeKind.TERMINAL_REJECTION
    assert outcome.reason is ExternalChannelIngestionReason.INITIAL_DELIVERY_UNAVAILABLE
    assert delivery.calls == ["session-link-1", "progress-1"]
    assert store.finalized_starts == []
    assert store.blocked_activation_ids == ["activation-1"]
    assert wake.calls == []


async def test_expired_deadline_stops_before_finalize_with_memory_lock() -> None:
    store = _Store(
        preparations=[
            ExternalChannelIngestionPreparation(
                position_id="position-1",
                exclusive_start_position=None,
                activation_id=None,
                immediate_outcome=None,
                wake_mailbox_item_id=None,
                wake_session_id=None,
            )
        ],
        stages=[
            ExternalChannelIngestionAdmission(
                status="ready",
                reason=ExternalChannelIngestionReason.ACCEPTED,
                activation_id="activation-1",
                binding_id="binding-1",
                session_id="session-1",
                mailbox_item_id="mailbox-1",
                required_delivery_attempt_ids=("session-link-1",),
                control_delivery_attempt_id=None,
                connection_id=None,
            )
        ],
        acceptances=[],
    )
    delivery = _RequiredDeliveryCoordinator(results=["delivered"])
    wake = _WakeDispatcher()
    service = ExternalChannelConversationIngestionService(
        conversation_lock=InMemoryExternalChannelConversationLock(),
        history_reader=_History(),
        store=store,
        required_delivery_coordinator=delivery,
        wake_dispatcher=wake,
    )
    request = replace(_request(), deadline=_ExpiringDeadline())

    outcome = await service.ingest(request)

    assert outcome.kind is ExternalChannelIngestionOutcomeKind.RETRYABLE_FAILURE
    assert outcome.reason is ExternalChannelIngestionReason.INITIAL_DELIVERY_UNAVAILABLE
    assert delivery.calls == ["session-link-1"]
    assert store.finalized_starts == []
    assert wake.calls == []


async def test_authority_loss_after_delivery_stops_before_activation() -> None:
    store = _Store(
        preparations=[
            ExternalChannelIngestionPreparation(
                position_id="position-1",
                exclusive_start_position=None,
                activation_id=None,
                immediate_outcome=None,
                wake_mailbox_item_id=None,
                wake_session_id=None,
            )
        ],
        stages=[
            ExternalChannelIngestionAdmission(
                status="ready",
                reason=ExternalChannelIngestionReason.ACCEPTED,
                activation_id="activation-1",
                binding_id="binding-1",
                session_id="session-1",
                mailbox_item_id="mailbox-1",
                required_delivery_attempt_ids=("session-link-1", "progress-1"),
                control_delivery_attempt_id=None,
                connection_id=None,
            )
        ],
        acceptances=[],
    )
    delivery = _RequiredDeliveryCoordinator(results=["delivered", "delivered"])
    wake = _WakeDispatcher()
    service = ExternalChannelConversationIngestionService(
        conversation_lock=_AuthorityLossLock(),
        history_reader=_History(),
        store=store,
        required_delivery_coordinator=delivery,
        wake_dispatcher=wake,
    )

    outcome = await service.ingest(_request())

    assert outcome.kind is ExternalChannelIngestionOutcomeKind.RETRYABLE_FAILURE
    assert outcome.reason is ExternalChannelIngestionReason.COORDINATION_UNAVAILABLE
    assert delivery.calls == ["session-link-1", "progress-1"]
    assert store.finalized_starts == []
    assert wake.calls == []


async def test_terminal_activation_revalidation_blocks_retained_input() -> None:
    """A terminal post-delivery revalidation cannot leave initialization open."""
    store = _Store(
        preparations=[
            ExternalChannelIngestionPreparation(
                position_id="position-1",
                exclusive_start_position=None,
                activation_id=None,
                immediate_outcome=None,
                wake_mailbox_item_id=None,
                wake_session_id=None,
            )
        ],
        stages=[
            ExternalChannelIngestionAdmission(
                status="ready",
                reason=ExternalChannelIngestionReason.ACCEPTED,
                activation_id="activation-1",
                binding_id="binding-1",
                session_id="session-1",
                mailbox_item_id="mailbox-1",
                required_delivery_attempt_ids=("session-link-1",),
                control_delivery_attempt_id=None,
                connection_id=None,
            )
        ],
        acceptances=[
            ExternalChannelIngestionActivation(
                status="terminal_rejection",
                reason=ExternalChannelIngestionReason.INGRESS_AUTHORITY_STALE,
                mailbox_item_id=None,
                session_id=None,
                control_delivery_attempt_id=None,
                connection_id=None,
            )
        ],
    )
    wake = _WakeDispatcher()
    service = ExternalChannelConversationIngestionService(
        conversation_lock=_Lock(),
        history_reader=_History(),
        store=store,
        required_delivery_coordinator=_RequiredDeliveryCoordinator(),
        wake_dispatcher=wake,
    )

    outcome = await service.ingest(_request())

    assert outcome.kind is ExternalChannelIngestionOutcomeKind.TERMINAL_REJECTION
    assert outcome.reason is ExternalChannelIngestionReason.INGRESS_AUTHORITY_STALE
    assert store.blocked_activation_ids == ["activation-1"]
    assert wake.calls == []


async def test_duplicate_recovers_pending_wake_without_history_read() -> None:
    history = _History()
    wake = _WakeDispatcher(results=["already_dispatched"])
    service = ExternalChannelConversationIngestionService(
        conversation_lock=_Lock(),
        history_reader=history,
        store=_Store(
            preparations=[
                ExternalChannelIngestionPreparation(
                    position_id=None,
                    exclusive_start_position=None,
                    activation_id=None,
                    immediate_outcome=ExternalChannelIngestionOutcome(
                        kind=ExternalChannelIngestionOutcomeKind.DUPLICATE,
                        reason=ExternalChannelIngestionReason.DUPLICATE,
                        mailbox_item_id="batch-1",
                        control_delivery_attempt_id=None,
                        connection_id=None,
                    ),
                    wake_mailbox_item_id="batch-1",
                    wake_session_id="session-1",
                )
            ],
            stages=[],
            acceptances=[],
        ),
        required_delivery_coordinator=_RequiredDeliveryCoordinator(),
        wake_dispatcher=wake,
    )

    outcome = await service.ingest(_request())

    assert outcome.kind is ExternalChannelIngestionOutcomeKind.DUPLICATE
    assert history.calls == []
    assert wake.calls == [("batch-1", "session-1")]


async def test_concurrent_wake_claim_is_retryable() -> None:
    wake = _WakeDispatcher(results=["claimed_elsewhere"])
    service = ExternalChannelConversationIngestionService(
        conversation_lock=_Lock(),
        history_reader=_History(),
        store=_Store(
            preparations=[
                ExternalChannelIngestionPreparation(
                    position_id=None,
                    exclusive_start_position=None,
                    activation_id=None,
                    immediate_outcome=ExternalChannelIngestionOutcome(
                        kind=ExternalChannelIngestionOutcomeKind.DUPLICATE,
                        reason=ExternalChannelIngestionReason.DUPLICATE,
                        mailbox_item_id="batch-1",
                        control_delivery_attempt_id=None,
                        connection_id=None,
                    ),
                    wake_mailbox_item_id="batch-1",
                    wake_session_id="session-1",
                )
            ],
            stages=[],
            acceptances=[],
        ),
        required_delivery_coordinator=_RequiredDeliveryCoordinator(),
        wake_dispatcher=wake,
    )

    outcome = await service.ingest(_request())

    assert outcome.kind is ExternalChannelIngestionOutcomeKind.RETRYABLE_FAILURE
    assert outcome.reason is ExternalChannelIngestionReason.WAKE_DISPATCH_PENDING


async def test_history_failure_returns_retryable_outcome() -> None:
    service = ExternalChannelConversationIngestionService(
        conversation_lock=_Lock(),
        history_reader=_History(failure=True),
        store=_Store(
            preparations=[
                ExternalChannelIngestionPreparation(
                    position_id="position-1",
                    exclusive_start_position=None,
                    activation_id=None,
                    immediate_outcome=None,
                    wake_mailbox_item_id=None,
                    wake_session_id=None,
                )
            ],
            stages=[],
            acceptances=[],
        ),
        required_delivery_coordinator=_RequiredDeliveryCoordinator(),
        wake_dispatcher=_WakeDispatcher(),
    )

    outcome = await service.ingest(_request())

    assert outcome.kind is ExternalChannelIngestionOutcomeKind.RETRYABLE_FAILURE
    assert outcome.reason is ExternalChannelIngestionReason.HISTORY_UNAVAILABLE


def test_locator_and_replay_representations_are_content_free() -> None:
    request = _request(operation=ExternalChannelIngestionOperation.ACCESS_ALLOW)

    rendered = repr(request)

    assert "tenant-1" not in rendered
    assert "channel-1" not in rendered
    assert "thread-1" not in rendered
    assert "participant" not in rendered
    assert "resource-1" not in repr(request.replay_boundary)


def test_current_trigger_rejects_replay_boundary() -> None:
    request = _request(operation=ExternalChannelIngestionOperation.ACCESS_ALLOW)

    with pytest.raises(ValueError, match="cannot carry"):
        ExternalChannelIngestionRequest(
            locator=request.locator,
            scope=request.scope,
            authority=request.authority,
            deadline=request.deadline,
            operation=ExternalChannelIngestionOperation.CURRENT_TRIGGER,
            selected_route_id=None,
            replay_boundary=request.replay_boundary,
        )
