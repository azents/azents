"""Actual history reads decode every Routine event without ordinary usage leakage."""

from azents.core.enums import EventKind, MessageRole
from azents.core.routine_execution import RoutineExecutionRef
from azents.engine.events.routine_judgment_test import _observation
from azents.engine.events.types import RoutineInputPayload, RoutineNotificationPayload
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import WriteSession
from azents.repos.agent_execution import EventTranscriptRepository
from azents.repos.agent_execution.data import EventCreate
from azents.repos.message import MessageRepository, event_to_chat_message
from azents.repos.routine.persistence_test import _subject


async def test_routine_history_and_notification_chat_projection(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    input_payload = RoutineInputPayload(
        executions=(
            RoutineExecutionRef(
                routine_id="routine-a",
                execution_id="occurrence-a",
                slug="routine-a",
                title="Routine A",
            ),
        ),
        content="Execute the stored admitted objective.",
    )
    notification = RoutineNotificationPayload(
        execution_id="occurrence-a",
        slug="routine-a",
        title="Routine A",
        content="A verified change needs attention.",
    )
    payloads = {
        EventKind.ROUTINE_JUDGMENT: _observation().payload,
        EventKind.ROUTINE_TRIGGER: input_payload,
        EventKind.ROUTINE_CONTINUATION: input_payload,
        EventKind.ROUTINE_NOTIFICATION: notification,
    }
    async with rdb_session_manager() as session:
        scope = await _subject(session)
        created = [
            await EventTranscriptRepository().append(
                session,
                EventCreate(
                    session_id=scope.session_id,
                    kind=kind,
                    payload=payload.model_dump(mode="json"),
                ),
            )
            for kind, payload in payloads.items()
        ]
    async with rdb_session_manager() as session:
        messages = MessageRepository()
        page = await messages.list_events_by_session_id_paginated(
            session, scope.session_id
        )
        assert [item.kind for item in page.items] == list(payloads)
        for original in created:
            decoded = await messages.get_event_by_id(session, original.id)
            assert decoded is not None and decoded.payload == original.payload
            row = await messages.get_by_id(session, original.id)
            assert row is not None
            projection = event_to_chat_message(row)
            if original.kind is EventKind.ROUTINE_NOTIFICATION:
                assert projection is not None
                assert projection.role is MessageRole.ASSISTANT
                assert projection.content == notification.content
                assert projection.usage is None
            else:
                assert projection is None
