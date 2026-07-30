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
    ExternalChannelDeliveryOperation,
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


def _history(
    *,
    author_type: ExternalChannelPrincipalAuthorType = (
        ExternalChannelPrincipalAuthorType.HUMAN
    ),
) -> ExternalChannelHistoryRange[ExternalChannelCanonicalHistoryMessage]:
    trigger = ExternalChannelCanonicalHistoryMessage(
        provider_message_key="message-2",
        provider_position="00000000000000000002",
        revision_key="message-2:original",
        revision_kind=ExternalChannelMessageRevisionKind.ORIGINAL,
        lifecycle=ExternalChannelMessageLifecycle.CURRENT,
        author_type=author_type,
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
        work_repository=cast(Any, SimpleNamespace()),
        agent_repository=cast(Any, SimpleNamespace()),
        workspace_repository=cast(
            Any,
            SimpleNamespace(
                get_by_id=AsyncMock(
                    return_value=SimpleNamespace(handle="workspace-handle")
                )
            ),
        ),
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


async def test_pending_selector_persists_only_human_trigger_identity() -> None:
    """A route-less human invocation commits metadata and one selector intent."""
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
        connection_id="connection-1",
        initiating_principal_id="principal-1",
        status=ExternalChannelConversationAdmissionStatus.PENDING_SELECTION,
    )
    repository = SimpleNamespace(
        lock_conversation_position=AsyncMock(return_value=position),
        get_resource_by_provider_key=AsyncMock(return_value=resource),
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
    store._persist_message_identity = AsyncMock(  # pyright: ignore[reportPrivateUsage]
        return_value=SimpleNamespace(
            id="message-2",
            principal_id="principal-1",
            current_revision_id=None,
            original_url=None,
            pending_size=0,
        )
    )
    store._persist_history_message = AsyncMock()  # pyright: ignore[reportPrivateUsage]
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
    store._persist_message_identity.assert_awaited_once_with(  # pyright: ignore[reportPrivateUsage]
        cast(AsyncSession, session),
        request=request,
        resource=resource,
        message=history.trigger,
    )
    store._persist_history_message.assert_not_awaited()  # pyright: ignore[reportPrivateUsage]
    store._create_selector_control_intent.assert_awaited_once_with(  # pyright: ignore[reportPrivateUsage]
        cast(AsyncSession, session),
        request=request,
        admission=admission,
    )
    session.commit.assert_awaited_once()


async def test_pending_source_identity_never_persists_provider_content() -> None:
    """Pre-authorization source rows retain only identity and ordering facts."""
    session = MagicMock(spec=AsyncSession)
    message = _history().trigger
    repository = SimpleNamespace(
        create_principal_idempotent=AsyncMock(return_value=SimpleNamespace(id="p-1")),
        create_message_idempotent=AsyncMock(return_value=SimpleNamespace(id="m-1")),
        update_message_identity_metadata=AsyncMock(
            return_value=SimpleNamespace(id="m-1")
        ),
        create_message_revision_idempotent=AsyncMock(),
        apply_message_revision=AsyncMock(),
    )
    store = _store(
        session=cast(AsyncSession, session),
        repository=repository,
    )

    persisted = await store._persist_message_identity(  # pyright: ignore[reportPrivateUsage]
        cast(AsyncSession, session),
        request=_request(),
        resource=cast(Any, SimpleNamespace(id="resource-1")),
        message=message,
    )

    assert persisted.id == "m-1"
    create = repository.create_message_idempotent.await_args.args[1]
    assert create.resource_id == "resource-1"
    assert create.provider_message_key == message.provider_message_key
    assert create.provider_position == message.provider_position
    assert create.current_revision_id is None
    assert create.original_url is None
    assert create.pending_size == 0
    repository.create_message_revision_idempotent.assert_not_awaited()
    repository.apply_message_revision.assert_not_awaited()


async def test_pending_selector_ignores_bot_before_catalog_or_source_persistence() -> (
    None
):
    """A bot cannot create selector state, content, controls, or cursor progress."""
    session = MagicMock(spec=AsyncSession)
    session.commit = AsyncMock()
    position = SimpleNamespace(
        id="position-1",
        connection_id="connection-1",
        read_through_position=None,
    )
    repository = SimpleNamespace(
        lock_conversation_position=AsyncMock(return_value=position),
        list_routable_multi_catalog_routes=AsyncMock(return_value=[]),
        get_resource_by_provider_key=AsyncMock(),
        advance_conversation_position_if_current=AsyncMock(return_value=True),
    )
    store = _store(
        session=cast(AsyncSession, session),
        repository=repository,
    )
    store._lock_authority = AsyncMock(  # pyright: ignore[reportPrivateUsage]
        return_value=SimpleNamespace(id="connection-1")
    )
    store._lock_pending_selection = AsyncMock()  # pyright: ignore[reportPrivateUsage]
    store._persist_message_identity = AsyncMock()  # pyright: ignore[reportPrivateUsage]
    store._persist_history_message = AsyncMock()  # pyright: ignore[reportPrivateUsage]
    store._create_selector_control_intent = AsyncMock()  # pyright: ignore[reportPrivateUsage]

    result = await store.accept(
        request=_request(),
        preparation=ExternalChannelIngestionPreparation(
            position_id=position.id,
            exclusive_start_position=None,
            immediate_outcome=None,
            wake_batch_id=None,
            wake_session_id=None,
        ),
        history=_history(author_type=ExternalChannelPrincipalAuthorType.BOT),
    )

    assert result.status == "ignored"
    assert result.reason is ExternalChannelIngestionReason.AUTHOR_NOT_ELIGIBLE
    repository.list_routable_multi_catalog_routes.assert_not_awaited()
    repository.get_resource_by_provider_key.assert_not_awaited()
    repository.advance_conversation_position_if_current.assert_not_awaited()
    store._lock_pending_selection.assert_not_awaited()  # pyright: ignore[reportPrivateUsage]
    store._persist_message_identity.assert_not_awaited()  # pyright: ignore[reportPrivateUsage]
    store._persist_history_message.assert_not_awaited()  # pyright: ignore[reportPrivateUsage]
    store._create_selector_control_intent.assert_not_awaited()  # pyright: ignore[reportPrivateUsage]
    session.commit.assert_awaited_once()


@pytest.mark.parametrize(
    "author_type",
    [
        ExternalChannelPrincipalAuthorType.BOT,
        ExternalChannelPrincipalAuthorType.SYSTEM,
    ],
)
async def test_context_only_trigger_is_ignored_without_cursor_advance_or_source_content(
    author_type: ExternalChannelPrincipalAuthorType,
) -> None:
    """Bot and system triggers remain context-only and never move the cursor."""
    session = MagicMock(spec=AsyncSession)
    session.commit = AsyncMock()
    position = SimpleNamespace(
        id="position-1",
        connection_id="connection-1",
        read_through_position=None,
    )
    repository = SimpleNamespace(
        lock_conversation_position=AsyncMock(return_value=position),
        advance_conversation_position_if_current=AsyncMock(return_value=True),
        get_resource_by_provider_key=AsyncMock(return_value=None),
    )
    store = _store(
        session=cast(AsyncSession, session),
        repository=repository,
    )
    store._lock_authority = AsyncMock(  # pyright: ignore[reportPrivateUsage]
        return_value=SimpleNamespace(id="connection-1")
    )
    store._lock_pending_selection = AsyncMock(  # pyright: ignore[reportPrivateUsage]
        return_value=None
    )
    store._lock_routing = AsyncMock(  # pyright: ignore[reportPrivateUsage]
        return_value=SimpleNamespace(
            resource=SimpleNamespace(id="resource-1"),
            route=SimpleNamespace(
                open_access_enabled=True,
            ),
            binding=None,
            admission=None,
        )
    )
    store._persist_message_identity = AsyncMock()  # pyright: ignore[reportPrivateUsage]
    store._persist_history_message = AsyncMock()  # pyright: ignore[reportPrivateUsage]
    store._create_metadata_source = AsyncMock()  # pyright: ignore[reportPrivateUsage]

    result = await store.accept(
        request=_request(),
        preparation=ExternalChannelIngestionPreparation(
            position_id=position.id,
            exclusive_start_position=None,
            immediate_outcome=None,
            wake_batch_id=None,
            wake_session_id=None,
        ),
        history=_history(author_type=author_type),
    )

    assert result.status == "ignored"
    assert result.reason is ExternalChannelIngestionReason.AUTHOR_NOT_ELIGIBLE
    store._persist_message_identity.assert_not_awaited()  # pyright: ignore[reportPrivateUsage]
    store._persist_history_message.assert_not_awaited()  # pyright: ignore[reportPrivateUsage]
    store._create_metadata_source.assert_not_awaited()  # pyright: ignore[reportPrivateUsage]
    store._lock_routing.assert_not_awaited()  # pyright: ignore[reportPrivateUsage]
    repository.advance_conversation_position_if_current.assert_not_awaited()
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
    """A retained trigger batch accepts without moving the shared position back."""
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
        open_access_enabled=False,
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
        principal_id="principal-1",
    )
    persisted_context = SimpleNamespace(
        message=SimpleNamespace(
            id="message-1",
            provider_message_key="message-1",
            provider_position="00000000000000000001",
        ),
        revision_id="revision-0",
    )
    persisted_trigger = SimpleNamespace(
        id="message-2",
        principal_id="principal-1",
        provider_message_key="message-2",
        provider_position=request.locator.trigger_position,
    )
    batch = SimpleNamespace(id="batch-1")
    work = SimpleNamespace(
        id="work-1",
        desired_progress_revision=1,
    )
    repository = SimpleNamespace(
        lock_conversation_position=AsyncMock(return_value=position),
        get_resource_by_provider_key=AsyncMock(return_value=resource),
        create_message_idempotent=AsyncMock(return_value=source_message),
        update_message_identity_metadata=AsyncMock(return_value=source_message),
        get_active_block=AsyncMock(return_value=None),
        get_active_access_grant=AsyncMock(return_value=object()),
        get_invocation_batch=AsyncMock(return_value=None),
        create_invocation_batch_idempotent=AsyncMock(return_value=batch),
        create_invocation_batch_item_idempotent=AsyncMock(),
        ensure_active_work=AsyncMock(return_value=work),
        create_delivery_attempt_idempotent=AsyncMock(
            return_value=SimpleNamespace(
                id="delivery-1",
                status=ExternalChannelDeliveryStatus.PENDING,
            )
        ),
        lock_invocation_batch=AsyncMock(
            return_value=SimpleNamespace(
                id="batch-1",
                mailbox_item_id="mailbox-1",
            )
        ),
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
        return_value=SimpleNamespace(
            id="connection-1",
            workspace_id="workspace-1",
        )
    )
    store._lock_routing = AsyncMock(  # pyright: ignore[reportPrivateUsage]
        return_value=SimpleNamespace(
            resource=resource,
            route=route,
            binding=None,
            admission=None,
        )
    )
    store._create_binding = AsyncMock(  # pyright: ignore[reportPrivateUsage]
        return_value=binding
    )
    store._create_session_link_intent = AsyncMock(  # pyright: ignore[reportPrivateUsage]
        return_value="session-link-1"
    )
    store._persist_principal = AsyncMock(  # pyright: ignore[reportPrivateUsage]
        return_value="principal-1"
    )
    persisted_trigger_result = SimpleNamespace(
        message=persisted_trigger,
        revision_id="revision-1",
    )
    store._persist_history_message = AsyncMock(  # pyright: ignore[reportPrivateUsage]
        side_effect=[persisted_context, persisted_trigger_result]
    )
    store._initialize_thread_position = AsyncMock()  # pyright: ignore[reportPrivateUsage]

    human_history = _history()
    bot_context = dataclasses.replace(
        human_history.trigger,
        provider_message_key="message-1",
        provider_position="00000000000000000001",
        revision_key="message-1:original",
        author_type=ExternalChannelPrincipalAuthorType.BOT,
        provider_user_id="context-bot-1",
        sender_display_name="Context Bot",
        normalized_body="provider-visible bot context",
    )
    history = dataclasses.replace(
        human_history,
        messages=(bot_context, human_history.trigger),
        scanned_message_count=2,
    )
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
        history=history,
    )

    assert result.status == "accepted"
    assert result.batch_id == "batch-1"
    assert result.control_delivery_attempt_id == "session-link-1"
    assert result.connection_id == "connection-1"
    store._create_session_link_intent.assert_awaited_once()  # pyright: ignore[reportPrivateUsage]
    delivery = repository.create_delivery_attempt_idempotent.await_args.args[1]
    assert delivery.origin_id == "work-1"
    assert delivery.binding_id == "binding-1"
    assert delivery.operation is ExternalChannelDeliveryOperation.PROGRESS_CREATE
    assert delivery.request_payload["work_id"] == "work-1"
    assert delivery.request_payload["thread_ts"] == "thread-1"
    persisted_messages = [
        call.kwargs["message"]
        for call in store._persist_history_message.await_args_list  # pyright: ignore[reportPrivateUsage]
    ]
    assert [message.author_type for message in persisted_messages] == [
        ExternalChannelPrincipalAuthorType.BOT,
        ExternalChannelPrincipalAuthorType.HUMAN,
    ]
    repository.advance_conversation_position_if_current.assert_not_awaited()
    session.commit.assert_awaited_once()


async def test_initial_session_link_intent_targets_the_bound_session() -> None:
    """The first binding persists a separate provider-native Session link."""
    session = MagicMock(spec=AsyncSession)
    repository = SimpleNamespace(
        create_delivery_attempt_idempotent=AsyncMock(
            return_value=SimpleNamespace(
                id="session-link-1",
                status=ExternalChannelDeliveryStatus.PENDING,
            )
        )
    )
    store = _store(
        session=cast(AsyncSession, session),
        repository=repository,
    )
    route = SimpleNamespace(require_active_agent_id=MagicMock(return_value="agent-1"))
    binding = SimpleNamespace(
        id="binding-1",
        agent_session_id="session-1",
    )

    attempt_id = await store._create_session_link_intent(  # pyright: ignore[reportPrivateUsage]
        cast(AsyncSession, session),
        request=_request(),
        connection=cast(Any, SimpleNamespace(workspace_id="workspace-1")),
        routing=cast(Any, SimpleNamespace(route=route)),
        binding=cast(Any, binding),
    )

    assert attempt_id == "session-link-1"
    create = repository.create_delivery_attempt_idempotent.await_args.args[1]
    assert create.origin_id == "binding-1"
    assert create.binding_id == "binding-1"
    assert create.operation is ExternalChannelDeliveryOperation.CONTROL_MESSAGE
    assert create.request_payload["control_kind"] == "session_link"
    assert create.request_payload["thread_ts"] == "thread-1"
    assert (
        create.request_payload["blocks"][0]["elements"][0]["url"]
        == "https://azents.example/w/workspace-handle/agents/agent-1/sessions/session-1"
    )
