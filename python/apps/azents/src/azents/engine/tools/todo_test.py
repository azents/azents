"""Session todo Toolkit State tool tests."""

import json
from unittest.mock import AsyncMock

from azents.core.tools import TurnContext
from azents.engine.tools.todo import (
    TodoItem,
    TodoState,
    TodoToolkit,
    TodoUpdateItem,
    UpdateTodoInput,
    apply_todo_update,
    render_todo_prompt,
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

    state = await toolkit.update_context(
        TurnContext(
            user_id="user-1",
            workspace_id="workspace-1",
            model="model",
            run_id="run-1",
            session_id="session-1",
            publish_event=AsyncMock(),
        )
    )

    assert [tool.spec.name for tool in state.tools] == ["update_todo"]
    assert "[in_progress] Current work" not in state.prompt
    store.load.assert_not_awaited()


def test_todo_prompt_is_stable_across_state() -> None:
    """Current Todo state does not change the toolkit prompt."""
    assert render_todo_prompt(TodoState()) == render_todo_prompt(
        TodoState(
            items=[
                TodoItem(
                    content="Current work",
                    status="in_progress",
                )
            ]
        )
    )


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
    publish_changed.assert_awaited_once()
