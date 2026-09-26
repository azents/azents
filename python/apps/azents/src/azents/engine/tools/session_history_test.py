"""Memory-gated history tool authority and output checks."""

import base64
import json
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, AsyncIterator, NamedTuple, cast
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    AgentSessionKind,
    AgentSessionProductMode,
    AgentSessionStatus,
    EventKind,
)
from azents.engine.events.types import (
    Event,
    NativeArtifact,
    OutputTextPart,
    ProviderToolCallPayload,
    ProviderToolSemanticContent,
)
from azents.engine.run.types import FunctionTool, FunctionToolError
from azents.engine.tools import session_history as history_module
from azents.rdb.models.event import RDBEvent
from azents.rdb.session import SessionManager
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.agent_session.data import AgentSession
from azents.repos.message import MessageRepository
from azents.repos.session_history.repository import (
    EventSearchHit,
    SearchPage,
    SessionHistoryRepository,
)
from azents.repos.workspace_user import WorkspaceUserRepository

_CURRENT = "1" * 32
_TARGET = "2" * 32
_CHILD = "3" * 32
_EVENT = "4" * 32


def _root(
    session_id: str,
    *,
    mode: AgentSessionProductMode = AgentSessionProductMode.TEAM,
    owner: str | None = None,
    status: AgentSessionStatus = AgentSessionStatus.ACTIVE,
    agent_id: str = "agent-1",
) -> AgentSession:
    return AgentSession.model_construct(
        id=session_id,
        workspace_id="workspace-1",
        agent_id=agent_id,
        session_kind=AgentSessionKind.ROOT,
        status=status,
        product_mode=mode,
        associated_user_id=owner,
    )


def _child(session_id: str) -> AgentSession:
    return AgentSession.model_construct(
        id=session_id,
        workspace_id="workspace-1",
        agent_id="agent-1",
        session_kind=AgentSessionKind.SUBAGENT,
        status=AgentSessionStatus.ACTIVE,
        product_mode=None,
    )


@asynccontextmanager
async def _session_context() -> AsyncIterator[AsyncSession]:
    yield cast(AsyncSession, AsyncMock())


class _HistoryToolFixture(NamedTuple):
    """Named tools and injected repository doubles for one test."""

    tools: dict[str, FunctionTool]
    history: AsyncMock
    messages: AsyncMock
    users: AsyncMock


def _tools(
    monkeypatch: pytest.MonkeyPatch,
    *,
    current: AgentSession,
    target: AgentSession | None = None,
    root: AgentSession | None = None,
) -> _HistoryToolFixture:
    """Provide injected repositories for one execution-bound tool factory."""
    sessions = AsyncMock(spec=AgentSessionRepository)
    history = AsyncMock(spec=SessionHistoryRepository)
    messages = AsyncMock(spec=MessageRepository)
    users = AsyncMock(spec=WorkspaceUserRepository)
    known = {current.id: current}
    if target is not None:
        known[target.id] = target
    if root is not None:
        known[root.id] = root
        sessions.get_root_session_agent_by_session_id.return_value = SimpleNamespace(
            agent_session_id=root.id
        )
    sessions.get_by_id.side_effect = lambda _session, session_id: known.get(session_id)
    users.get_by_workspace_and_user.return_value = SimpleNamespace()
    monkeypatch.setattr(history_module, "AgentSessionRepository", lambda: sessions)
    monkeypatch.setattr(history_module, "SessionHistoryRepository", lambda: history)
    monkeypatch.setattr(history_module, "MessageRepository", lambda: messages)
    monkeypatch.setattr(history_module, "WorkspaceUserRepository", lambda: users)
    tools = history_module.make_session_history_tools(
        agent_id="agent-1",
        current_session_id=current.id,
        session_manager=cast(SessionManager[AsyncSession], _session_context),
    )
    return _HistoryToolFixture(
        tools={tool.spec.name: tool for tool in tools},
        history=history,
        messages=messages,
        users=users,
    )


async def _json_result(
    tool: FunctionTool, arguments: dict[str, object]
) -> dict[str, Any]:
    raw = await tool.handler(json.dumps(arguments))
    assert isinstance(raw, str)
    decoded = json.loads(raw)
    assert isinstance(decoded, dict)
    return decoded


def _cursor(payload: dict[str, object]) -> str:
    """Encode a deliberately controlled cursor payload for validation tests."""
    return base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")


@pytest.mark.parametrize(
    "payload",
    [
        {"time": "2026-09-26T00:00:00+00:00", "session": _CURRENT, "extra": 1},
        {"time": "not-a-date", "session": _CURRENT},
        {"time": "2026-09-26T00:00:00+00:00", "session": 42},
    ],
)
async def test_global_search_rejects_invalid_cursor_payload(
    monkeypatch: pytest.MonkeyPatch, payload: dict[str, object]
) -> None:
    """Global search validates its opaque continuation before querying."""
    fixture = _tools(monkeypatch, current=_root(_CURRENT))
    with pytest.raises(FunctionToolError, match="Invalid history cursor"):
        await fixture.tools["search_sessions"].handler(
            json.dumps({"cursor": _cursor(payload)})
        )
    fixture.history.search_roots.assert_not_awaited()


async def test_global_search_accepts_typed_cursor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A valid continuation passes the parsed time and Session ID to SQL."""
    fixture = _tools(monkeypatch, current=_root(_CURRENT))
    fixture.history.search_roots.return_value = SearchPage(items=[], has_more=False)
    await _json_result(
        fixture.tools["search_sessions"],
        {"cursor": _cursor({"time": "2026-09-26T00:00:00+00:00", "session": _CURRENT})},
    )
    assert fixture.history.search_roots.await_args.kwargs["before"] == (
        datetime(2026, 9, 26, tzinfo=UTC),
        _CURRENT,
    )


async def test_current_search_uses_concrete_child_but_root_team_authority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The current selector never substitutes the root Session's ID."""
    root = _root(_CURRENT)
    child = _child(_CHILD)
    fixture = _tools(monkeypatch, current=child, root=root)
    tools, history = fixture.tools, fixture.history
    history.search_events.return_value = SearchPage(
        items=[
            EventSearchHit(
                event_id=_EVENT,
                kind=EventKind.USER_MESSAGE,
                payload={"sender_user_id": None, "content": "purple comet"},
                created_at=datetime.now(UTC),
            )
        ],
        has_more=False,
    )

    result = await _json_result(
        tools["search_sessions"], {"query": "comet", "session_id": "current"}
    )

    assert result["session_id"] == _CHILD
    assert result["matches"][0]["event_id"] == _EVENT
    assert result["matches"][0]["snippet"] == "purple comet"
    assert history.search_events.await_args.kwargs["session_id"] == _CHILD


@pytest.mark.parametrize(
    ("mode", "owner", "permitted"),
    [
        (AgentSessionProductMode.TEAM, None, True),
        (AgentSessionProductMode.USER, "user-1", False),
    ],
)
async def test_team_execution_cannot_read_private_user_session(
    monkeypatch: pytest.MonkeyPatch,
    mode: AgentSessionProductMode,
    owner: str | None,
    permitted: bool,
) -> None:
    """Known IDs must not authorize private history for Team execution."""
    fixture = _tools(
        monkeypatch,
        current=_root(_CURRENT),
        target=_root(_TARGET, mode=mode, owner=owner),
    )
    tools, messages = fixture.tools, fixture.messages
    if not permitted:
        with pytest.raises(FunctionToolError, match="Session history is unavailable"):
            await tools["read_session_history"].handler(
                json.dumps({"session_id": _TARGET})
            )
        messages.list_events_by_session_id_paginated.assert_not_awaited()
        return
    messages.list_events_by_session_id_paginated.return_value = SimpleNamespace(
        items=[], has_more=False, has_newer=False
    )
    result = await _json_result(tools["read_session_history"], {"session_id": _TARGET})
    assert result["session_id"] == _TARGET


async def test_user_execution_can_read_own_private_and_team_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Association and current Workspace membership bound private reads."""
    own = _root(_CURRENT, mode=AgentSessionProductMode.USER, owner="user-1")
    other = _root(_TARGET, mode=AgentSessionProductMode.USER, owner="user-2")
    fixture = _tools(monkeypatch, current=own, target=other)
    tools, messages, users = fixture.tools, fixture.messages, fixture.users
    with pytest.raises(FunctionToolError, match="Session history is unavailable"):
        await tools["read_session_history"].handler(json.dumps({"session_id": _TARGET}))
    messages.list_events_by_session_id_paginated.assert_not_awaited()
    users.get_by_workspace_and_user.assert_awaited()

    users.get_by_workspace_and_user.return_value = None
    with pytest.raises(FunctionToolError, match="Session history is unavailable"):
        await tools["search_sessions"].handler(json.dumps({"query": "private"}))


async def test_archived_target_denied_even_when_id_was_known(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Archive is read-time unavailability, not just a search filter."""
    archived = _root(_TARGET, status=AgentSessionStatus.ARCHIVED)
    fixture = _tools(monkeypatch, current=_root(_CURRENT), target=archived)
    tools, history, messages = fixture.tools, fixture.history, fixture.messages
    for name, args in (
        ("search_sessions", {"session_id": _TARGET, "query": "word"}),
        ("read_session_history", {"session_id": _TARGET}),
        ("read_session_tool_result", {"session_id": _TARGET, "event_id": _EVENT}),
    ):
        with pytest.raises(FunctionToolError, match="Session history is unavailable"):
            await tools[name].handler(json.dumps(args))
    history.search_events.assert_not_awaited()
    messages.get_by_id.assert_not_awaited()


async def test_selected_result_only_returns_text_chunks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Tool arguments, attachment metadata and other events never enter output."""
    fixture = _tools(monkeypatch, current=_root(_CURRENT), target=_root(_TARGET))
    tools, messages = fixture.tools, fixture.messages
    row = RDBEvent(
        session_id=_TARGET,
        kind=EventKind.CLIENT_TOOL_RESULT,
        payload={
            "call_id": "call-1",
            "name": "test_tool",
            "status": "completed",
            "output": [
                {"type": "text", "text": "a" * 2100},
                {
                    "type": "file",
                    "model_file_id": "hidden-file",
                    "media_type": "text/plain",
                    "name": "hidden-name",
                },
            ],
        },
    )
    row.id = _EVENT
    messages.get_by_id.return_value = row
    first = await _json_result(
        tools["read_session_tool_result"], {"session_id": _TARGET, "event_id": _EVENT}
    )
    assert first["text"] == "a" * 2000
    assert "hidden-file" not in json.dumps(first)
    assert first["next_cursor"] is not None
    second = await _json_result(
        tools["read_session_tool_result"],
        {
            "session_id": _TARGET,
            "event_id": _EVENT,
            "cursor": first["next_cursor"],
        },
    )
    assert second["text"] == "a" * 100
    assert second["next_cursor"] is None


async def test_selected_result_caps_unbounded_persisted_tool_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Tool-provided names cannot turn a bounded result into unbounded output."""
    fixture = _tools(monkeypatch, current=_root(_CURRENT), target=_root(_TARGET))
    tools, messages = fixture.tools, fixture.messages
    row = RDBEvent(
        session_id=_TARGET,
        kind=EventKind.CLIENT_TOOL_RESULT,
        payload={
            "call_id": "call-1",
            "name": "x" * 5000,
            "status": "completed",
            "output": "short",
        },
    )
    row.id = _EVENT
    messages.get_by_id.return_value = row
    result = await _json_result(
        tools["read_session_tool_result"], {"session_id": _TARGET, "event_id": _EVENT}
    )
    assert result["tool"] == "x" * 160


async def test_result_cursor_is_not_authority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A copied cursor never permits access to a different target event."""
    fixture = _tools(monkeypatch, current=_root(_CURRENT), target=_root(_TARGET))
    tools, messages = fixture.tools, fixture.messages
    row = RDBEvent(
        session_id=_TARGET,
        kind=EventKind.CLIENT_TOOL_RESULT,
        payload={
            "call_id": "call-1",
            "name": "test_tool",
            "status": "completed",
            "output": "a" * 3000,
        },
    )
    row.id = _EVENT
    messages.get_by_id.return_value = row
    result = await _json_result(
        tools["read_session_tool_result"], {"session_id": _TARGET, "event_id": _EVENT}
    )
    with pytest.raises(FunctionToolError, match="Invalid history cursor"):
        await tools["read_session_tool_result"].handler(
            json.dumps(
                {
                    "session_id": _TARGET,
                    "event_id": "5" * 32,
                    "cursor": result["next_cursor"],
                }
            )
        )


@pytest.mark.parametrize(
    "offset",
    [True, "1", -1],
)
async def test_result_cursor_rejects_invalid_offset(
    monkeypatch: pytest.MonkeyPatch, offset: object
) -> None:
    """Typed result cursors do not coerce booleans or strings into offsets."""
    fixture = _tools(monkeypatch, current=_root(_CURRENT), target=_root(_TARGET))
    row = RDBEvent(
        session_id=_TARGET,
        kind=EventKind.CLIENT_TOOL_RESULT,
        payload={
            "call_id": "call-1",
            "name": "test_tool",
            "status": "completed",
            "output": "result",
        },
    )
    row.id = _EVENT
    fixture.messages.get_by_id.return_value = row
    with pytest.raises(FunctionToolError, match="Invalid history cursor"):
        await fixture.tools["read_session_tool_result"].handler(
            json.dumps(
                {
                    "session_id": _TARGET,
                    "event_id": _EVENT,
                    "cursor": _cursor(
                        {"session": _TARGET, "event": _EVENT, "offset": offset}
                    ),
                }
            )
        )


async def test_hosted_tool_page_and_selected_detail_exclude_input_and_native_data(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Hosted output lives in the call event, with only its text selectively shown."""
    fixture = _tools(monkeypatch, current=_root(_CURRENT), target=_root(_TARGET))
    tools, messages = fixture.tools, fixture.messages
    payload = ProviderToolCallPayload(
        call_id="hosted-1",
        name="web_search",
        status="completed",
        semantic=ProviderToolSemanticContent(
            input="private-hosted-input",
            output=[OutputTextPart(text="visible-hosted-result")],
            references=[],
        ),
        native_artifact=NativeArtifact(
            compat_key="litellm:responses:openai:example:1",
            adapter="litellm",
            native_format="responses",
            provider="openai",
            model="example",
            schema_version="1",
            item={"private": "hidden-native-value"},
        ),
    )
    row = RDBEvent(
        session_id=_TARGET,
        kind=EventKind.PROVIDER_TOOL_CALL,
        payload=payload.model_dump(mode="json"),
    )
    row.id = _EVENT
    messages.get_by_id.return_value = row
    event = Event(
        id=_EVENT,
        session_id=_TARGET,
        kind=EventKind.PROVIDER_TOOL_CALL,
        payload=payload,
        created_at=datetime.now(UTC),
    )
    messages.list_events_by_session_id_paginated.return_value = SimpleNamespace(
        items=[event], has_more=False, has_newer=False
    )

    page = await _json_result(tools["read_session_history"], {"session_id": _TARGET})
    assert page["events"][0]["tool"] == "web_search"
    assert page["events"][0]["has_text"] is True
    assert "visible-hosted-result" not in json.dumps(page)
    assert "private-hosted-input" not in json.dumps(page)

    result = await _json_result(
        tools["read_session_tool_result"], {"session_id": _TARGET, "event_id": _EVENT}
    )
    assert result["text"] == "visible-hosted-result"
    assert "hidden-native-value" not in json.dumps(result)
    assert "private-hosted-input" not in json.dumps(result)
