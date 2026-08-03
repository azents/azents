"""Focused current-projection tests for direct External Channel Work."""

from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, MagicMock

from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    ExternalChannelAccessRequestStatus,
    ExternalChannelWorkProjectionStatus,
    ExternalChannelWorkStatus,
)
from azents.core.external_channel_title import DISCORD_INITIAL_THREAD_TITLE_LABEL
from azents.rdb.models.external_channel import (
    RDBExternalChannelWork,
    RDBExternalChannelWorkProjectionPart,
)
from azents.repos.external_channel.work import (
    ExternalChannelWorkRepository,
    projection_state,
)
from azents.testing.external_channel import make_provider_effect_plan


def _work(*, desired: bool) -> RDBExternalChannelWork:
    return RDBExternalChannelWork(
        binding_id="binding-1",
        status=ExternalChannelWorkStatus.ACTIVE,
        schema_version=2,
        title="Working…" if desired else None,
        tasks=[],
        state_revision=2,
        desired_progress_revision=3,
        desired_progress_payload={"state": "working"} if desired else None,
        finished_at=None,
    )


def _part(
    *,
    status: ExternalChannelWorkProjectionStatus,
    provider_message_key: str | None,
    revision: int = 3,
) -> RDBExternalChannelWorkProjectionPart:
    return RDBExternalChannelWorkProjectionPart(
        work_id="work-1",
        part_ordinal=0,
        desired_progress_revision=revision,
        status=status,
        provider_message_key=provider_message_key,
    )


def test_projection_state_is_missing_without_owned_parts() -> None:
    assert projection_state(_work(desired=True), []) == "missing"


def test_projection_state_is_synchronized_for_current_present_part() -> None:
    assert (
        projection_state(
            _work(desired=True),
            [
                _part(
                    status=ExternalChannelWorkProjectionStatus.PRESENT,
                    provider_message_key="provider-key",
                )
            ],
        )
        == "synchronized"
    )


def test_projection_state_preserves_unknown_without_retry_authority() -> None:
    assert (
        projection_state(
            _work(desired=True),
            [
                _part(
                    status=ExternalChannelWorkProjectionStatus.UNKNOWN,
                    provider_message_key=None,
                )
            ],
        )
        == "unknown"
    )


def test_projection_state_reports_failed_terminal_delete() -> None:
    finished = _work(desired=False)
    finished.status = ExternalChannelWorkStatus.FINISHED
    assert (
        projection_state(
            finished,
            [
                _part(
                    status=ExternalChannelWorkProjectionStatus.FAILED,
                    provider_message_key="provider-key",
                )
            ],
        )
        == "delete_failed"
    )


def test_projection_state_accepts_orm_sequence_contract() -> None:
    parts = [
        _part(
            status=ExternalChannelWorkProjectionStatus.DELETED,
            provider_message_key=None,
        )
    ]
    assert projection_state(_work(desired=False), parts) == "none"


async def test_access_control_create_is_claimed_once_before_provider_io() -> None:
    """A repeated access callback cannot create a second provider control."""
    request = SimpleNamespace(
        status=ExternalChannelAccessRequestStatus.PENDING,
        control_provider_message_key=None,
        control_projection_status=None,
    )
    session = MagicMock()
    session.scalar = AsyncMock(return_value=request)
    session.flush = AsyncMock()
    repository = ExternalChannelWorkRepository()
    plan = make_provider_effect_plan("access-control")
    repository.prepare_direct_control = AsyncMock(return_value=plan)

    first = await repository.prepare_access_control_create(
        cast(AsyncSession, session),
        access_request_id="access-request-1",
        connection_id="connection-1",
        resource_id="resource-1",
        route_id="route-1",
        binding_id=None,
        request_payload={"access_request_id": "access-request-1"},
        operation_seed="access-request:access-request-1",
    )
    second = await repository.prepare_access_control_create(
        cast(AsyncSession, session),
        access_request_id="access-request-1",
        connection_id="connection-1",
        resource_id="resource-1",
        route_id="route-1",
        binding_id=None,
        request_payload={"access_request_id": "access-request-1"},
        operation_seed="access-request:access-request-1",
    )

    assert first == plan
    assert second is None
    assert (
        request.control_projection_status is ExternalChannelWorkProjectionStatus.UNKNOWN
    )
    session.flush.assert_awaited_once()
    repository.prepare_direct_control.assert_awaited_once()


async def test_discord_delivery_channel_records_direct_create_title_once() -> None:
    """Direct-create evidence is retained once and never manufactured later."""
    resource = SimpleNamespace(
        labels={"provider": "discord", "guild_id": "111"},
    )
    session = MagicMock()
    session.get = AsyncMock(return_value=resource)
    session.flush = AsyncMock()
    repository = ExternalChannelWorkRepository()

    first = await repository.record_discord_delivery_channel(
        cast(AsyncSession, session),
        resource_id="resource-1",
        delivery_channel_id="444",
        initial_thread_title="Test agent",
    )
    second = await repository.record_discord_delivery_channel(
        cast(AsyncSession, session),
        resource_id="resource-1",
        delivery_channel_id="555",
        initial_thread_title="Another title",
    )

    assert first == "444"
    assert second == "444"
    assert resource.labels["delivery_channel_id"] == "444"
    assert resource.labels[DISCORD_INITIAL_THREAD_TITLE_LABEL] == "Test agent"
    session.flush.assert_awaited_once()
