"""PostgreSQL-backed Session history search and visible paging checks."""

import json

import pytest
from pydantic import TypeAdapter

from azents.core.enums import (
    EventKind,
    ExternalChannelPrincipalAuthorType,
    ExternalChannelProvider,
    ExternalChannelResourceType,
)
from azents.engine.events.conversational_tool_projection_test import _call
from azents.engine.events.types import ExternalChannelMessagePayload
from azents.engine.tools.session_history import (
    _render_event,
    _search_category,
    _search_text,
)
from azents.rdb.models.agent_session import RDBAgentSession
from azents.rdb.models.event import JSONValue, RDBEvent
from azents.rdb.session_capabilities import WriteSession
from azents.repos.message import MessageRepository
from azents.repos.message.repository_test import _create_agent_session
from azents.repos.session_history.operations import SessionHistoryEvent
from azents.repos.session_history.repository import (
    VISIBLE_KINDS,
    SessionHistoryRepository,
    SessionHistoryScope,
)

_PAYLOAD_ADAPTER: TypeAdapter[dict[str, JSONValue]] = TypeAdapter(dict[str, JSONValue])


async def _event(
    session: WriteSession,
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
    session.write_session.add(row)
    await session.write_session.flush()
    return row.id


async def test_search_visible_scalar_and_part_text_without_file_metadata(
    rdb_session: WriteSession,
) -> None:
    """Only exposed user text can match; returned anchors locate actual events."""
    session_id = await _create_agent_session(rdb_session)
    root = await rdb_session.read_session.get(RDBAgentSession, session_id)
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
        exclude_tools=True,
        limit=10,
        before=None,
    )
    assert [hit.session_id for hit in roots.items] == [session_id]
    assert roots.items[0].event_id == match_id

    hits = await repo.search_events(
        rdb_session,
        session_id=session_id,
        query="purple comet",
        exclude_tools=True,
        limit=10,
        before=None,
    )
    assert [hit.event_id for hit in hits.items] == [match_id]
    external_hits = await repo.search_events(
        rdb_session,
        session_id=session_id,
        query="discord signal",
        exclude_tools=True,
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
            exclude_tools=True,
            limit=10,
            before=None,
        )
        assert no_hits.items == []


async def test_visible_paging_skips_hidden_and_reverted_events_in_flags(
    rdb_session: WriteSession,
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


@pytest.mark.parametrize("exclude_tools", [False, True])
async def test_conversation_search_survives_tool_exclusion_and_round_trips(
    rdb_session: WriteSession, exclude_tools: bool
) -> None:
    """Channel, scheduled and Routine reports remain visible as conversation."""
    session_id = await _create_agent_session(rdb_session)
    call = _call(
        {
            "message": "channel public needle",
            "title": "hidden work title",
            "todo_update": [{"title": "hidden internal task"}],
        }
    )
    await _event(
        rdb_session,
        session_id,
        1,
        EventKind.CLIENT_TOOL_CALL,
        call.model_dump(mode="json"),
    )
    await _event(
        rdb_session,
        session_id,
        2,
        EventKind.CLIENT_TOOL_RESULT,
        {
            "call_id": call.call_id,
            "name": "channel_action",
            "wire_dialect": "json_function",
            "status": "completed",
            "output": json.dumps(
                {
                    "outcomes": [
                        {"operation": "reply", "status": "delivered"},
                        {"operation": "reply", "status": "failed"},
                    ]
                }
            ),
        },
    )
    await _event(
        rdb_session,
        session_id,
        3,
        EventKind.SCHEDULED_TASK_RESULT,
        {
            "title": "Morning report",
            "scheduled_for": "2026-10-22T00:00:00Z",
            "status": "finished",
            "result": "scheduled public needle",
        },
    )
    await _event(
        rdb_session,
        session_id,
        4,
        EventKind.ROUTINE_NOTIFICATION,
        {
            "execution_id": "chat-exec",
            "slug": "watch",
            "title": "Watch",
            "content": "routine chat public needle",
        },
    )
    for order, execution_id, message in (
        (5, "channel-exec", "routine channel public needle"),
        (6, "chat-exec", "routine chat public needle"),
    ):
        await _event(
            rdb_session,
            session_id,
            order,
            EventKind.CLIENT_TOOL_RESULT,
            {
                "call_id": f"routine-{order}",
                "name": "record_routine_result",
                "wire_dialect": "json_function",
                "status": "completed",
                "output": json.dumps(
                    {
                        "created": True,
                        "execution": {
                            "context": {"execution_id": execution_id},
                            "work": {
                                "notify": True,
                                "message": message,
                                "result": "hidden internal result",
                                "next_hint": "hidden internal hint",
                            },
                            "delivery_status": "delivered",
                        },
                    }
                ),
            },
        )
    repo = SessionHistoryRepository()
    hits = await repo.search_events(
        rdb_session,
        session_id=session_id,
        query="public needle",
        exclude_tools=exclude_tools,
        limit=10,
        before=None,
    )
    assert [int(hit.event_id, 16) for hit in hits.items] == [5, 4, 3, 1]
    assert all(
        _search_category(hit.kind, hit.payload) == "conversation" for hit in hits.items
    )
    assert [_search_text(hit.kind, hit.payload) for hit in hits.items] == [
        "routine channel public needle",
        "routine chat public needle",
        "scheduled public needle",
        "channel public needle",
    ]
    root = await rdb_session.read_session.get(RDBAgentSession, session_id)
    assert root is not None
    roots = await repo.search_roots(
        rdb_session,
        scope=SessionHistoryScope(
            agent_id=root.agent_id,
            workspace_id=root.workspace_id,
            associated_user_id=None,
        ),
        query="public needle",
        exclude_tools=exclude_tools,
        limit=10,
        before=None,
    )
    assert roots.items[0].event_id == hits.items[0].event_id
    projections = await repo.conversation_projections(
        rdb_session,
        session_id=session_id,
        event_ids=[hit.event_id for hit in hits.items],
    )
    assert projections[f"{1:032x}"].delivery_status == "partial"
    assert projections[f"{5:032x}"].delivery_status == "delivered"
    page = await MessageRepository().list_events_by_session_id_paginated(
        rdb_session,
        session_id,
        limit=10,
        visible_kinds=VISIBLE_KINDS,
    )
    rendered = [
        _render_event(
            SessionHistoryEvent(
                id=event.id,
                session_id=event.session_id,
                kind=event.kind,
                payload=event.payload,
                created_at=event.created_at,
                reverted=False,
                conversation=projections.get(event.id),
            )
        )
        for event in page.items
    ]
    assert [item["text"] for item in rendered if "text" in item] == [
        "channel public needle",
        "scheduled public needle",
        "routine chat public needle",
        "routine channel public needle",
    ]
    assert all(item["role"] == "assistant" for item in rendered if "text" in item)
    scheduled = next(
        item for item in rendered if item["kind"] == "scheduled_task_result"
    )
    assert scheduled["status"] == "finished"
    assert "delivery_status" not in scheduled
    for hidden in (
        "hidden work title",
        "hidden internal task",
        "hidden internal result",
        "hidden internal hint",
    ):
        hidden_hits = await repo.search_events(
            rdb_session,
            session_id=session_id,
            query=hidden,
            exclude_tools=exclude_tools,
            limit=10,
            before=None,
        )
        assert hidden_hits.items == []


@pytest.mark.parametrize("exclude_tools", [False, True])
async def test_tool_output_search_option_never_searches_inputs_or_native_data(
    rdb_session: WriteSession, exclude_tools: bool
) -> None:
    """Only semantic tool output is optional; input and file metadata stay private."""
    session_id = await _create_agent_session(rdb_session)
    await _event(
        rdb_session,
        session_id,
        1,
        EventKind.CLIENT_TOOL_CALL,
        _call({"message": "input secret"})
        .model_copy(update={"name": "ordinary_tool"})
        .model_dump(mode="json"),
    )
    await _event(
        rdb_session,
        session_id,
        2,
        EventKind.CLIENT_TOOL_RESULT,
        {
            "call_id": "tool-1",
            "name": "ordinary_tool",
            "wire_dialect": "json_function",
            "status": "completed",
            "output": [
                {"type": "output_text", "text": "tool output needle"},
                {
                    "type": "file",
                    "name": "file secret",
                    "media_type": "text/plain",
                    "model_file_id": "file-1",
                },
            ],
            "metadata": {"private": "metadata secret"},
        },
    )
    repo = SessionHistoryRepository()
    hits = await repo.search_events(
        rdb_session,
        session_id=session_id,
        query="tool output needle",
        exclude_tools=exclude_tools,
        limit=10,
        before=None,
    )
    assert len(hits.items) == (0 if exclude_tools else 1)
    for query in ("input secret", "file secret", "metadata secret"):
        hidden_hits = await repo.search_events(
            rdb_session,
            session_id=session_id,
            query=query,
            exclude_tools=exclude_tools,
            limit=10,
            before=None,
        )
        assert hidden_hits.items == []


@pytest.mark.parametrize(
    ("arguments", "dialect"),
    [
        ('{"mode":"ignore","message":"hidden needle"}', "json_function"),
        ('{"message":17}', "json_function"),
        ('{"message":"hidden needle"', "json_function"),
        ('{"message":"hidden needle"}', "plaintext_custom"),
    ],
)
async def test_invalid_or_ignored_channel_calls_do_not_match(
    rdb_session: WriteSession, arguments: str, dialect: str
) -> None:
    """Historical malformed inputs cannot break search or become conversation."""
    session_id = await _create_agent_session(rdb_session)
    payload = _call({}).model_dump(mode="json")
    payload.update(arguments=arguments, wire_dialect=dialect)
    await _event(
        rdb_session,
        session_id,
        1,
        EventKind.CLIENT_TOOL_CALL,
        payload,
    )
    hits = await SessionHistoryRepository().search_events(
        rdb_session,
        session_id=session_id,
        query="needle",
        exclude_tools=False,
        limit=10,
        before=None,
    )
    assert hits.items == []


@pytest.mark.parametrize("exclude_tools", [False, True])
async def test_hosted_output_filtering_applies_before_paging_and_root_discovery(
    rdb_session: WriteSession,
    exclude_tools: bool,
) -> None:
    """The flag filters in SQL, before keysets and lookahead limits."""
    session_id = await _create_agent_session(rdb_session)
    await _event(
        rdb_session,
        session_id,
        1,
        EventKind.ASSISTANT_MESSAGE,
        {"content": "literal 100%_needle"},
    )
    await _event(
        rdb_session,
        session_id,
        2,
        EventKind.CLIENT_TOOL_RESULT,
        {
            "call_id": "ordinary",
            "name": "read",
            "wire_dialect": "json_function",
            "status": "completed",
            "output": "literal 100%_needle",
        },
    )
    await _event(
        rdb_session,
        session_id,
        3,
        EventKind.PROVIDER_TOOL_CALL,
        {
            "call_id": "hosted",
            "name": "web_search",
            "status": "completed",
            "semantic": {
                "input": "hidden hosted input",
                "output": [
                    {"type": "output_text", "text": "literal 100%_needle"},
                ],
                "references": [{"title": "hidden hosted metadata"}],
            },
            "native_artifact": {"private": "hidden hosted native"},
        },
    )
    repo = SessionHistoryRepository()
    root = await rdb_session.read_session.get(RDBAgentSession, session_id)
    assert root is not None
    scope = SessionHistoryScope(
        agent_id=root.agent_id,
        workspace_id=root.workspace_id,
        associated_user_id=None,
    )
    roots = await repo.search_roots(
        rdb_session,
        scope=scope,
        query="100%_needle",
        exclude_tools=exclude_tools,
        limit=1,
        before=None,
    )
    expected_id = f"{1 if exclude_tools else 3:032x}"
    assert roots.items[0].event_id == expected_id
    page = await repo.search_events(
        rdb_session,
        session_id=session_id,
        query="100%_needle",
        exclude_tools=exclude_tools,
        limit=1,
        before=None,
    )
    assert page.items[0].event_id == expected_id
    assert page.has_more is (not exclude_tools)
    for query in (
        "hidden hosted input",
        "hidden hosted metadata",
        "hidden hosted native",
    ):
        no_hits = await repo.search_events(
            rdb_session,
            session_id=session_id,
            query=query,
            exclude_tools=exclude_tools,
            limit=10,
            before=None,
        )
        assert no_hits.items == []


@pytest.mark.parametrize(
    ("notify", "created", "reverted"),
    [(False, True, False), (True, False, False), (True, True, True)],
)
async def test_silent_replayed_or_reverted_routine_result_is_not_conversation(
    rdb_session: WriteSession,
    notify: bool,
    created: bool,
    reverted: bool,
) -> None:
    session_id = await _create_agent_session(rdb_session)
    await _event(
        rdb_session,
        session_id,
        1,
        EventKind.CLIENT_TOOL_RESULT,
        {
            "call_id": "routine",
            "name": "record_routine_result",
            "wire_dialect": "json_function",
            "status": "completed",
            "output": json.dumps(
                {
                    "created": created,
                    "execution": {
                        "context": {"execution_id": "exec"},
                        "work": {"notify": notify, "message": "silent needle"},
                        "delivery_status": "delivered",
                    },
                }
            ),
        },
        reverted=reverted,
    )
    for exclude_tools in (False, True):
        hits = await SessionHistoryRepository().search_events(
            rdb_session,
            session_id=session_id,
            query="silent needle",
            exclude_tools=exclude_tools,
            limit=10,
            before=None,
        )
        assert hits.items == []
