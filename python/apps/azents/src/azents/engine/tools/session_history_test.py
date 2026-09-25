"""Memory-gated history tool authority and output checks."""

import json
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, AsyncIterator, cast
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


def _tools(
    monkeypatch: pytest.MonkeyPatch,
    *,
    current: AgentSession,
    target: AgentSession | None = None,
    root: AgentSession | None = None,
) -> tuple[dict[str, FunctionTool], AsyncMock, AsyncMock, AsyncMock]:
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
    return {tool.spec.name: tool for tool in tools}, history, messages, users


async def _json_result(
    tool: FunctionTool, arguments: dict[str, object]
) -> dict[str, Any]:
    raw = await tool.handler(json.dumps(arguments))
    assert isinstance(raw, str)
    decoded = json.loads(raw)
    assert isinstance(decoded, dict)
    return decoded


async def test_current_search_uses_concrete_child_but_root_team_authority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The current selector never substitutes the root Session's ID."""
    root = _root(_CURRENT)
    child = _child(_CHILD)
    tools, history, _, _ = _tools(monkeypatch, current=child, root=root)
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
    tools, _, messages, _ = _tools(
        monkeypatch,
        current=_root(_CURRENT),
        target=_root(_TARGET, mode=mode, owner=owner),
    )
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
    tools, _, messages, users = _tools(monkeypatch, current=own, target=other)
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
    tools, history, messages, _ = _tools(
        monkeypatch, current=_root(_CURRENT), target=archived
    )
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
    tools, _, messages, _ = _tools(
        monkeypatch, current=_root(_CURRENT), target=_root(_TARGET)
    )
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
    tools, _, messages, _ = _tools(
        monkeypatch, current=_root(_CURRENT), target=_root(_TARGET)
    )
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
    tools, _, messages, _ = _tools(
        monkeypatch, current=_root(_CURRENT), target=_root(_TARGET)
    )
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


async def test_hosted_tool_page_and_selected_detail_exclude_input_and_native_data(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Hosted output lives in the call event, with only its text selectively shown."""
    tools, _, messages, _ = _tools(
        monkeypatch, current=_root(_CURRENT), target=_root(_TARGET)
    )
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
