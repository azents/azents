"""Session todo Toolkit State tool tests."""

import json
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.tools import TurnContext
from azents.engine.events.engine_events import TodoStateChanged
from azents.engine.hooks.types import (
    CompactionSummaryHookContext,
    CompactionSummaryReplace,
)
from azents.engine.tooling.toolkit_state import ToolkitStateRunAuthorityLostError
from azents.engine.tools.todo import (
    TodoItem,
    TodoState,
    TodoStateStore,
    TodoToolkit,
    TodoUpdateItem,
    UpdateTodoInput,
    apply_todo_update,
    make_update_todo_tool,
    render_todo_snapshot,
)
from azents.repos.agent_execution import AgentRunOwnershipLostError


def _compaction_context(
    summary: str = "Existing summary",
) -> CompactionSummaryHookContext:
    """Create a compaction summary hook context for Todo tests."""
    return CompactionSummaryHookContext(
        workspace_id="workspace-1",
        agent_id="agent-1",
        session_id="session-1",
        run_id="run-1",
        compaction_id="compaction-1",
        reason="manual_command",
        covered_until_event_id="event-1",
        summary=summary,
        continuity_history="Recent context",
    )


def test_replace_sets_full_todo_list() -> None:
    """replace operation replaces entire todo list."""
    current = TodoState()
    updated = apply_todo_update(
        current,
        UpdateTodoInput(
            operation="replace",
            items=[
                TodoUpdateItem(
                    content="Write design",
                    status="completed",
                ),
                TodoUpdateItem(
                    content="Implement UI",
                    status="in_progress",
                ),
            ],
        ),
    )

    assert [item.content for item in updated.items] == [
        "Write design",
        "Implement UI",
    ]
    assert updated.items[1].status == "in_progress"


def test_clear_resets_todo_list() -> None:
    """clear operation clears todo list."""
    current = apply_todo_update(
        TodoState(),
        UpdateTodoInput(
            operation="replace",
            items=[
                TodoUpdateItem(content="A", status="pending"),
                TodoUpdateItem(content="B", status="in_progress"),
            ],
        ),
    )

    cleared = apply_todo_update(current, UpdateTodoInput(operation="clear"))

    assert cleared.items == []


def test_todo_snapshot_is_omitted_for_empty_state() -> None:
    """Empty Todo state does not render a compaction snapshot section."""
    assert render_todo_snapshot(TodoState()) is None


def test_todo_snapshot_renders_current_items() -> None:
    """Todo compaction snapshot renders readable current state."""
    snapshot = render_todo_snapshot(
        TodoState(
            items=[
                TodoItem(content="Review plan", status="completed"),
                TodoItem(content="Implement change", status="in_progress"),
            ]
        )
    )

    assert snapshot == (
        "## Todo Snapshot\n"
        "\n"
        "Session Todo state at compaction time:\n"
        "- [completed] Review plan\n"
        "- [in_progress] Implement change"
    )


async def test_todo_compaction_summary_hook_appends_snapshot() -> None:
    """Todo hook appends Todo snapshot to the generated summary."""
    store = AsyncMock()
    store.load.return_value = TodoState(
        items=[TodoItem(content="Current work", status="in_progress")]
    )
    toolkit = TodoToolkit(store=store, agent_id="agent-1", session_id="session-1")
    hook = toolkit.hooks().get("on_compaction_summary")
    assert hook is not None

    result = await hook(_compaction_context("Existing summary\n"))

    assert isinstance(result, CompactionSummaryReplace)
    assert result.summary == (
        "Existing summary\n"
        "\n"
        "## Todo Snapshot\n"
        "\n"
        "Session Todo state at compaction time:\n"
        "- [in_progress] Current work"
    )
    store.load.assert_awaited_once_with("agent-1", "session-1")


async def test_todo_compaction_summary_hook_omits_empty_state() -> None:
    """Todo hook leaves summary unchanged when Todo is empty."""
    store = AsyncMock()
    store.load.return_value = TodoState()
    toolkit = TodoToolkit(store=store, agent_id="agent-1", session_id="session-1")
    hook = toolkit.hooks().get("on_compaction_summary")
    assert hook is not None

    result = await hook(_compaction_context())

    assert result is None
    store.load.assert_awaited_once_with("agent-1", "session-1")


async def test_todo_toolkit_exposes_unprefixed_update_tool() -> None:
    """TodoToolkit exposes update_todo without prefix."""
    store = AsyncMock()
    store.load.return_value = TodoState(
        items=[
            TodoItem(
                content="Current work",
                status="in_progress",
            )
        ]
    )
    toolkit = TodoToolkit(store=store, agent_id="agent-1", session_id="session-1")

    context = TurnContext(
        user_id="user-1",
        workspace_id="workspace-1",
        model="model",
        run_id="run-1",
        owner_generation=1,
        session_id="session-1",
        publish_event=AsyncMock(),
    )
    state = await toolkit.update_context(context)

    assert [tool.spec.name for tool in state.tools] == ["update_todo"]
    assert "[in_progress] Current work" not in (
        await toolkit.get_static_prompt(context)
    )
    store.load.assert_not_awaited()


async def test_update_todo_returns_compact_acknowledgement() -> None:
    """update_todo stores and publishes state without echoing JSON."""
    store = AsyncMock()
    store.update.return_value = TodoState(
        items=[TodoItem(content="Current work", status="in_progress")]
    )
    publish_changed = AsyncMock()
    toolkit = TodoToolkit(store=store, agent_id="agent-1", session_id="session-1")
    state = await toolkit.update_context(
        TurnContext(
            user_id="user-1",
            workspace_id="workspace-1",
            model="model",
            run_id="run-1",
            owner_generation=7,
            session_id="session-1",
            publish_event=publish_changed,
        )
    )

    result = await state.tools[0].handler(
        json.dumps(
            {
                "operation": "replace",
                "items": [{"content": "Current work", "status": "in_progress"}],
            }
        )
    )

    assert result == "Done"
    _, _, update_kwargs = store.update.mock_calls[0]
    assert update_kwargs["run_id"] == "run-1"
    assert update_kwargs["owner_generation"] == 7
    publish_changed.assert_awaited_once()
    assert publish_changed.await_args is not None
    published = publish_changed.await_args.args[0]
    assert isinstance(published, TodoStateChanged)
    assert published.run_id == "run-1"


async def test_update_todo_projection_failure_preserves_committed_success() -> None:
    """Post-commit projection failure cannot make a durable update retryable."""
    store = AsyncMock()
    store.update.return_value = TodoState(
        items=[TodoItem(content="Current work", status="in_progress")]
    )
    publish_changed = AsyncMock(side_effect=RuntimeError("projection unavailable"))
    tool = make_update_todo_tool(
        store=store,
        agent_id="agent-1",
        session_id="session-1",
        run_id="run-1",
        owner_generation=7,
        publish_changed=publish_changed,
    )

    result = await tool.handler(
        json.dumps(
            {
                "operation": "replace",
                "items": [{"content": "Current work", "status": "in_progress"}],
            }
        )
    )

    assert result == "Done"
    store.update.assert_awaited_once()
    publish_changed.assert_awaited_once()


async def test_todo_store_rejects_stale_owner_generation_before_write() -> None:
    """A taken-over Run cannot commit Todo state under its old owner lease."""
    scope = AsyncMock()
    scope.__aenter__.return_value = cast(AsyncSession, object())
    session_manager = MagicMock(return_value=scope)
    run_repository = AsyncMock()
    session_repository = AsyncMock()
    session_repository.lock_by_id.return_value = SimpleNamespace(owner_generation=2)
    toolkit_state_repository = AsyncMock()
    toolkit_state_repository.get.return_value = None
    store = TodoStateStore(
        session_manager=cast(Any, session_manager),
        agent_run_repository=cast(Any, run_repository),
        agent_session_repository=cast(Any, session_repository),
        toolkit_state_repository=cast(Any, toolkit_state_repository),
    )

    with pytest.raises(ToolkitStateRunAuthorityLostError):
        await store.update(
            "agent-1",
            "session-1",
            run_id="run-a",
            owner_generation=1,
            mutator=lambda _: TodoState(),
        )

    run_repository.lock_active_owner.assert_not_awaited()


async def test_todo_store_rejects_inactive_run_before_write() -> None:
    """A quarantined Run cannot overwrite Todo state after Run B starts."""
    scope = AsyncMock()
    scope.__aenter__.return_value = cast(AsyncSession, object())
    session_manager = MagicMock(return_value=scope)
    run_repository = AsyncMock()
    run_repository.lock_active_owner.side_effect = AgentRunOwnershipLostError(
        run_id="run-a",
        session_id="session-1",
        expected_owner_generation=2,
        current_owner_generation=2,
        active_run_id="run-b",
    )
    session_repository = AsyncMock()
    session_repository.lock_by_id.return_value = SimpleNamespace(owner_generation=2)
    toolkit_state_repository = AsyncMock()
    toolkit_state_repository.get.return_value = None
    store = TodoStateStore(
        session_manager=cast(Any, session_manager),
        agent_run_repository=cast(Any, run_repository),
        agent_session_repository=cast(Any, session_repository),
        toolkit_state_repository=cast(Any, toolkit_state_repository),
    )

    with pytest.raises(ToolkitStateRunAuthorityLostError):
        await store.update(
            "agent-1",
            "session-1",
            run_id="run-a",
            owner_generation=2,
            mutator=lambda _: TodoState(),
        )

    run_repository.lock_active_owner.assert_awaited_once_with(
        scope.__aenter__.return_value,
        run_id="run-a",
        session_id="session-1",
        owner_generation=2,
    )
