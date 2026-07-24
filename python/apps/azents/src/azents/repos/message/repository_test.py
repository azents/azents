"""Message repository pagination tests."""

from pydantic import TypeAdapter
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import EventKind, LLMProvider
from azents.engine.events.types import UserMessagePayload
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.agent_runtime import RDBAgentRuntime
from azents.rdb.models.event import JSONValue, RDBEvent
from azents.rdb.models.llm_provider_integration import RDBLLMProviderIntegration
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.agent_session.data import AgentSessionCreate
from azents.repos.message import MessageRepository
from azents.repos.workspace import WorkspaceRepository
from azents.repos.workspace.data import WorkspaceCreate
from azents.testing.model_selection import make_test_model_selection_dict

_JSON_PAYLOAD_ADAPTER: TypeAdapter[dict[str, JSONValue]] = TypeAdapter(
    dict[str, JSONValue]
)


async def _create_agent_session(session: AsyncSession) -> str:
    """Create an AgentSession for message repository tests."""
    handle = "message-pagination"
    await WorkspaceRepository().create(
        session,
        WorkspaceCreate(name="Message pagination test", handle=handle),
    )
    workspace_id = await WorkspaceRepository().resolve_id(session, handle)
    assert workspace_id is not None
    integration = RDBLLMProviderIntegration(
        workspace_id=workspace_id,
        provider=LLMProvider.ANTHROPIC,
        name="message-pagination-integration",
        encrypted_credentials="encrypted-test-value",
        config=None,
    )
    session.add(integration)
    await session.flush()
    model_selection = make_test_model_selection_dict(
        integration_id=integration.id,
        provider=LLMProvider.ANTHROPIC,
        model_identifier="message-pagination-model",
    )
    agent = RDBAgent(
        workspace_id=workspace_id,
        name="Message pagination test agent",
        model_selection=model_selection,
        lightweight_model_selection=model_selection,
    )
    session.add(agent)
    await session.flush()
    session.add(RDBAgentRuntime(workspace_id=workspace_id, agent_id=agent.id))
    await session.flush()
    agent_session = await AgentSessionRepository().create(
        session,
        AgentSessionCreate(
            workspace_id=workspace_id,
            agent_id=agent.id,
            title=None,
        ),
    )
    return agent_session.id


async def _create_events(session: AsyncSession, session_id: str) -> list[str]:
    """Create five ordered durable events and one reverted event."""
    ids = [f"{order:032x}" for order in range(1, 6)]
    for order, event_id in enumerate(ids, start=1):
        payload = _JSON_PAYLOAD_ADAPTER.validate_python(
            UserMessagePayload(
                sender_user_id=None, content=f"event-{order}"
            ).model_dump(mode="json")
        )
        event = RDBEvent(
            session_id=session_id,
            kind=EventKind.USER_MESSAGE,
            payload=payload,
            model_order=order,
        )
        event.id = event_id
        session.add(event)

    reverted = RDBEvent(
        session_id=session_id,
        kind=EventKind.USER_MESSAGE,
        payload=_JSON_PAYLOAD_ADAPTER.validate_python(
            UserMessagePayload(sender_user_id=None, content="reverted").model_dump(
                mode="json"
            )
        ),
        model_order=6,
        reverted=True,
    )
    reverted.id = f"{6:032x}"
    session.add(reverted)
    await session.flush()
    return ids


class TestMessageRepositoryPagination:
    """Bidirectional event pagination reports both boundary directions."""

    async def test_default_before_and_after_pages_have_directional_flags(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        session_id = await _create_agent_session(rdb_session)
        event_ids = await _create_events(rdb_session, session_id)
        repo = MessageRepository()

        latest, has_more, has_newer = await repo.list_events_by_session_id_paginated(
            rdb_session,
            session_id,
            limit=2,
        )
        assert [event.id for event in latest] == event_ids[3:5]
        assert has_more is True
        assert has_newer is False

        older, has_more, has_newer = await repo.list_events_by_session_id_paginated(
            rdb_session,
            session_id,
            limit=2,
            before=event_ids[3],
        )
        assert [event.id for event in older] == event_ids[1:3]
        assert has_more is True
        assert has_newer is True

        newer, has_more, has_newer = await repo.list_events_by_session_id_paginated(
            rdb_session,
            session_id,
            limit=2,
            after=event_ids[1],
        )
        assert [event.id for event in newer] == event_ids[2:4]
        assert has_more is True
        assert has_newer is True

    async def test_empty_boundary_pages_still_report_opposite_direction(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        session_id = await _create_agent_session(rdb_session)
        event_ids = await _create_events(rdb_session, session_id)
        repo = MessageRepository()

        (
            before_oldest,
            has_more,
            has_newer,
        ) = await repo.list_events_by_session_id_paginated(
            rdb_session,
            session_id,
            before=event_ids[0],
        )
        assert before_oldest == []
        assert has_more is False
        assert has_newer is True

        (
            after_newest,
            has_more,
            has_newer,
        ) = await repo.list_events_by_session_id_paginated(
            rdb_session,
            session_id,
            after=event_ids[-1],
        )
        assert after_newest == []
        assert has_more is True
        assert has_newer is False
