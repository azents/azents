"""Prepared Routine files cannot follow a changed Primary or fall back."""

from unittest.mock import AsyncMock

import pytest
import sqlalchemy as sa

from azents.core.routine import RoutineDeliveryStatus, RoutineObjectiveOutcome
from azents.rdb.models.agent_session import RDBAgentSession
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import WriteSession
from azents.repos.agent_execution import EventTranscriptRepository
from azents.repos.external_channel.work import ExternalChannelWorkRepository
from azents.repos.routine.completion_test import NOW, fixture, work
from azents.repos.routine.notification import RoutineNotificationOperations
from azents.repos.session_primary_channel import SessionPrimaryChannelRepository
from azents.services.external_channel.channel_action import ExternalChannelActionService
from azents.services.routine.files import RoutineNotificationFiles
from azents.services.routine.notification import RoutineNotificationService
from azents.services.routine.notification_test import _channel_binding


@pytest.mark.parametrize("had_primary", [False, True])
async def test_destination_change_after_file_preparation_suppresses_all_delivery(
    rdb_session_manager: SessionManager[WriteSession], had_primary: bool
) -> None:
    f = await fixture(rdb_session_manager)
    async with rdb_session_manager() as session:
        first = await _channel_binding(session, f.scope)
        second = await _channel_binding(session, f.scope)
        first_id, second_id = first.id, second.id
        await session.write_session.execute(
            sa.update(RDBAgentSession)
            .where(RDBAgentSession.id == f.scope.session_id)
            .values(primary_channel_binding_id=first_id if had_primary else None)
        )
    operations = RoutineNotificationOperations(
        session_manager=rdb_session_manager,
        primary=SessionPrimaryChannelRepository(),
        channels=ExternalChannelWorkRepository.create(),
        events=EventTranscriptRepository(),
        execution_authority=f.repository.execution_authority,
    )
    expected = await operations.current_primary(scope=f.scope, authority=f.authority)
    files = RoutineNotificationFiles(binding_id=expected, manifests=(), attachments=())
    item = f.states[0]
    recording = await f.repository.complete(
        scope=f.scope,
        authority=f.authority,
        slug=item.context.candidate.slug,
        execution_id=item.context.execution_id,
        work=work(notify=True, outcome=RoutineObjectiveOutcome.FINISHED),
        now=NOW,
    )
    async with rdb_session_manager() as session:
        await session.write_session.execute(
            sa.update(RDBAgentSession)
            .where(RDBAgentSession.id == f.scope.session_id)
            .values(primary_channel_binding_id=second_id)
        )
    channels = AsyncMock(spec=ExternalChannelActionService)
    publish = AsyncMock()
    service = RoutineNotificationService(
        operations=operations, completion=f.repository, channels=channels
    )
    state = await service.deliver(
        scope=f.scope,
        authority=f.authority,
        recording=recording,
        runtime=None,
        publish_event=publish,
        files=files,
    )
    assert state.delivery_status is RoutineDeliveryStatus.FAILED
    publish.assert_not_called()
    channels.execute_binding_effect.assert_not_called()
