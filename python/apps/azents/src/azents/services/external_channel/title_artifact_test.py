"""Tests for External Channel automatic-title creation artifacts."""

import dataclasses
import datetime
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    ExternalChannelDiscordThreadObservationStatus,
    ExternalChannelProvider,
    ExternalChannelResourceType,
)
from azents.repos.external_channel.data import ExternalChannelResource
from azents.repos.external_channel.title import ExternalChannelTitleRepository
from azents.services.external_channel.conversation import DiscordRootThreadObservation
from azents.services.external_channel.title_artifact import (
    ExternalChannelTitleArtifactRequest,
    ExternalChannelTitleArtifactService,
)


def _resource(*, delivery_channel_id: str | None = None) -> ExternalChannelResource:
    labels: dict[str, object] = {
        "provider": "discord",
        "guild_id": "guild-1",
        "parent_channel_id": "parent-1",
        "root_message_id": "root-1",
    }
    if delivery_channel_id is not None:
        labels["delivery_channel_id"] = delivery_channel_id
    return ExternalChannelResource.model_construct(
        id="resource-1",
        connection_id="connection-1",
        resource_type=ExternalChannelResourceType.THREAD,
        labels=labels,
    )


def _observation() -> DiscordRootThreadObservation:
    return DiscordRootThreadObservation(
        status=ExternalChannelDiscordThreadObservationStatus.THREAD_ABSENT,
        guild_id="guild-1",
        parent_channel_id="parent-1",
        root_message_id="root-1",
        trigger_provider_message_key="message-1",
        observed_at=datetime.datetime(2026, 8, 2, tzinfo=datetime.UTC),
        root_has_thread=False,
        thread=None,
    )


def _request(
    *,
    provider: ExternalChannelProvider = ExternalChannelProvider.DISCORD,
    provisional_title_source: str = " Agent   One ",
    observation: DiscordRootThreadObservation | None = None,
    resource: ExternalChannelResource | None = None,
) -> ExternalChannelTitleArtifactRequest:
    return ExternalChannelTitleArtifactRequest(
        connection_id="connection-1",
        agent_session_id="session-1",
        binding_id="binding-1",
        resource=resource or _resource(),
        trigger_provider_message_key="message-1",
        provider=provider,
        provisional_title_source=provisional_title_source,
        access_request_id=None,
        discord_root_thread_observation=observation,
    )


def _service() -> tuple[ExternalChannelTitleArtifactService, MagicMock]:
    repository = MagicMock(spec=ExternalChannelTitleRepository)
    repository.create_session_title_candidate = AsyncMock(
        return_value=SimpleNamespace(
            id="candidate-1",
            admission_access_request_id=None,
            admission_provisional_title="Agent One",
        )
    )
    repository.create_discord_thread_title_projection = AsyncMock(
        return_value=SimpleNamespace(id="projection-1")
    )
    repository.get_projection_by_resource_id = AsyncMock(return_value=None)
    repository.get_candidate_by_identity = AsyncMock(
        return_value=SimpleNamespace(
            id="candidate-1",
            admission_access_request_id=None,
            admission_provisional_title="Agent One",
        )
    )
    return (
        ExternalChannelTitleArtifactService(
            title_repository=cast(ExternalChannelTitleRepository, repository)
        ),
        repository,
    )


async def test_create_persists_candidate_without_projection_for_non_discord() -> None:
    """Non-Discord creation retains only the exact Session title candidate."""
    service, repository = _service()

    artifacts = await service.create(
        cast(AsyncSession, MagicMock()),
        request=_request(provider=ExternalChannelProvider.SLACK),
    )

    assert artifacts.candidate.id == "candidate-1"
    assert artifacts.projection is None
    repository.create_discord_thread_title_projection.assert_not_awaited()


async def test_create_persists_exact_discord_projection_with_normalized_title() -> None:
    """A qualifying exact-root absence records one immutable title projection."""
    service, repository = _service()

    artifacts = await service.create(
        cast(AsyncSession, MagicMock()),
        request=_request(observation=_observation()),
    )

    assert artifacts.projection is not None
    create = repository.create_discord_thread_title_projection.await_args.args[1]
    assert create.session_title_candidate_id == "candidate-1"
    assert create.requested_provisional_title == "Agent One"
    assert create.admission_root_message_id == "root-1"
    assert create.admission_trigger_provider_message_key == "message-1"


async def test_create_rejects_blank_provisional_title_source() -> None:
    """Candidate creation never substitutes an ungrounded fallback title."""
    service, repository = _service()

    with pytest.raises(ValueError, match="must not be blank"):
        await service.create(
            cast(AsyncSession, MagicMock()),
            request=_request(provisional_title_source=" \t "),
        )

    repository.create_session_title_candidate.assert_not_awaited()


async def test_existing_candidate_projection_never_creates_a_new_candidate() -> None:
    """Access-Allow replay only adds a projection to its durable candidate."""
    service, repository = _service()

    artifacts = await service.create_projection_for_existing_candidate(
        cast(AsyncSession, MagicMock()),
        request=_request(observation=_observation()),
    )

    assert artifacts is not None
    repository.create_session_title_candidate.assert_not_awaited()
    repository.create_discord_thread_title_projection.assert_awaited_once()


async def test_access_replay_ignores_observation_time() -> None:
    """Durable admission identity does not compare a replay observation timestamp."""
    service, repository = _service()
    candidate = repository.get_candidate_by_identity.return_value
    candidate.admission_access_request_id = "access-1"
    observed = _observation()
    repository.get_projection_by_resource_id.return_value = SimpleNamespace(
        binding_id="binding-1",
        agent_session_id="session-1",
        session_title_candidate_id="candidate-1",
        requested_provisional_title="Agent One",
        admission_connection_id="connection-1",
        admission_guild_id="guild-1",
        admission_parent_channel_id="parent-1",
        admission_root_message_id="root-1",
        admission_trigger_provider_message_key="message-1",
        admission_observation_status=observed.status,
        admission_root_has_thread=observed.root_has_thread,
        admission_observed_thread_channel_id=None,
    )

    artifacts = await service.create_projection_for_existing_candidate(
        cast(AsyncSession, MagicMock()),
        request=dataclasses.replace(
            _request(
                observation=dataclasses.replace(
                    observed,
                    observed_at=observed.observed_at + datetime.timedelta(seconds=1),
                )
            ),
            access_request_id="access-1",
        ),
    )

    assert artifacts is not None
    assert artifacts.projection is repository.get_projection_by_resource_id.return_value
    repository.create_discord_thread_title_projection.assert_not_awaited()


async def test_access_replay_uses_persisted_provisional_title_after_agent_rename() -> (
    None
):
    """A later Agent rename cannot alter the durable admission title snapshot."""
    service, repository = _service()
    candidate = repository.get_candidate_by_identity.return_value
    candidate.admission_access_request_id = "access-1"

    artifacts = await service.create_projection_for_existing_candidate(
        cast(AsyncSession, MagicMock()),
        request=dataclasses.replace(
            _request(
                provisional_title_source="Agent Renamed",
                observation=_observation(),
            ),
            access_request_id="access-1",
        ),
    )

    assert artifacts is not None
    create = repository.create_discord_thread_title_projection.await_args.args[1]
    assert create.requested_provisional_title == "Agent One"
