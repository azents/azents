"""Tests for provider-neutral synchronous conversation ingestion."""

import datetime
from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass, field, replace

import pytest

from azents.core.enums import (
    ExternalChannelConversationLocation,
    ExternalChannelConversationScopeKind,
    ExternalChannelIngressProfile,
    ExternalChannelMessageLifecycle,
    ExternalChannelMessageRevisionKind,
    ExternalChannelPrincipalAuthorType,
    ExternalChannelProvider,
)
from azents.services.external_channel.conversation import (
    ExternalChannelConversationLockLease,
    ExternalChannelConversationScope,
    ExternalChannelHistoryRange,
    ExternalChannelHistoryTemporaryFailure,
    ExternalChannelOperationDeadline,
    ExternalChannelParticipationScope,
)
from azents.services.external_channel.ingestion import (
    ExternalChannelCanonicalHistoryMessage,
    ExternalChannelConversationIngestionService,
    ExternalChannelIngestionAcceptance,
    ExternalChannelIngestionOperation,
    ExternalChannelIngestionOutcome,
    ExternalChannelIngestionOutcomeKind,
    ExternalChannelIngestionPreparation,
    ExternalChannelIngestionReason,
    ExternalChannelIngestionRequest,
    ExternalChannelIngressAuthority,
    ExternalChannelIngressAuthorityKind,
    ExternalChannelReplayBoundary,
    ExternalChannelSetupReplayBoundary,
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
        scope: ExternalChannelConversationScope | ExternalChannelParticipationScope,
        deadline: ExternalChannelOperationDeadline,
    ) -> AbstractAsyncContextManager[ExternalChannelConversationLockLease]:
        del scope, deadline

        @asynccontextmanager
        async def owned() -> AsyncIterator[ExternalChannelConversationLockLease]:
            yield self.lease

        return owned()


@dataclass
class _EventLease:
    name: str
    events: list[str]

    async def assert_owned(self) -> None:
        self.events.append(f"{self.name}:assert")


@dataclass
class _EventLock:
    name: str
    events: list[str]

    def acquire(
        self,
        *,
        scope: ExternalChannelConversationScope | ExternalChannelParticipationScope,
        deadline: ExternalChannelOperationDeadline,
    ) -> AbstractAsyncContextManager[ExternalChannelConversationLockLease]:
        del scope, deadline

        @asynccontextmanager
        async def owned() -> AsyncIterator[ExternalChannelConversationLockLease]:
            self.events.append(f"{self.name}:enter")
            try:
                yield _EventLease(self.name, self.events)
            finally:
                self.events.append(f"{self.name}:exit")

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
    acceptances: list[ExternalChannelIngestionAcceptance]
    accepted_starts: list[str | None] = field(default_factory=list)

    async def prepare(
        self,
        *,
        request: ExternalChannelIngestionRequest,
    ) -> ExternalChannelIngestionPreparation:
        del request
        return self.preparations.pop(0)

    async def accept(
        self,
        *,
        request: ExternalChannelIngestionRequest,
        preparation: ExternalChannelIngestionPreparation,
        history: ExternalChannelHistoryRange[ExternalChannelCanonicalHistoryMessage],
    ) -> ExternalChannelIngestionAcceptance:
        del request, history
        self.accepted_starts.append(preparation.exclusive_start_position)
        return self.acceptances.pop(0)


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


@dataclass
class _EventHistory:
    events: list[str]

    async def read_range(
        self,
        *,
        locator: ExternalChannelTriggerLocator,
        exclusive_start_position: str | None,
        deadline: ExternalChannelOperationDeadline,
    ) -> ExternalChannelHistoryRange[ExternalChannelCanonicalHistoryMessage]:
        del exclusive_start_position, deadline
        self.events.append(f"history:{locator.trigger_provider_message_key}")
        message = _message(
            provider_message_key=locator.trigger_provider_message_key,
            provider_position=locator.trigger_position,
        )
        return ExternalChannelHistoryRange(
            messages=(message,),
            trigger=message,
            context_omitted=False,
            range_start_position=None,
            trigger_position=locator.trigger_position,
            provider_request_count=1,
            scanned_message_count=1,
            elapsed_seconds=0,
        )


@dataclass
class _EventStore:
    events: list[str]
    priority_request: ExternalChannelIngestionRequest | None = None

    async def prepare(
        self,
        *,
        request: ExternalChannelIngestionRequest,
    ) -> ExternalChannelIngestionPreparation:
        self.events.append(f"prepare:{request.operation.value}")
        if (
            request.operation is ExternalChannelIngestionOperation.CURRENT_TRIGGER
            and self.priority_request is not None
        ):
            priority = self.priority_request
            self.priority_request = None
            return ExternalChannelIngestionPreparation(
                position_id=None,
                exclusive_start_position=None,
                immediate_outcome=None,
                wake_mailbox_item_id=None,
                wake_session_id=None,
                priority_request=priority,
            )
        return ExternalChannelIngestionPreparation(
            position_id=f"position:{request.operation.value}",
            exclusive_start_position=None,
            immediate_outcome=None,
            wake_mailbox_item_id=None,
            wake_session_id=None,
            priority_request=None,
        )

    async def accept(
        self,
        *,
        request: ExternalChannelIngestionRequest,
        preparation: ExternalChannelIngestionPreparation,
        history: ExternalChannelHistoryRange[ExternalChannelCanonicalHistoryMessage],
    ) -> ExternalChannelIngestionAcceptance:
        del preparation, history
        self.events.append(f"accept:{request.operation.value}")
        return ExternalChannelIngestionAcceptance(
            status="accepted",
            reason=ExternalChannelIngestionReason.ACCEPTED,
            mailbox_item_id=f"mailbox:{request.operation.value}",
            session_id=f"session:{request.operation.value}",
            control_delivery_attempt_id=None,
            connection_id=None,
        )


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
        provider_event_type="app_mention",
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
        initial_title_eligible=False,
    )


def _parent_request() -> ExternalChannelIngestionRequest:
    request = _request()
    return replace(
        request,
        locator=replace(
            request.locator,
            provider_parent_channel_id="channel-1",
            provider_thread_key=None,
            delivery_thread_key="00000000000000000002",
        ),
        scope=ExternalChannelConversationScope(
            connection_id=request.locator.connection_id,
            kind=ExternalChannelConversationScopeKind.PARENT_CHANNEL,
            provider_channel_id=request.locator.provider_channel_id,
            provider_thread_key=None,
        ),
    )


def _setup_request() -> ExternalChannelIngestionRequest:
    request = _parent_request()
    locator = replace(
        request.locator,
        trigger_provider_message_key="message-key-1",
        trigger_provider_message_id="1.000000",
        trigger_position="00000000000000000001",
        delivery_thread_key="00000000000000000001",
    )
    return ExternalChannelIngestionRequest(
        locator=locator,
        scope=request.scope,
        authority=replace(
            request.authority,
            kind=ExternalChannelIngressAuthorityKind.DURABLE_REPLAY,
        ),
        deadline=request.deadline,
        operation=ExternalChannelIngestionOperation.SETUP_CONTINUATION,
        selected_route_id="route-1",
        replay_boundary=ExternalChannelSetupReplayBoundary(
            connection_id=locator.connection_id,
            claim_id="claim-1",
            expected_claim_generation=1,
            selected_source_revision=2,
            setting_id="setting-1",
            settings_generation=1,
            location=ExternalChannelConversationLocation.CHANNEL,
            source_resource_id="source-resource-1",
            target_resource_id="parent-resource-1",
            principal_id="principal-1",
            trigger_provider_message_key=locator.trigger_provider_message_key,
            conversation_position_id="position-1",
            range_start_position=None,
            trigger_position=locator.trigger_position,
        ),
        initial_title_eligible=False,
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
                immediate_outcome=None,
                wake_mailbox_item_id=None,
                wake_session_id=None,
                priority_request=None,
            ),
            ExternalChannelIngestionPreparation(
                position_id="position-1",
                exclusive_start_position="00000000000000000001",
                immediate_outcome=None,
                wake_mailbox_item_id=None,
                wake_session_id=None,
                priority_request=None,
            ),
        ],
        acceptances=[
            ExternalChannelIngestionAcceptance(
                status="position_mismatch",
                reason=ExternalChannelIngestionReason.POSITION_CHANGED,
                mailbox_item_id=None,
                session_id=None,
                control_delivery_attempt_id=None,
                connection_id=None,
            ),
            ExternalChannelIngestionAcceptance(
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
        participation_lock=lock,
        history_reader=history,
        store=store,
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
    assert store.accepted_starts == history.calls
    assert wake.calls == [("batch-1", "session-1")]
    assert lock.lease.assertions == 4


async def test_duplicate_recovers_pending_wake_without_history_read() -> None:
    history = _History()
    wake = _WakeDispatcher(results=["already_dispatched"])
    service = ExternalChannelConversationIngestionService(
        conversation_lock=_Lock(),
        participation_lock=_Lock(),
        history_reader=history,
        store=_Store(
            preparations=[
                ExternalChannelIngestionPreparation(
                    position_id=None,
                    exclusive_start_position=None,
                    immediate_outcome=ExternalChannelIngestionOutcome(
                        kind=ExternalChannelIngestionOutcomeKind.DUPLICATE,
                        reason=ExternalChannelIngestionReason.DUPLICATE,
                        mailbox_item_id="batch-1",
                        control_delivery_attempt_id=None,
                        connection_id=None,
                    ),
                    wake_mailbox_item_id="batch-1",
                    wake_session_id="session-1",
                    priority_request=None,
                )
            ],
            acceptances=[],
        ),
        wake_dispatcher=wake,
    )

    outcome = await service.ingest(_request())

    assert outcome.kind is ExternalChannelIngestionOutcomeKind.DUPLICATE
    assert history.calls == []
    assert wake.calls == [("batch-1", "session-1")]


async def test_provider_control_delivery_does_not_gate_accepted_wake() -> None:
    """Committed provider controls remain independent from accepted input wake."""
    wake = _WakeDispatcher()
    service = ExternalChannelConversationIngestionService(
        conversation_lock=_Lock(),
        participation_lock=_Lock(),
        history_reader=_History(),
        store=_Store(
            preparations=[
                ExternalChannelIngestionPreparation(
                    position_id="position-1",
                    exclusive_start_position=None,
                    immediate_outcome=None,
                    wake_mailbox_item_id=None,
                    wake_session_id=None,
                    priority_request=None,
                )
            ],
            acceptances=[
                ExternalChannelIngestionAcceptance(
                    status="accepted",
                    reason=ExternalChannelIngestionReason.ACCEPTED,
                    mailbox_item_id="batch-1",
                    session_id="session-1",
                    control_delivery_attempt_id="progress-1",
                    connection_id="connection-1",
                )
            ],
        ),
        wake_dispatcher=wake,
    )

    outcome = await service.ingest(_request())

    assert outcome.kind is ExternalChannelIngestionOutcomeKind.ACCEPTED
    assert outcome.control_delivery_attempt_id == "progress-1"
    assert outcome.connection_id == "connection-1"
    assert wake.calls == [("batch-1", "session-1")]


async def test_parent_history_io_runs_outside_locks() -> None:
    """Provider history is fetched only after both coordination locks are released."""
    events: list[str] = []
    service = ExternalChannelConversationIngestionService(
        conversation_lock=_EventLock("conversation", events),
        participation_lock=_EventLock("participation", events),
        history_reader=_EventHistory(events),
        store=_EventStore(events),
        wake_dispatcher=_WakeDispatcher(),
    )

    outcome = await service.ingest(_parent_request())

    assert outcome.kind is ExternalChannelIngestionOutcomeKind.ACCEPTED
    history_index = events.index("history:message-key-2")
    assert events[:history_index] == [
        "conversation:enter",
        "conversation:assert",
        "participation:enter",
        "participation:assert",
        "conversation:assert",
        "prepare:current_trigger",
        "participation:exit",
        "conversation:exit",
    ]
    assert events[history_index + 1 :] == [
        "conversation:enter",
        "conversation:assert",
        "participation:enter",
        "participation:assert",
        "conversation:assert",
        "accept:current_trigger",
        "participation:exit",
        "conversation:exit",
    ]


async def test_selected_setup_continuation_precedes_newer_parent_ingress() -> None:
    """A selected setup source is accepted before the newer top-level trigger."""
    events: list[str] = []
    store = _EventStore(events, priority_request=_setup_request())
    wake = _WakeDispatcher(results=["dispatched", "dispatched"])
    service = ExternalChannelConversationIngestionService(
        conversation_lock=_EventLock("conversation", events),
        participation_lock=_EventLock("participation", events),
        history_reader=_EventHistory(events),
        store=store,
        wake_dispatcher=wake,
    )

    outcome = await service.ingest(_parent_request())

    assert outcome.kind is ExternalChannelIngestionOutcomeKind.ACCEPTED
    assert [event for event in events if event.startswith(("history:", "accept:"))] == [
        "history:message-key-1",
        "accept:setup_continuation",
        "history:message-key-2",
        "accept:current_trigger",
    ]
    assert wake.calls == [
        ("mailbox:setup_continuation", "session:setup_continuation"),
        ("mailbox:current_trigger", "session:current_trigger"),
    ]


async def test_concurrent_wake_claim_is_retryable() -> None:
    wake = _WakeDispatcher(results=["claimed_elsewhere"])
    service = ExternalChannelConversationIngestionService(
        conversation_lock=_Lock(),
        participation_lock=_Lock(),
        history_reader=_History(),
        store=_Store(
            preparations=[
                ExternalChannelIngestionPreparation(
                    position_id=None,
                    exclusive_start_position=None,
                    immediate_outcome=ExternalChannelIngestionOutcome(
                        kind=ExternalChannelIngestionOutcomeKind.DUPLICATE,
                        reason=ExternalChannelIngestionReason.DUPLICATE,
                        mailbox_item_id="batch-1",
                        control_delivery_attempt_id=None,
                        connection_id=None,
                    ),
                    wake_mailbox_item_id="batch-1",
                    wake_session_id="session-1",
                    priority_request=None,
                )
            ],
            acceptances=[],
        ),
        wake_dispatcher=wake,
    )

    outcome = await service.ingest(_request())

    assert outcome.kind is ExternalChannelIngestionOutcomeKind.RETRYABLE_FAILURE
    assert outcome.reason is ExternalChannelIngestionReason.WAKE_DISPATCH_PENDING


async def test_history_failure_returns_retryable_outcome() -> None:
    service = ExternalChannelConversationIngestionService(
        conversation_lock=_Lock(),
        participation_lock=_Lock(),
        history_reader=_History(failure=True),
        store=_Store(
            preparations=[
                ExternalChannelIngestionPreparation(
                    position_id="position-1",
                    exclusive_start_position=None,
                    immediate_outcome=None,
                    wake_mailbox_item_id=None,
                    wake_session_id=None,
                    priority_request=None,
                )
            ],
            acceptances=[],
        ),
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
            initial_title_eligible=False,
        )
