"""Judgment persistence uses a Session observation, not ordinary Run projections."""

import sqlalchemy as sa

from azents.core.enums import EventKind
from azents.engine.events.routine_judgment_test import _observation
from azents.rdb.models.agent_run import RDBAgentRun
from azents.rdb.models.agent_session import RDBAgentSession
from azents.rdb.models.conversation import RDBConversation
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import WriteSession
from azents.repos.agent_execution import EventTranscriptRepository
from azents.repos.agent_execution.data import EventCreate
from azents.repos.routine.persistence_test import _subject


async def test_append_read_judgment_does_not_change_activity_or_context(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    repository = EventTranscriptRepository()
    async with rdb_session_manager() as session:
        scope = await _subject(session)
        root = await session.read_session.get(RDBAgentSession, scope.session_id)
        assert root is not None
        conversation = await session.read_session.scalar(
            sa.select(RDBConversation).where(
                RDBConversation.session_id == scope.session_id
            )
        )
        assert conversation is not None
        before_session = (root.last_activity_at, root.updated_at)
        before_conversation = (
            conversation.last_user_input_at,
            root.model_input_head_event_id,
        )
        payload = _observation().payload
        event = await repository.append(
            session,
            EventCreate(
                session_id=scope.session_id,
                kind=EventKind.ROUTINE_JUDGMENT,
                payload=payload.model_dump(mode="json"),
                provider="openai",
                model="synthetic-model",
            ),
        )
        await session.write_session.refresh(root)
        await session.write_session.refresh(conversation)
        assert (root.last_activity_at, root.updated_at) == before_session
        assert (
            conversation.last_user_input_at,
            root.model_input_head_event_id,
        ) == before_conversation
        assert (
            await session.read_session.scalar(
                sa.select(sa.func.count())
                .select_from(RDBAgentRun)
                .where(RDBAgentRun.session_id == scope.session_id)
            )
            == 0
        )
        restored = await repository.get_by_id(session, event_id=event.id)
        assert restored is not None and restored.payload == payload
        assert restored.provider == "openai"
        assert restored.model == "synthetic-model"
        recent = await repository.list_recent_by_session_id(
            session, scope.session_id, limit=10
        )
        assert recent == [event]
