"""Focused transaction tests for the database ingestion store."""

import dataclasses
import datetime
from contextlib import AbstractAsyncContextManager
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    ExternalChannelConversationAdmissionStatus,
    ExternalChannelConversationScopeKind,
    ExternalChannelDeliveryStatus,
    ExternalChannelIngressProfile,
    ExternalChannelMessageLifecycle,
    ExternalChannelMessageRevisionKind,
    ExternalChannelPrincipalAuthorType,
    ExternalChannelProvider,
)
from azents.services.external_channel.conversation import (
    ExternalChannelConversationScope,
    ExternalChannelHistoryRange,
    ExternalChannelOperationDeadline,
)
from azents.services.external_channel.ingestion import (
    ExternalChannelCanonicalHistoryMessage,
    ExternalChannelIngestionOperation,
    ExternalChannelIngestionPreparation,
    ExternalChannelIngestionReason,
    ExternalChannelIngestionRequest,
    ExternalChannelIngressAuthority,
    ExternalChannelIngressAuthorityKind,
    ExternalChannelReplayBoundary,
    ExternalChannelTriggerLocator,
)
from azents.services.external_channel.ingestion_store import (
    ExternalChannelDatabaseIngestionStore,
    _resource_labels,  # pyright: ignore[reportPrivateUsage]
)


class _SessionContext(AbstractAsyncContextManager[AsyncSession]):
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def __aenter__(self) -> AsyncSession:
        return self.session

    async def __aexit__(self, *args: object) -> None:
        return None


class _SessionManager:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def __call__(self) -> AbstractAsyncContextManager[AsyncSession]:
        return _SessionContext(self.session)


def _request() -> ExternalChannelIngestionRequest:
    locator = ExternalChannelTriggerLocator(
        connection_id="connection-1",
        provider=ExternalChannelProvider.SLACK,
        provider_tenant_id="tenant-1",
        provider_channel_id="channel-1",
        provider_parent_channel_id=None,
        provider_thread_key="thread-1",
        delivery_thread_key="thread-1",
        provider_resource_key="resource-1",
        trigger_provider_message_key="message-2",
        trigger_provider_message_id="2.000000",
        trigger_position="00000000000000000002",
        provider_user_id="participant-1",
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
            configuration_generation=1,
            lease_owner=None,
            lease_generation=None,
        ),
        deadline=ExternalChannelOperationDeadline(
            datetime.datetime.now(datetime.UTC) + datetime.timedelta(seconds=30)
        ),
        operation=ExternalChannelIngestionOperation.CURRENT_TRIGGER,
        selected_route_id=None,
        replay_boundary=None,
    )


def _history() -> ExternalChannelHistoryRange[ExternalChannelCanonicalHistoryMessage]:
    trigger = ExternalChannelCanonicalHistoryMessage(
        provider_message_key="message-2",
        provider_position="00000000000000000002",
        revision_key="message-2:original",
        revision_kind=ExternalChannelMessageRevisionKind.ORIGINAL,
        lifecycle=ExternalChannelMessageLifecycle.CURRENT,
        author_type=ExternalChannelPrincipalAuthorType.HUMAN,
        provider_user_id="participant-1",
        sender_display_name="Participant",
        normalized_body="provider-authoritative content",
        attachment_metadata=None,
        reference_mappings=None,
        normalized_size=30,
        provider_created_at=datetime.datetime(2026, 7, 29, tzinfo=datetime.UTC),
        provider_updated_at=None,
        original_url=None,
    )
    return ExternalChannelHistoryRange(
        messages=(trigger,),
        trigger=trigger,
        context_omitted=False,
        range_start_position="00000000000000000000",
        trigger_position=trigger.provider_position,
        provider_request_count=1,
        scanned_message_count=1,
        elapsed_seconds=0,
    )


def _replay_request() -> ExternalChannelIngestionRequest:
    request = _request()
    return dataclasses.replace(
        request,
        operation=ExternalChannelIngestionOperation.ACCESS_ALLOW,
        selected_route_id="route-1",
        replay_boundary=ExternalChannelReplayBoundary(
            connection_id=request.locator.connection_id,
            resource_id="resource-1",
            source_message_id="message-2",
            conversation_position_id="position-1",
            range_start_position="00000000000000000000",
            trigger_position=request.locator.trigger_position,
        ),
    )


def _discord_request(
    *,
    scope_kind: ExternalChannelConversationScopeKind,
) -> ExternalChannelIngestionRequest:
    thread_id = (
        "201" if scope_kind is ExternalChannelConversationScopeKind.THREAD else None
    )
    locator = ExternalChannelTriggerLocator(
        connection_id="connection-1",
        provider=ExternalChannelProvider.DISCORD,
        provider_tenant_id="300",
        provider_channel_id="201" if thread_id is not None else "200",
        provider_parent_channel_id="200" if thread_id is not None else None,
        provider_thread_key=thread_id,
        delivery_thread_key="201",
        provider_resource_key=(
            "discord:300:201" if thread_id is not None else "discord:300:100"
        ),
        trigger_provider_message_key="discord:300:100",
        trigger_provider_message_id="100",
        trigger_position="00000000000000000100",
        provider_user_id="400",
        invocation=True,
    )
    return ExternalChannelIngestionRequest(
        locator=locator,
        scope=ExternalChannelConversationScope(
            connection_id=locator.connection_id,
            kind=scope_kind,
            provider_channel_id=locator.provider_channel_id,
            provider_thread_key=locator.provider_thread_key,
        ),
        authority=ExternalChannelIngressAuthority(
            kind=ExternalChannelIngressAuthorityKind.LEASE,
            ingress_profile=ExternalChannelIngressProfile.DISCORD_GATEWAY_HTTP,
            configuration_generation=2,
            lease_owner="manager-1",
            lease_generation=3,
        ),
        deadline=ExternalChannelOperationDeadline(
            datetime.datetime.now(datetime.UTC) + datetime.timedelta(seconds=30)
        ),
        operation=ExternalChannelIngestionOperation.CURRENT_TRIGGER,
        selected_route_id=None,
        replay_boundary=None,
    )


def test_discord_manual_thread_labels_keep_thread_root_identity() -> None:
    labels = _resource_labels(
        _discord_request(scope_kind=ExternalChannelConversationScopeKind.THREAD)
    )

    assert labels["source_channel_id"] == "201"
    assert labels["parent_channel_id"] == "200"
    assert labels["root_message_id"] == "201"
    assert labels["delivery_channel_id"] == "201"


def test_discord_parent_labels_keep_trigger_root_and_confirmed_delivery() -> None:
    labels = _resource_labels(
        _discord_request(scope_kind=ExternalChannelConversationScopeKind.PARENT_CHANNEL)
    )

    assert labels["source_channel_id"] == "200"
    assert labels["parent_channel_id"] == "200"
    assert labels["root_message_id"] == "100"
    assert labels["delivery_channel_id"] == "201"


@pytest.mark.asyncio
async def test_discord_access_control_uses_confirmed_thread_without_lazy_fields() -> (
    None
):
    session = MagicMock(spec=AsyncSession)
    repository = SimpleNamespace(
        create_delivery_attempt_idempotent=AsyncMock(
            return_value=SimpleNamespace(
                id="attempt-1",
                status=ExternalChannelDeliveryStatus.PENDING,
            )
        )
    )
    store = _store(
        session=cast(AsyncSession, session),
        repository=repository,
    )

    attempt_id = await store._create_access_control_intent(  # pyright: ignore[reportPrivateUsage]
        cast(AsyncSession, session),
        request_id="request-1",
        request=_discord_request(
            scope_kind=ExternalChannelConversationScopeKind.PARENT_CHANNEL
        ),
        routing=cast(Any, SimpleNamespace(binding=None)),
        principal_provider_user_id="400",
        participant_label="Participant",
        now=datetime.datetime.now(datetime.UTC),
    )

    assert attempt_id == "attempt-1"
    create = repository.create_delivery_attempt_idempotent.await_args.args[1]
    assert create.request_payload["channel_id"] == "201"
    assert "thread_parent_channel_id" not in create.request_payload
    assert "thread_root_message_id" not in create.request_payload


def _store(
    *,
    session: AsyncSession,
    repository: object,
) -> ExternalChannelDatabaseIngestionStore:
    return ExternalChannelDatabaseIngestionStore(
        session_manager=cast(Any, _SessionManager(session)),
        repository=cast(Any, repository),
        agent_repository=cast(Any, SimpleNamespace()),
        agent_session_repository=cast(Any, SimpleNamespace()),
        root_agent_session_creation_service=cast(Any, SimpleNamespace()),
        mailbox_service=cast(Any, SimpleNamespace()),
        config=cast(Any, SimpleNamespace(web_url="https://azents.example")),
    )


@pytest.mark.parametrize(
    ("kind", "profile"),
    [
        (
            ExternalChannelIngressAuthorityKind.CONFIGURATION,
            ExternalChannelIngressProfile.SLACK_SOCKET,
        ),
        (
            ExternalChannelIngressAuthorityKind.LEASE,
            ExternalChannelIngressProfile.SLACK_HTTP,
        ),
    ],
)
async def test_final_authority_lock_rejects_invalid_kind_profile_combination(
    kind: ExternalChannelIngressAuthorityKind,
    profile: ExternalChannelIngressProfile,
) -> None:
    session = MagicMock(spec=AsyncSession)
    repository = SimpleNamespace(
        lock_connection_for_routing=AsyncMock(
            return_value=SimpleNamespace(
                id="connection-1",
                provider=ExternalChannelProvider.SLACK,
                provider_tenant_id="tenant-1",
                ingress_profile=profile,
                configuration_generation=1,
            )
        ),
        get_owned_discord_gateway_configuration=AsyncMock(),
    )
    invalid_authority = object.__new__(ExternalChannelIngressAuthority)
    object.__setattr__(invalid_authority, "kind", kind)
    object.__setattr__(invalid_authority, "ingress_profile", profile)
    object.__setattr__(invalid_authority, "configuration_generation", 1)
    object.__setattr__(
        invalid_authority,
        "lease_owner",
        "owner-1" if kind is ExternalChannelIngressAuthorityKind.LEASE else None,
    )
    object.__setattr__(
        invalid_authority,
        "lease_generation",
        None,
    )
    request = dataclasses.replace(_request(), authority=invalid_authority)
    store = _store(
        session=cast(AsyncSession, session),
        repository=repository,
    )

    locked = await store._lock_authority(  # pyright: ignore[reportPrivateUsage]
        cast(AsyncSession, session),
        request=request,
        now=datetime.datetime.now(datetime.UTC),
    )

    assert locked is None
    repository.get_owned_discord_gateway_configuration.assert_not_awaited()


async def test_position_mismatch_rolls_back_before_routing_or_content_writes() -> None:
    """A changed PostgreSQL position aborts the entire final acceptance attempt."""
    session = MagicMock(spec=AsyncSession)
    session.rollback = AsyncMock()
    repository = SimpleNamespace(
        lock_conversation_position=AsyncMock(
            return_value=SimpleNamespace(
                id="position-1",
                connection_id="connection-1",
                read_through_position="00000000000000000001",
            )
        ),
        get_resource_by_provider_key=AsyncMock(),
        create_message_revision_idempotent=AsyncMock(),
        create_invocation_batch_idempotent=AsyncMock(),
    )
    store = _store(
        session=cast(AsyncSession, session),
        repository=repository,
    )
    store._lock_authority = AsyncMock(  # pyright: ignore[reportPrivateUsage]
        return_value=SimpleNamespace(id="connection-1")
    )

    result = await store.accept(
        request=_request(),
        preparation=ExternalChannelIngestionPreparation(
            position_id="position-1",
            exclusive_start_position="00000000000000000000",
            immediate_outcome=None,
            wake_batch_id=None,
            wake_session_id=None,
        ),
        history=_history(),
    )

    assert result.status == "position_mismatch"
    assert result.reason is ExternalChannelIngestionReason.POSITION_CHANGED
    session.rollback.assert_awaited_once()
    repository.get_resource_by_provider_key.assert_not_awaited()
    repository.create_message_revision_idempotent.assert_not_awaited()
    repository.create_invocation_batch_idempotent.assert_not_awaited()


async def test_pending_selector_persists_trigger_before_control_delivery() -> None:
    """A route-less Multi App invocation returns one committed selector intent."""
    session = MagicMock(spec=AsyncSession)
    session.commit = AsyncMock()
    position = SimpleNamespace(
        id="position-1",
        connection_id="connection-1",
        read_through_position=None,
    )
    resource = SimpleNamespace(id="resource-1")
    admission = SimpleNamespace(
        id="admission-1",
        status=ExternalChannelConversationAdmissionStatus.PENDING_SELECTION,
    )
    repository = SimpleNamespace(
        lock_conversation_position=AsyncMock(return_value=position),
    )
    store = _store(
        session=cast(AsyncSession, session),
        repository=repository,
    )
    store._lock_authority = AsyncMock(  # pyright: ignore[reportPrivateUsage]
        return_value=SimpleNamespace(id="connection-1")
    )
    store._lock_pending_selection = AsyncMock(  # pyright: ignore[reportPrivateUsage]
        return_value=SimpleNamespace(
            resource=resource,
            admission=admission,
        )
    )
    store._persist_history_message = AsyncMock(  # pyright: ignore[reportPrivateUsage]
        return_value=SimpleNamespace(
            message=SimpleNamespace(id="message-2"),
            revision_id="revision-1",
        )
    )
    store._create_selector_control_intent = AsyncMock(  # pyright: ignore[reportPrivateUsage]
        return_value="delivery-1"
    )
    request = _request()
    history = _history()

    result = await store.accept(
        request=request,
        preparation=ExternalChannelIngestionPreparation(
            position_id=position.id,
            exclusive_start_position=None,
            immediate_outcome=None,
            wake_batch_id=None,
            wake_session_id=None,
        ),
        history=history,
    )

    assert result.status == "awaiting_selection"
    assert result.reason is ExternalChannelIngestionReason.SELECTION_REQUIRED
    assert result.control_delivery_attempt_id == "delivery-1"
    assert result.connection_id == "connection-1"
    store._persist_history_message.assert_awaited_once_with(  # pyright: ignore[reportPrivateUsage]
        cast(AsyncSession, session),
        request=request,
        resource=resource,
        message=history.trigger,
    )
    store._create_selector_control_intent.assert_awaited_once_with(  # pyright: ignore[reportPrivateUsage]
        cast(AsyncSession, session),
        request=request,
        admission=admission,
    )
    session.commit.assert_awaited_once()


async def test_new_selector_admission_reads_history_before_duplicate_shortcut() -> None:
    """A newly created selector boundary must reach canonical history acceptance."""
    session = MagicMock(spec=AsyncSession)
    session.commit = AsyncMock()
    position = SimpleNamespace(
        id="position-1",
        read_through_position=None,
    )
    resource = SimpleNamespace(id="resource-1")
    repository = SimpleNamespace(
        get_resource_by_provider_key=AsyncMock(return_value=None),
        get_active_binding_by_resource=AsyncMock(return_value=None),
        get_open_conversation_admission=AsyncMock(
            return_value=SimpleNamespace(
                status=ExternalChannelConversationAdmissionStatus.PENDING_SELECTION,
            )
        ),
    )
    store = _store(
        session=cast(AsyncSession, session),
        repository=repository,
    )
    store._lock_authority = AsyncMock(  # pyright: ignore[reportPrivateUsage]
        return_value=SimpleNamespace(id="connection-1")
    )
    store._prepare_position = AsyncMock(  # pyright: ignore[reportPrivateUsage]
        return_value=position
    )
    store._create_metadata_source = AsyncMock(  # pyright: ignore[reportPrivateUsage]
        return_value=resource
    )
    store._existing_batch = AsyncMock(  # pyright: ignore[reportPrivateUsage]
        return_value=None
    )

    preparation = await store.prepare(request=_request())

    assert preparation.position_id == position.id
    assert preparation.immediate_outcome is None
    assert preparation.exclusive_start_position is None
    session.commit.assert_awaited_once()


async def test_prepare_rejects_replay_position_outside_request_scope() -> None:
    """A retained position must still belong to the exact replay conversation."""
    session = MagicMock(spec=AsyncSession)
    repository = SimpleNamespace(
        get_conversation_position=AsyncMock(
            return_value=SimpleNamespace(
                id="position-1",
                connection_id="another-connection",
                scope_kind=ExternalChannelConversationScopeKind.THREAD,
                provider_channel_id="channel-1",
                provider_thread_key="thread-1",
            )
        ),
        get_resource_by_provider_key=AsyncMock(),
    )
    store = _store(
        session=cast(AsyncSession, session),
        repository=repository,
    )
    store._lock_authority = AsyncMock(  # pyright: ignore[reportPrivateUsage]
        return_value=SimpleNamespace(id="connection-1")
    )

    preparation = await store.prepare(request=_replay_request())

    assert preparation.immediate_outcome is not None
    assert (
        preparation.immediate_outcome.reason
        is ExternalChannelIngestionReason.INVALID_REPLAY_BOUNDARY
    )
    repository.get_resource_by_provider_key.assert_not_awaited()


async def test_prepare_rejects_replay_resource_owner_mismatch() -> None:
    """A replay cannot substitute another canonical resource with the same locator."""
    session = MagicMock(spec=AsyncSession)
    session.commit = AsyncMock()
    repository = SimpleNamespace(
        get_conversation_position=AsyncMock(
            return_value=SimpleNamespace(
                id="position-1",
                connection_id="connection-1",
                scope_kind=ExternalChannelConversationScopeKind.THREAD,
                provider_channel_id="channel-1",
                provider_thread_key="thread-1",
                read_through_position=None,
            )
        ),
        get_resource_by_provider_key=AsyncMock(
            return_value=SimpleNamespace(
                id="resource-other",
                connection_id="connection-1",
            )
        ),
        get_message=AsyncMock(),
    )
    store = _store(
        session=cast(AsyncSession, session),
        repository=repository,
    )
    store._lock_authority = AsyncMock(  # pyright: ignore[reportPrivateUsage]
        return_value=SimpleNamespace(id="connection-1")
    )

    preparation = await store.prepare(request=_replay_request())

    assert preparation.immediate_outcome is not None
    assert (
        preparation.immediate_outcome.reason
        is ExternalChannelIngestionReason.INVALID_REPLAY_BOUNDARY
    )
    repository.get_message.assert_not_awaited()
    session.commit.assert_awaited_once()


async def test_replay_after_shared_position_accepts_without_cursor_rollback() -> None:
    """A retained trigger batch activates its binding without moving position back."""
    session = MagicMock(spec=AsyncSession)
    session.commit = AsyncMock()
    request = _replay_request()
    position = SimpleNamespace(
        id="position-1",
        connection_id="connection-1",
        scope_kind=ExternalChannelConversationScopeKind.THREAD,
        provider_channel_id="channel-1",
        provider_thread_key="thread-1",
        read_through_position="00000000000000000009",
    )
    resource = SimpleNamespace(id="resource-1", connection_id="connection-1")
    route = SimpleNamespace(
        id="route-1",
        connection_id="connection-1",
        require_active_agent_id=MagicMock(return_value="agent-1"),
    )
    binding = SimpleNamespace(
        id="binding-1",
        route_id="route-1",
        resource_id="resource-1",
        agent_session_id="session-1",
    )
    source_message = SimpleNamespace(
        id="message-2",
        resource_id="resource-1",
        provider_message_key="message-2",
        provider_position=request.locator.trigger_position,
    )
    persisted_trigger = SimpleNamespace(
        id="message-2",
        principal_id="principal-1",
        provider_message_key="message-2",
        provider_position=request.locator.trigger_position,
    )
    batch = SimpleNamespace(id="batch-1")
    repository = SimpleNamespace(
        lock_conversation_position=AsyncMock(return_value=position),
        create_message_idempotent=AsyncMock(return_value=source_message),
        update_message_identity_metadata=AsyncMock(return_value=source_message),
        get_active_block=AsyncMock(return_value=None),
        get_active_access_grant=AsyncMock(return_value=SimpleNamespace(id="grant-1")),
        get_invocation_batch=AsyncMock(return_value=None),
        create_invocation_batch_idempotent=AsyncMock(return_value=batch),
        create_invocation_batch_item_idempotent=AsyncMock(),
        ensure_active_work=AsyncMock(),
        mark_resource_history_ready=AsyncMock(),
        lock_invocation_batch=AsyncMock(
            return_value=SimpleNamespace(
                id="batch-1",
                mailbox_item_id="mailbox-1",
            )
        ),
        mark_binding_activated=AsyncMock(return_value=SimpleNamespace(id="binding-1")),
        advance_conversation_position_if_current=AsyncMock(),
    )
    store = _store(
        session=cast(AsyncSession, session),
        repository=repository,
    )
    store.agent_session_repository = cast(
        Any,
        SimpleNamespace(mark_running_for_input_wakeup=AsyncMock()),
    )
    store._lock_authority = AsyncMock(  # pyright: ignore[reportPrivateUsage]
        return_value=SimpleNamespace(id="connection-1")
    )
    store._lock_routing = AsyncMock(  # pyright: ignore[reportPrivateUsage]
        return_value=SimpleNamespace(
            resource=resource,
            route=route,
            binding=binding,
            admission=None,
        )
    )
    store._persist_principal = AsyncMock(  # pyright: ignore[reportPrivateUsage]
        return_value="principal-1"
    )
    store._persist_history_message = AsyncMock(  # pyright: ignore[reportPrivateUsage]
        return_value=SimpleNamespace(
            message=persisted_trigger,
            revision_id="revision-1",
        )
    )
    store._initialize_thread_position = AsyncMock()  # pyright: ignore[reportPrivateUsage]

    boundary = request.replay_boundary
    assert boundary is not None
    result = await store.accept(
        request=request,
        preparation=ExternalChannelIngestionPreparation(
            position_id=position.id,
            exclusive_start_position=boundary.range_start_position,
            immediate_outcome=None,
            wake_batch_id=None,
            wake_session_id=None,
        ),
        history=_history(),
    )

    assert result.status == "accepted"
    assert result.batch_id == "batch-1"
    repository.advance_conversation_position_if_current.assert_not_awaited()
    repository.mark_resource_history_ready.assert_awaited_once_with(
        cast(AsyncSession, session),
        resource_id="resource-1",
        through_provider_position="00000000000000000009",
        completed_at=repository.mark_resource_history_ready.await_args.kwargs[
            "completed_at"
        ],
    )
    repository.mark_binding_activated.assert_awaited_once_with(
        cast(AsyncSession, session),
        binding_id="binding-1",
        now=repository.mark_binding_activated.await_args.kwargs["now"],
        projected_through_position=request.locator.trigger_position,
    )
    session.commit.assert_awaited_once()
