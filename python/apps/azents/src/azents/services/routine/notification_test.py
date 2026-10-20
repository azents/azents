"""Canonical completion survives failed or suppressed immediate notification."""

import asyncio
import datetime
from typing import Literal
from unittest.mock import AsyncMock, Mock

import pytest
import sqlalchemy as sa

from azents.core.enums import AgentRunStatus
from azents.core.external_channel_file import ExternalChannelOutboundFileManifest
from azents.core.external_channel_provider_effect import (
    ProviderEffectPlan,
    ProviderMutationOutcome,
)
from azents.core.routine import (
    RoutineDeliveryStatus,
    RoutineObjectiveOutcome,
    RoutineScope,
)
from azents.rdb.models.agent_session import RDBAgentSession
from azents.rdb.models.external_channel import (
    RDBExternalChannelBinding,
    RDBExternalChannelResource,
)
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import WriteSession
from azents.repos.agent_execution import EventTranscriptRepository
from azents.repos.external_channel.work import ExternalChannelWorkRepository
from azents.repos.routine.completion_test import NOW, fixture, work
from azents.repos.routine.notification import RoutineNotificationOperations
from azents.repos.routine.persistence_test import _legacy_binding
from azents.repos.session_primary_channel import SessionPrimaryChannelRepository
from azents.services.external_channel.channel_action import ExternalChannelActionService
from azents.services.routine.files import RoutineNotificationFiles
from azents.services.routine.notification import RoutineNotificationService


async def _channel_binding(
    session: WriteSession, scope: RoutineScope
) -> RDBExternalChannelBinding:
    binding = await _legacy_binding(session, scope)
    await session.write_session.execute(
        sa.update(RDBExternalChannelResource)
        .where(RDBExternalChannelResource.id == binding.resource_id)
        .values(labels={"channel_id": "C-fixture", "thread_ts": "1.2"})
    )
    return binding


@pytest.mark.parametrize(
    "provider_status", ["delivered", "failed", "unknown", "raises", "cancelled"]
)
async def test_current_primary_delivery_is_post_commit_and_never_replayed(
    rdb_session_manager: SessionManager[WriteSession],
    provider_status: Literal["delivered", "failed", "unknown", "raises", "cancelled"],
) -> None:
    f = await fixture(rdb_session_manager)
    async with rdb_session_manager() as session:
        binding = await _channel_binding(session, f.scope)
        binding_id = binding.id
        await session.write_session.execute(
            sa.update(RDBAgentSession)
            .where(
                RDBAgentSession.id == f.scope.session_id,
            )
            .values(primary_channel_binding_id=binding_id)
        )
    channels = Mock(spec=ExternalChannelActionService)
    channels.for_execution_owner.return_value = channels
    publish = AsyncMock()
    operations = RoutineNotificationOperations(
        session_manager=rdb_session_manager,
        primary=SessionPrimaryChannelRepository(),
        channels=ExternalChannelWorkRepository.create(),
        events=EventTranscriptRepository(),
        execution_authority=f.repository.execution_authority,
    )
    service = RoutineNotificationService(
        operations=operations, completion=f.repository, channels=channels
    )
    item = f.states[0]
    manifest = ExternalChannelOutboundFileManifest(
        path="/tmp/report.txt",
        filename="report.txt",
        media_type="text/plain",
        expected_size=5,
    )
    files = RoutineNotificationFiles(
        binding_id=binding_id, manifests=(manifest,), attachments=()
    )
    recording = await f.repository.complete(
        scope=f.scope,
        authority=f.authority,
        slug=item.context.candidate.slug,
        execution_id=item.context.execution_id,
        work=work(notify=True, outcome=RoutineObjectiveOutcome.FINISHED),
        now=NOW,
    )

    async def send(
        plan: ProviderEffectPlan, **kwargs: object
    ) -> ProviderMutationOutcome:
        assert plan.target.binding_id == binding_id
        assert plan.target.request_payload["files"] == [
            manifest.model_dump(mode="json")
        ]
        assert kwargs["authority"] == f.authority
        # A separate real transaction sees completion before the provider call.
        state = await f.repository.context(
            scope=f.scope,
            authority=f.authority,
            slug=item.context.candidate.slug,
            execution_id=item.context.execution_id,
        )
        assert state.phase == "completed"
        assert state.delivery_status is RoutineDeliveryStatus.UNOBSERVED
        if provider_status == "raises":
            raise RuntimeError("Simulated provider boundary failure")
        if provider_status == "cancelled":
            raise asyncio.CancelledError
        return ProviderMutationOutcome(
            status=provider_status,
            provider_message_key="sent-message",
            error_kind=None,
            error_summary=None,
        )

    channels.execute_binding_effect.side_effect = send
    if provider_status in {"raises", "cancelled"}:
        with pytest.raises(
            RuntimeError if provider_status == "raises" else asyncio.CancelledError
        ):
            await service.deliver(
                scope=f.scope,
                authority=f.authority,
                recording=recording,
                runtime=None,
                publish_event=publish,
                files=files,
            )
    else:
        await service.deliver(
            scope=f.scope,
            authority=f.authority,
            recording=recording,
            runtime=None,
            publish_event=publish,
            files=files,
        )
    state = await f.repository.context(
        scope=f.scope,
        authority=f.authority,
        slug=item.context.candidate.slug,
        execution_id=item.context.execution_id,
    )
    assert state.phase == "completed"
    assert state.delivery_status is (
        RoutineDeliveryStatus.DELIVERED
        if provider_status == "delivered"
        else RoutineDeliveryStatus.UNOBSERVED
        if provider_status == "cancelled"
        else RoutineDeliveryStatus.FAILED
    )
    assert recording.state.work is not None
    repeat = await f.repository.complete(
        scope=f.scope,
        authority=f.authority,
        slug=item.context.candidate.slug,
        execution_id=item.context.execution_id,
        work=recording.state.work,
        now=NOW,
    )
    await service.deliver(
        scope=f.scope,
        authority=f.authority,
        recording=repeat,
        runtime=None,
        publish_event=publish,
        files=None,
    )
    assert channels.execute_binding_effect.call_count == 1
    publish.assert_not_called()
    assert (
        len(await f.repository.list_started(scope=f.scope, authority=f.authority)) == 1
    )
    async with rdb_session_manager() as session:
        run = await f.repository.runs.get_by_id(session, f.authority.run_id)
        assert run is not None and run.status is AgentRunStatus.RUNNING


async def test_invalid_existing_primary_fails_without_session_chat_fallback(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    f = await fixture(rdb_session_manager)
    async with rdb_session_manager() as session:
        binding = await _channel_binding(session, f.scope)
        binding.disconnected_at = datetime.datetime.now(datetime.UTC)
        await session.write_session.execute(
            sa.update(RDBAgentSession)
            .where(
                RDBAgentSession.id == f.scope.session_id,
            )
            .values(primary_channel_binding_id=binding.id)
        )
    channels = Mock(spec=ExternalChannelActionService)
    publish = AsyncMock()
    service = RoutineNotificationService(
        operations=RoutineNotificationOperations(
            session_manager=rdb_session_manager,
            primary=SessionPrimaryChannelRepository(),
            channels=ExternalChannelWorkRepository.create(),
            events=EventTranscriptRepository(),
            execution_authority=f.repository.execution_authority,
        ),
        completion=f.repository,
        channels=channels,
    )
    item = f.states[0]
    recording = await f.repository.complete(
        scope=f.scope,
        authority=f.authority,
        slug=item.context.candidate.slug,
        execution_id=item.context.execution_id,
        work=work(notify=True, outcome=RoutineObjectiveOutcome.FINISHED),
        now=NOW,
    )
    state = await service.deliver(
        scope=f.scope,
        authority=f.authority,
        recording=recording,
        runtime=None,
        publish_event=publish,
        files=None,
    )
    assert state.delivery_status is RoutineDeliveryStatus.FAILED
    channels.execute_binding_effect.assert_not_called()
    publish.assert_not_called()
    async with rdb_session_manager() as session:
        assert (
            await EventTranscriptRepository().get_by_external_id(
                session,
                f.scope.session_id,
                f"routine-notification:{item.context.execution_id}",
            )
            is None
        )


async def test_primary_replacement_suppresses_captured_effect(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    f = await fixture(rdb_session_manager)
    async with rdb_session_manager() as session:
        first = await _channel_binding(session, f.scope)
        second = await _channel_binding(session, f.scope)
        first_id, second_id = first.id, second.id
        await session.write_session.execute(
            sa.update(RDBAgentSession)
            .where(
                RDBAgentSession.id == f.scope.session_id,
            )
            .values(primary_channel_binding_id=first_id)
        )
    operations = RoutineNotificationOperations(
        session_manager=rdb_session_manager,
        primary=SessionPrimaryChannelRepository(),
        channels=ExternalChannelWorkRepository.create(),
        events=EventTranscriptRepository(),
        execution_authority=f.repository.execution_authority,
    )
    item = f.states[0]
    recording = await f.repository.complete(
        scope=f.scope,
        authority=f.authority,
        slug=item.context.candidate.slug,
        execution_id=item.context.execution_id,
        work=work(notify=True, outcome=RoutineObjectiveOutcome.FINISHED),
        now=NOW,
    )
    prepared = await operations.prepare(
        scope=f.scope,
        authority=f.authority,
        recording=recording,
        files=(),
        attachments=(),
        expected_primary=None,
        pin_primary=False,
    )
    assert prepared.binding_id == first_id and prepared.plans
    async with rdb_session_manager() as session:
        await session.write_session.execute(
            sa.update(RDBAgentSession)
            .where(
                RDBAgentSession.id == f.scope.session_id,
            )
            .values(primary_channel_binding_id=second_id)
        )
    assert not await operations.primary_matches(
        scope=f.scope, authority=f.authority, binding_id=first_id
    )
    assert await operations.primary_matches(
        scope=f.scope, authority=f.authority, binding_id=second_id
    )
