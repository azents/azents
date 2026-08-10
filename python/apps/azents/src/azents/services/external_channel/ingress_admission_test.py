"""DB-only effective-target admission tests."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, MagicMock

from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    ExternalChannelAppMode,
    ExternalChannelConversationLocation,
    ExternalChannelConversationScopeKind,
    ExternalChannelProvider,
    ExternalChannelResourceStatus,
    ExternalChannelResourceType,
    ExternalChannelResponseMode,
)
from azents.job_runtime.types import JobRuntime
from azents.rdb.session import SessionManager
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.external_channel.data import (
    ExternalChannelAgentRoute,
    ExternalChannelConnection,
    ExternalChannelParticipationSetting,
    ExternalChannelResource,
)
from azents.repos.external_channel.ingress_queue import (
    ExternalChannelIngressQueueRepository,
)
from azents.repos.external_channel.repository import ExternalChannelRepository
from azents.services.external_channel.ingestion import (
    ExternalChannelIngestionRequest,
    ExternalChannelTriggerLocator,
)
from azents.services.external_channel.ingress_admission import (
    ExternalChannelIngressAdmissionService,
)


def _session_manager() -> SessionManager[AsyncSession]:
    @asynccontextmanager
    async def manager() -> AsyncIterator[AsyncSession]:
        yield cast(AsyncSession, object())

    return manager


def _service(repository: MagicMock) -> ExternalChannelIngressAdmissionService:
    return ExternalChannelIngressAdmissionService(
        session_manager=_session_manager(),
        repository=cast(ExternalChannelRepository, repository),
        queue_repository=cast(ExternalChannelIngressQueueRepository, MagicMock()),
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


def _request() -> ExternalChannelIngestionRequest:
    return cast(
        ExternalChannelIngestionRequest,
        SimpleNamespace(
            locator=ExternalChannelTriggerLocator(
                connection_id="connection-1",
                provider=ExternalChannelProvider.DISCORD,
                provider_event_type="discord_message_create",
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
                invocation=True,
            ),
            scope=SimpleNamespace(
                kind=ExternalChannelConversationScopeKind.THREAD,
                provider_channel_id="thread-1",
                provider_thread_key="thread-1",
            ),
        ),
    )


async def test_channel_location_fans_source_thread_into_parent_owner() -> None:
    """A source-thread callback targets the configured parent conversation."""
    source = _resource("source-1", ExternalChannelResourceType.THREAD)
    parent = _resource("parent-resource-1", ExternalChannelResourceType.PARENT_CHANNEL)
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
    repository.lock_resource_by_provider_key = AsyncMock(return_value=parent)
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
    assert target.resource.id == "parent-resource-1"
    assert target.setting is not None
    assert target.binding is None
    assert target.response_mode is ExternalChannelResponseMode.ALL_MESSAGES
    repository.lock_resource_by_provider_key.assert_awaited_once_with(
        session,
        connection_id="connection-1",
        resource_type=ExternalChannelResourceType.PARENT_CHANNEL,
        provider_resource_key="parent-1",
    )
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
