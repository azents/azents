"""PostgreSQL-backed Session history search and visible paging checks."""

import json
from contextlib import asynccontextmanager
from typing import AsyncIterator

from pydantic import TypeAdapter
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    EventKind,
    ExternalChannelPrincipalAuthorType,
    ExternalChannelProvider,
    ExternalChannelResourceType,
)
from azents.engine.events.types import ExternalChannelMessagePayload
from azents.engine.tools.session_history import make_session_history_tools
from azents.rdb.models.agent_session import RDBAgentSession
from azents.rdb.models.event import JSONValue, RDBEvent
from azents.repos.message import MessageRepository
from azents.repos.message.repository_test import _create_agent_session
from azents.repos.session_history.repository import (
    VISIBLE_KINDS,
    SessionHistoryRepository,
    SessionHistoryScope,
)

_PAYLOAD_ADAPTER: TypeAdapter[dict[str, JSONValue]] = TypeAdapter(dict[str, JSONValue])


async def _event(
    session: AsyncSession,
    session_id: str,
    order: int,
    kind: EventKind,
    payload: dict[str, object],
    *,
    reverted: bool = False,
) -> str:
    row = RDBEvent(
        session_id=session_id,
        kind=kind,
        payload=_PAYLOAD_ADAPTER.validate_python(payload),
        reverted=reverted,
    )
    row.id = f"{order:032x}"
    session.add(row)
    await session.flush()
    return row.id


async def test_search_visible_scalar_and_part_text_without_file_metadata(
    rdb_session: AsyncSession,
) -> None:
    """Only exposed user text can match; returned anchors locate actual events."""
    session_id = await _create_agent_session(rdb_session)
    root = await rdb_session.get(RDBAgentSession, session_id)
    assert root is not None
    scope = SessionHistoryScope(
        agent_id=root.agent_id,
        workspace_id=root.workspace_id,
        associated_user_id=None,
    )
    await _event(
        rdb_session,
        session_id,
        1,
        EventKind.USER_MESSAGE,
        {"sender_user_id": None, "content": "first lunar echo"},
    )
    match_id = await _event(
        rdb_session,
        session_id,
        2,
        EventKind.USER_MESSAGE,
        {
            "sender_user_id": None,
            "content": [
                {"type": "input_text", "text": "purple comet"},
                {
                    "type": "file",
                    "model_file_id": "file-1",
                    "media_type": "text/plain",
                    "name": "hidden-filename-needle",
                },
            ],
        },
    )
    await _event(
        rdb_session,
        session_id,
        3,
        EventKind.REASONING,
        {"text": "internal-needle"},
    )
    await _event(
        rdb_session,
        session_id,
        4,
        EventKind.CLIENT_TOOL_RESULT,
        {"output": "tool-result-needle"},
    )
    external = ExternalChannelMessagePayload(
        provider=ExternalChannelProvider.DISCORD,
        provider_tenant_id="private-tenant-id",
        resource_id="resource-1",
        resource_label="test channel",
        resource_type=ExternalChannelResourceType.THREAD,
        binding_id="binding-1",
        invocation_batch_id="batch-1",
        external_message_id="external-1",
        projection_root_id="external-channel:binding-1:external-1",
        provider_message_key="discord:resource-1:external-1",
        provider_position="00000000000000000001",
        principal_id="principal-1",
        provider_user_id="private-provider-id",
        sender_display_name="Test",
        author_type=ExternalChannelPrincipalAuthorType.HUMAN,
        prompt_role="invocation",
        body="Discord signal memory",
        attachment_metadata={},
        provider_created_at=None,
        provider_updated_at=None,
        original_url=None,
        truncated_context_message_count=0,
        truncated_context_size=0,
    )
    external_id = await _event(
        rdb_session,
        session_id,
        5,
        EventKind.EXTERNAL_CHANNEL_MESSAGE,
        external.model_dump(mode="json"),
    )
    repo = SessionHistoryRepository()

    roots = await repo.search_roots(
        rdb_session,
        scope=scope,
        query="PURPLE comet",
        limit=10,
        before=None,
    )
    assert [hit.session_id for hit in roots.items] == [session_id]
    assert roots.items[0].event_id == match_id

    hits = await repo.search_events(
        rdb_session,
        session_id=session_id,
        query="purple comet",
        limit=10,
        before=None,
    )
    assert [hit.event_id for hit in hits.items] == [match_id]
    external_hits = await repo.search_events(
        rdb_session,
        session_id=session_id,
        query="discord signal",
        limit=10,
        before=None,
    )
    assert [hit.event_id for hit in external_hits.items] == [external_id]
    for hidden in (
        "hidden-filename-needle",
        "internal-needle",
        "tool-result-needle",
        "private-provider-id",
    ):
        no_hits = await repo.search_events(
            rdb_session,
            session_id=session_id,
            query=hidden,
            limit=10,
            before=None,
        )
        assert no_hits.items == []


async def test_visible_paging_skips_hidden_and_reverted_events_in_flags(
    rdb_session: AsyncSession,
) -> None:
    """Event filtering happens before limits and both direction existence checks."""
    session_id = await _create_agent_session(rdb_session)
    first = await _event(
        rdb_session,
        session_id,
        1,
        EventKind.USER_MESSAGE,
        {"sender_user_id": None, "content": "first"},
    )
    await _event(
        rdb_session,
        session_id,
        2,
        EventKind.REASONING,
        {"text": "private"},
    )
    last = await _event(
        rdb_session,
        session_id,
        3,
        EventKind.USER_MESSAGE,
        {"sender_user_id": None, "content": "last"},
    )
    await _event(
        rdb_session,
        session_id,
        4,
        EventKind.USER_MESSAGE,
        {"sender_user_id": None, "content": "reverted"},
        reverted=True,
    )
    await _event(
        rdb_session,
        session_id,
        5,
        EventKind.REASONING,
        {"text": "another hidden event"},
    )
    repo = MessageRepository()

    latest = await repo.list_events_by_session_id_paginated(
        rdb_session, session_id, limit=1, visible_kinds=VISIBLE_KINDS
    )
    assert [event.id for event in latest.items] == [last]
    assert latest.has_more is True
    assert latest.has_newer is False

    older = await repo.list_events_by_session_id_paginated(
        rdb_session, session_id, limit=1, before=last, visible_kinds=VISIBLE_KINDS
    )
    assert [event.id for event in older.items] == [first]
    assert older.has_more is False
    assert older.has_newer is True

    anchored = await repo.list_events_by_session_id_paginated(
        rdb_session, session_id, limit=1, around=first, visible_kinds=VISIBLE_KINDS
    )
    assert [event.id for event in anchored.items] == [first]
    assert anchored.has_newer is True


async def test_bound_tool_handlers_read_search_page_and_one_result_from_database(
    rdb_session: AsyncSession,
) -> None:
    """Exercise the real tool handlers and repositories against one event transcript."""
    session_id = await _create_agent_session(rdb_session)
    root = await rdb_session.get(RDBAgentSession, session_id)
    assert root is not None
    match_id = await _event(
        rdb_session,
        session_id,
        1,
        EventKind.USER_MESSAGE,
        {"sender_user_id": None, "content": "lunar memory"},
    )
    await _event(
        rdb_session,
        session_id,
        2,
        EventKind.REASONING,
        {"text": "hidden"},
    )
    result_id = await _event(
        rdb_session,
        session_id,
        3,
        EventKind.CLIENT_TOOL_RESULT,
        {
            "call_id": "call-1",
            "name": "example_tool",
            "status": "completed",
            "output": "selected result only",
        },
    )

    @asynccontextmanager
    async def manager() -> AsyncIterator[AsyncSession]:
        yield rdb_session

    tools = {
        tool.spec.name: tool
        for tool in make_session_history_tools(
            agent_id=root.agent_id,
            current_session_id=session_id,
            session_manager=manager,
        )
    }
    search = await tools["search_sessions"].handler(
        json.dumps({"session_id": "current", "query": "lunar"})
    )
    assert isinstance(search, str)
    assert json.loads(search)["matches"][0]["event_id"] == match_id

    page = await tools["read_session_history"].handler(
        json.dumps({"session_id": session_id, "around_event_id": match_id})
    )
    assert isinstance(page, str)
    items = json.loads(page)["events"]
    assert [item["event_id"] for item in items] == [match_id]

    latest = await tools["read_session_history"].handler(
        json.dumps({"session_id": session_id})
    )
    assert isinstance(latest, str)
    output = json.loads(latest)
    assert [item["event_id"] for item in output["events"]] == [match_id, result_id]
    assert "selected result only" not in latest
    assert output["events"][1]["has_text"] is True

    detail = await tools["read_session_tool_result"].handler(
        json.dumps({"session_id": session_id, "event_id": result_id})
    )
    assert isinstance(detail, str)
    assert json.loads(detail)["text"] == "selected result only"
