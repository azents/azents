"""DB-only effective-target admission tests."""

import datetime
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    AgentSessionStatus,
    ExternalChannelAppMode,
    ExternalChannelConversationLocation,
    ExternalChannelConversationScopeKind,
    ExternalChannelIngressAuthorityKind,
    ExternalChannelIngressProfile,
    ExternalChannelProvider,
    ExternalChannelResourceStatus,
    ExternalChannelResourceType,
    ExternalChannelResponseMode,
)
from azents.job_runtime.types import JobRuntime
from azents.rdb.session import SessionManager
from azents.repos.agent_session.repository import AgentSessionRepository
from azents.repos.external_channel.data import (
    ExternalChannelAgentRoute,
    ExternalChannelBinding,
    ExternalChannelConnection,
    ExternalChannelParticipationSetting,
    ExternalChannelResource,
)
from azents.repos.external_channel.ingress_queue import (
    ExternalChannelIngressQueueRepository,
)
from azents.repos.external_channel.repository import ExternalChannelRepository
from azents.services.external_channel.ingestion import (
    ExternalChannelIngestionOutcomeKind,
    ExternalChannelIngestionReason,
    ExternalChannelIngestionRequest,
    ExternalChannelTriggerLocator,
)
from azents.services.external_channel.ingress_admission import (
    ExternalChannelIngressAdmissionService,
    _response_mode_triggered,
)


def _session_manager(
    session: AsyncSession | None = None,
) -> SessionManager[AsyncSession]:
    @asynccontextmanager
    async def manager() -> AsyncIterator[AsyncSession]:
        yield cast(AsyncSession, object()) if session is None else session

    return manager


def _service(
    repository: MagicMock,
    *,
    session_manager: SessionManager[AsyncSession] | None = None,
    queue_repository: MagicMock | None = None,
) -> ExternalChannelIngressAdmissionService:
    return ExternalChannelIngressAdmissionService(
        session_manager=session_manager or _session_manager(),
        repository=cast(ExternalChannelRepository, repository),
        queue_repository=cast(
            ExternalChannelIngressQueueRepository,
            queue_repository or MagicMock(),
        ),
        agent_session_repository=cast(AgentSessionRepository, MagicMock()),
        job_runtime=cast(JobRuntime, MagicMock()),
    )


def _connection() -> ExternalChannelConnection:
    return ExternalChannelConnection.model_construct(
        id="connection-1",
        provider=ExternalChannelProvider.DISCORD,
        app_mode=ExternalChannelAppMode.SINGLE,
    )


def _route() -> ExternalChannelAgentRoute:
    return ExternalChannelAgentRoute.model_construct(
        id="route-1",
        connection_id="connection-1",
        agent_id="agent-1",
    )


def _resource(
    resource_id: str,
    resource_type: ExternalChannelResourceType,
) -> ExternalChannelResource:
    return ExternalChannelResource.model_construct(
        id=resource_id,
        connection_id="connection-1",
        resource_type=resource_type,
        provider_resource_key=resource_id,
        labels=None,
        status=ExternalChannelResourceStatus.ACTIVE,
    )


def _request(
    *,
    invocation: bool = True,
    provider: ExternalChannelProvider = ExternalChannelProvider.DISCORD,
) -> ExternalChannelIngestionRequest:
    return cast(
        ExternalChannelIngestionRequest,
        SimpleNamespace(
            locator=ExternalChannelTriggerLocator(
                connection_id="connection-1",
                provider=provider,
                provider_event_type=(
                    "discord_message_create"
                    if provider is ExternalChannelProvider.DISCORD
                    else "message"
                ),
                provider_tenant_id="guild-1",
                provider_channel_id="thread-1",
                provider_parent_channel_id="parent-1",
                provider_thread_key="thread-1",
                delivery_thread_key="thread-1",
                provider_resource_key="discord:guild-1:thread-1",
                trigger_provider_message_key="discord:message-1",
                trigger_provider_message_id="message-1",
                trigger_position="0001",
                provider_user_id="user-1",
                invocation=invocation,
                expected_file_count=None,
            ),
            scope=SimpleNamespace(
                connection_id="connection-1",
                kind=ExternalChannelConversationScopeKind.THREAD,
                provider_channel_id="thread-1",
                provider_thread_key="thread-1",
            ),
            authority=SimpleNamespace(
                ingress_profile=ExternalChannelIngressProfile.DISCORD_GATEWAY_HTTP,
                configuration_generation=1,
                kind=ExternalChannelIngressAuthorityKind.LEASE,
                lease_owner="lease-owner-1",
                lease_generation=1,
            ),
            initial_title_eligible=False,
        ),
    )


def _binding(
    response_mode: ExternalChannelResponseMode,
) -> ExternalChannelBinding:
    return ExternalChannelBinding.model_construct(
        id="binding-1",
        resource_id="source-1",
        route_id="route-1",
        agent_session_id="session-1",
        response_mode=response_mode,
    )


@pytest.mark.parametrize(
    ("invocation", "binding", "response_mode", "expected"),
    [
        (False, None, ExternalChannelResponseMode.ALL_MESSAGES, False),
        (True, None, ExternalChannelResponseMode.ALL_MESSAGES, True),
        (False, None, ExternalChannelResponseMode.MENTION_ONLY, False),
        (True, None, ExternalChannelResponseMode.MENTION_ONLY, True),
        (
            False,
            _binding(ExternalChannelResponseMode.ALL_MESSAGES),
            ExternalChannelResponseMode.ALL_MESSAGES,
            True,
        ),
        (
            False,
            _binding(ExternalChannelResponseMode.MENTION_ONLY),
            ExternalChannelResponseMode.MENTION_ONLY,
            False,
        ),
        (
            True,
            _binding(ExternalChannelResponseMode.MENTION_ONLY),
            ExternalChannelResponseMode.MENTION_ONLY,
            True,
        ),
    ],
)
def test_response_mode_requires_invocation_until_binding_exists(
    invocation: bool,
    binding: ExternalChannelBinding | None,
    response_mode: ExternalChannelResponseMode,
    expected: bool,
) -> None:
    """Only a connected all-messages Binding admits ordinary continuation."""
    assert (
        _response_mode_triggered(
            invocation=invocation,
            binding=binding,
            response_mode=response_mode,
        )
        is expected
    )


@pytest.mark.parametrize(
    ("provider", "location"),
    [
        (
            ExternalChannelProvider.SLACK,
            ExternalChannelConversationLocation.CHANNEL,
        ),
        (
            ExternalChannelProvider.SLACK,
            ExternalChannelConversationLocation.THREADS,
        ),
        (
            ExternalChannelProvider.DISCORD,
            ExternalChannelConversationLocation.CHANNEL,
        ),
        (
            ExternalChannelProvider.DISCORD,
            ExternalChannelConversationLocation.THREADS,
        ),
    ],
)
async def test_unbound_all_messages_non_invocation_stops_before_queue(
    provider: ExternalChannelProvider,
    location: ExternalChannelConversationLocation,
) -> None:
    """Parent configuration cannot join an unbound conversation automatically."""
    commit = AsyncMock()
    session = cast(AsyncSession, SimpleNamespace(commit=commit))
    repository = MagicMock()
    repository.create_principal_idempotent = AsyncMock()
    queue_repository = MagicMock()
    queue_repository.admit = AsyncMock()
    service = _service(
        repository,
        session_manager=_session_manager(session),
        queue_repository=queue_repository,
    )
    source = _resource("source-1", ExternalChannelResourceType.THREAD)
    target_resource = (
        _resource(
            "parent-resource-1",
            ExternalChannelResourceType.PARENT_CHANNEL,
        )
        if location is ExternalChannelConversationLocation.CHANNEL
        else source
    )
    target = SimpleNamespace(
        resource=target_resource,
        route=_route(),
        setting=ExternalChannelParticipationSetting.model_construct(
            id="setting-1",
            route_id="route-1",
            location=location,
            response_mode=ExternalChannelResponseMode.ALL_MESSAGES,
            settings_generation=1,
        ),
        binding=None,
        response_mode=ExternalChannelResponseMode.ALL_MESSAGES,
    )

    with (
        patch.object(
            ExternalChannelIngressAdmissionService,
            "_lock_authority",
            new=AsyncMock(return_value=_connection()),
        ),
        patch.object(
            ExternalChannelIngressAdmissionService,
            "_ensure_source_resource",
            new=AsyncMock(return_value=source),
        ),
        patch.object(
            ExternalChannelIngressAdmissionService,
            "_resolve_target",
            new=AsyncMock(return_value=cast(Any, target)),
        ),
    ):
        outcome = await service.admit_current_trigger(
            provider_event_id="event-1",
            request=_request(
                invocation=False,
                provider=provider,
            ),
        )

    assert outcome is not None
    assert outcome.kind is ExternalChannelIngestionOutcomeKind.IGNORED
    assert outcome.reason is ExternalChannelIngestionReason.RESPONSE_MODE_NOT_TRIGGERED
    commit.assert_awaited_once()
    repository.create_principal_idempotent.assert_not_awaited()
    queue_repository.admit.assert_not_awaited()


async def test_bound_trigger_checks_session_without_row_lock() -> None:
    """Queue admission reads Session availability without serializing the row."""
    commit = AsyncMock()
    session = cast(AsyncSession, SimpleNamespace(commit=commit))
    repository = MagicMock()
    repository.create_principal_idempotent = AsyncMock(
        return_value=SimpleNamespace(id="principal-1")
    )
    repository.get_active_block = AsyncMock(return_value=None)
    repository.get_active_access_grant = AsyncMock(return_value=SimpleNamespace())
    repository.create_conversation_position_idempotent = AsyncMock(
        return_value=SimpleNamespace(id="position-1")
    )
    queue_repository = MagicMock()
    queue_repository.admit = AsyncMock(
        return_value=SimpleNamespace(
            owner=SimpleNamespace(
                id="owner-1",
                created_at=datetime.datetime.now(datetime.UTC),
            ),
            created=True,
            replaced_stale_owner=False,
        )
    )
    service = _service(
        repository,
        session_manager=_session_manager(session),
        queue_repository=queue_repository,
    )
    service.agent_session_repository = MagicMock()
    service.agent_session_repository.get_by_id = AsyncMock(
        return_value=SimpleNamespace(
            status=AgentSessionStatus.ACTIVE,
            stop_requested_at=None,
        )
    )
    service.agent_session_repository.lock_by_id = AsyncMock()
    service._submit = AsyncMock()  # noqa: SLF001
    source = _resource("source-1", ExternalChannelResourceType.THREAD)
    route = _route().model_copy(update={"open_access_enabled": False})
    target = SimpleNamespace(
        resource=source,
        route=route,
        setting=None,
        binding=_binding(ExternalChannelResponseMode.ALL_MESSAGES),
        response_mode=ExternalChannelResponseMode.ALL_MESSAGES,
    )

    with (
        patch.object(
            ExternalChannelIngressAdmissionService,
            "_lock_authority",
            new=AsyncMock(return_value=_connection()),
        ),
        patch.object(
            ExternalChannelIngressAdmissionService,
            "_ensure_source_resource",
            new=AsyncMock(return_value=source),
        ),
        patch.object(
            ExternalChannelIngressAdmissionService,
            "_resolve_target",
            new=AsyncMock(return_value=cast(Any, target)),
        ),
    ):
        outcome = await service.admit_current_trigger(
            provider_event_id="event-1",
            request=_request(),
        )

    assert outcome is not None
    assert outcome.kind is ExternalChannelIngestionOutcomeKind.ACCEPTED
    service.agent_session_repository.get_by_id.assert_awaited_once_with(
        session,
        "session-1",
    )
    service.agent_session_repository.lock_by_id.assert_not_awaited()
    queue_repository.admit.assert_awaited_once()
    commit.assert_awaited_once()


async def test_discord_channel_location_keeps_thread_as_owner_target() -> None:
    """Discord Threads remain independent from the configured parent conversation."""
    source = _resource("source-1", ExternalChannelResourceType.THREAD)
    repository = MagicMock()
    repository.lock_connected_binding_by_resource = AsyncMock(return_value=None)
    repository.lock_routable_single_route = AsyncMock(return_value=_route())
    repository.lock_active_participation_setting = AsyncMock(
        return_value=ExternalChannelParticipationSetting.model_construct(
            id="setting-1",
            route_id="route-1",
            location=ExternalChannelConversationLocation.CHANNEL,
            response_mode=ExternalChannelResponseMode.ALL_MESSAGES,
            settings_generation=1,
        )
    )
    repository.lock_resource_by_provider_key = AsyncMock()
    repository.create_resource_idempotent = AsyncMock()
    service = _service(repository)
    session = cast(AsyncSession, object())

    target = await service._resolve_target(  # noqa: SLF001
        session,
        request=_request(),
        connection=_connection(),
        source_resource=source,
        now=MagicMock(),
    )

    assert target is not None
    assert target.resource is source
    assert target.setting is not None
    assert target.binding is None
    assert target.response_mode is ExternalChannelResponseMode.ALL_MESSAGES
    repository.lock_resource_by_provider_key.assert_not_awaited()
    repository.create_resource_idempotent.assert_not_awaited()


async def test_threads_location_keeps_source_thread_as_owner_target() -> None:
    """A configured per-thread conversation does not fan into its parent."""
    source = _resource("source-1", ExternalChannelResourceType.THREAD)
    repository = MagicMock()
    repository.lock_connected_binding_by_resource = AsyncMock(return_value=None)
    repository.lock_routable_single_route = AsyncMock(return_value=_route())
    repository.lock_active_participation_setting = AsyncMock(
        return_value=ExternalChannelParticipationSetting.model_construct(
            id="setting-1",
            route_id="route-1",
            location=ExternalChannelConversationLocation.THREADS,
            response_mode=ExternalChannelResponseMode.MENTION_ONLY,
            settings_generation=1,
        )
    )
    repository.lock_resource_by_provider_key = AsyncMock()
    service = _service(repository)

    target = await service._resolve_target(  # noqa: SLF001
        cast(AsyncSession, object()),
        request=_request(),
        connection=_connection(),
        source_resource=source,
        now=MagicMock(),
    )

    assert target is not None
    assert target.resource is source
    assert target.response_mode is ExternalChannelResponseMode.MENTION_ONLY
    repository.lock_resource_by_provider_key.assert_not_awaited()


async def test_source_resource_create_race_rejects_inactive_result() -> None:
    """An idempotent create conflict cannot admit an unavailable source."""
    inactive = ExternalChannelResource.model_construct(
        id="source-1",
        connection_id="connection-1",
        resource_type=ExternalChannelResourceType.THREAD,
        provider_resource_key="discord:guild-1:thread-1",
        labels=None,
        status=ExternalChannelResourceStatus.UNAVAILABLE,
    )
    repository = MagicMock()
    repository.lock_resource_by_provider_key = AsyncMock(side_effect=[None, inactive])
    repository.create_resource_idempotent = AsyncMock(return_value=inactive)
    service = _service(repository)

    resource = await service._ensure_source_resource(  # noqa: SLF001
        cast(AsyncSession, object()),
        request=_request(),
        now=MagicMock(),
    )

    assert resource is None
    repository.create_resource_idempotent.assert_awaited_once()
