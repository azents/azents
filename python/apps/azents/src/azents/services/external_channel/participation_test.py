"""Provider-neutral External Channel participation service tests."""

import datetime
from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.config import Config
from azents.core.enums import (
    ExternalChannelConversationLocation,
    ExternalChannelConversationScopeKind,
    ExternalChannelParticipationSettingStatus,
    ExternalChannelProvider,
    ExternalChannelResourceStatus,
    ExternalChannelResourceType,
    ExternalChannelResponseMode,
    ExternalChannelSetupClaimStatus,
)
from azents.rdb.session import SessionManager
from azents.repos.external_channel.data import (
    ExternalChannelParticipationSetting,
    ExternalChannelResource,
    ExternalChannelSetupClaim,
)
from azents.services.external_channel.conversation import (
    ExternalChannelConversationLockLease,
    ExternalChannelConversationScope,
    ExternalChannelOperationDeadline,
    ExternalChannelParticipationScope,
)
from azents.services.external_channel.ingestion import (
    ExternalChannelIngestionOutcome,
    ExternalChannelIngestionOutcomeKind,
    ExternalChannelIngestionReason,
)
from azents.services.external_channel.participation import (
    ExternalChannelParticipationService,
    _CommittedLocation,  # pyright: ignore[reportPrivateUsage]
)
from azents.services.external_channel.participation_state import (
    ExternalChannelSetupSourceProjection,
    projection_with_setup_source,
)

_NOW = datetime.datetime(2026, 8, 1, tzinfo=datetime.UTC)


@asynccontextmanager
async def _session_manager() -> AsyncGenerator[AsyncSession, None]:
    yield cast(AsyncSession, SimpleNamespace())


class _Lock:
    def acquire(
        self,
        *,
        scope: ExternalChannelConversationScope | ExternalChannelParticipationScope,
        deadline: ExternalChannelOperationDeadline,
    ) -> AbstractAsyncContextManager[ExternalChannelConversationLockLease]:
        del scope, deadline

        @asynccontextmanager
        async def owned() -> AsyncIterator[ExternalChannelConversationLockLease]:
            yield cast(
                ExternalChannelConversationLockLease,
                SimpleNamespace(assert_owned=AsyncMock()),
            )

        return owned()


def _source() -> ExternalChannelSetupSourceProjection:
    return ExternalChannelSetupSourceProjection(
        schema_version=1,
        provider=ExternalChannelProvider.SLACK,
        provider_event_type="app_mention",
        provider_tenant_id="tenant-1",
        provider_channel_id="channel-1",
        provider_parent_channel_id="channel-1",
        scope_kind=ExternalChannelConversationScopeKind.PARENT_CHANNEL,
        provider_thread_key=None,
        delivery_thread_key="1.000000",
        provider_resource_key="slack:tenant-1:channel-1:1.000000",
        trigger_provider_message_key="slack:tenant-1:channel-1:1.000000",
        trigger_provider_message_id="1.000000",
        trigger_position="00000000000000000001",
        range_start_position=None,
    )


def _claim(
    *,
    status: ExternalChannelSetupClaimStatus,
) -> ExternalChannelSetupClaim:
    return ExternalChannelSetupClaim.model_construct(
        id="claim-1",
        connection_id="connection-1",
        provider_parent_channel_id="channel-1",
        route_id="route-1",
        conversation_position_id="position-1",
        source_resource_id="source-resource-1",
        principal_id="principal-1",
        source_projection=projection_with_setup_source(_source()),
        source_revision=2,
        claim_generation=1,
        status=status,
        selected_setting_id=(
            "setting-1"
            if status
            in {
                ExternalChannelSetupClaimStatus.SELECTED,
                ExternalChannelSetupClaimStatus.COMPLETED,
            }
            else None
        ),
        selected_resource_id=(
            "parent-resource-1"
            if status
            in {
                ExternalChannelSetupClaimStatus.SELECTED,
                ExternalChannelSetupClaimStatus.COMPLETED,
            }
            else None
        ),
        selected_source_revision=(
            2
            if status
            in {
                ExternalChannelSetupClaimStatus.SELECTED,
                ExternalChannelSetupClaimStatus.COMPLETED,
            }
            else None
        ),
    )


def _setting() -> ExternalChannelParticipationSetting:
    return ExternalChannelParticipationSetting.model_construct(
        id="setting-1",
        connection_id="connection-1",
        provider_parent_channel_id="channel-1",
        route_id="route-1",
        location=ExternalChannelConversationLocation.CHANNEL,
        response_mode=ExternalChannelResponseMode.MENTION_ONLY,
        settings_generation=1,
        configured_by_user_id=None,
        configured_by_principal_id="principal-1",
        status=ExternalChannelParticipationSettingStatus.ACTIVE,
    )


def _service(
    *,
    repository: object,
    replay: object | None = None,
) -> ExternalChannelParticipationService:
    return ExternalChannelParticipationService(
        session_manager=cast(SessionManager[AsyncSession], _session_manager),
        repository=cast(Any, repository),
        agent_repository=cast(Any, MagicMock()),
        ingestion_replay_service=cast(Any, replay or MagicMock()),
        conversation_lock=cast(Any, _Lock()),
        participation_lock=cast(Any, _Lock()),
        config=Config.model_construct(external_channel_participation_enabled=True),
    )


@pytest.mark.asyncio
async def test_replay_failure_preserves_committed_location_for_recovery() -> None:
    """Selection commits first and reports a recoverable replay failure."""
    events: list[str] = []
    pending = _claim(status=ExternalChannelSetupClaimStatus.PENDING_LOCATION)
    selected = _claim(status=ExternalChannelSetupClaimStatus.SELECTED)
    repository = MagicMock()
    repository.get_setup_claim = AsyncMock(return_value=pending)
    replay = MagicMock()

    async def replay_setup_claim(**kwargs: object) -> ExternalChannelIngestionOutcome:
        del kwargs
        events.append("replay")
        return ExternalChannelIngestionOutcome(
            kind=ExternalChannelIngestionOutcomeKind.RETRYABLE_FAILURE,
            reason=ExternalChannelIngestionReason.HISTORY_UNAVAILABLE,
            mailbox_item_id=None,
            control_delivery_attempt_id=None,
            connection_id=None,
        )

    replay.replay_setup_claim = replay_setup_claim
    service = _service(repository=repository, replay=replay)

    async def commit_location(**kwargs: object) -> _CommittedLocation:
        del kwargs
        events.append("commit")
        return _CommittedLocation(
            setting=_setting(),
            claim=selected,
            created=True,
        )

    service._commit_location = commit_location  # pyright: ignore[reportPrivateUsage]

    result = await service.select_location(
        setup_claim_id=pending.id,
        expected_claim_generation=1,
        expected_source_revision=2,
        location=ExternalChannelConversationLocation.CHANNEL,
        configured_by_principal_id="principal-1",
        now=_NOW,
        deadline=ExternalChannelOperationDeadline(
            _NOW + datetime.timedelta(seconds=30)
        ),
    )

    assert events == ["commit", "replay"]
    assert result.status == "pending_recovery"
    assert result.setting.id == "setting-1"
    assert result.claim.status is ExternalChannelSetupClaimStatus.SELECTED
    assert result.replay_outcome is not None
    assert (
        result.replay_outcome.kind
        is ExternalChannelIngestionOutcomeKind.RETRYABLE_FAILURE
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("location", "expected_resource_type"),
    [
        (
            ExternalChannelConversationLocation.CHANNEL,
            ExternalChannelResourceType.PARENT_CHANNEL,
        ),
        (
            ExternalChannelConversationLocation.THREADS,
            ExternalChannelResourceType.THREAD,
        ),
    ],
)
async def test_location_selection_resolves_explicit_target_resource(
    location: ExternalChannelConversationLocation,
    expected_resource_type: ExternalChannelResourceType,
) -> None:
    """Channel creates a parent Resource while Threads retains the source Resource."""
    source_resource = ExternalChannelResource.model_construct(
        id="source-resource-1",
        connection_id="connection-1",
        resource_type=ExternalChannelResourceType.THREAD,
        provider_resource_key="slack:tenant-1:channel-1:1.000000",
        status=ExternalChannelResourceStatus.ACTIVE,
    )
    parent_resource = ExternalChannelResource.model_construct(
        id="parent-resource-1",
        connection_id="connection-1",
        resource_type=ExternalChannelResourceType.PARENT_CHANNEL,
        provider_resource_key="channel-1",
        status=ExternalChannelResourceStatus.ACTIVE,
    )
    repository = MagicMock()
    repository.lock_resource = AsyncMock(return_value=source_resource)
    repository.create_resource_idempotent = AsyncMock(return_value=parent_resource)
    service = _service(repository=repository)

    resolved = await service._resolve_selected_resource(  # pyright: ignore[reportPrivateUsage]
        cast(AsyncSession, SimpleNamespace()),
        claim=_claim(status=ExternalChannelSetupClaimStatus.PENDING_LOCATION),
        source=_source(),
        location=location,
        now=_NOW,
    )

    assert resolved.resource_type is expected_resource_type
    if location is ExternalChannelConversationLocation.CHANNEL:
        create = repository.create_resource_idempotent.await_args.args[1]
        assert create.resource_type is ExternalChannelResourceType.PARENT_CHANNEL
        assert create.provider_resource_key == "channel-1"
        repository.lock_resource.assert_not_awaited()
    else:
        assert resolved is source_resource
        repository.create_resource_idempotent.assert_not_awaited()
