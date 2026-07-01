"""Session goal Toolkit State tool tests."""

from collections.abc import Callable
from unittest.mock import AsyncMock

import pytest

from azents.core.tools import TurnContext
from azents.engine.hooks.types import (
    CompactionSummaryHookContext,
    CompactionSummaryReplace,
    SessionIdleHookContext,
)
from azents.engine.run.types import FunctionToolError
from azents.engine.tools.goal import (
    GoalState,
    GoalStatus,
    GoalToolkit,
    render_goal_prompt,
    render_goal_snapshot,
)


def _compaction_context(
    summary: str = "Existing summary",
) -> CompactionSummaryHookContext:
    """Create a compaction summary hook context for Goal tests."""
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


async def test_goal_toolkit_exposes_goal_tools() -> None:
    """GoalToolkit exposes goal tools without prefix."""
    store = AsyncMock()
    store.load.return_value = GoalState(objective="Ship goal", status="active")
    toolkit = GoalToolkit(store=store, agent_id="agent-1", session_id="session-1")

    context = TurnContext(
        user_id="user-1",
        workspace_id="workspace-1",
        model="model",
        run_id="run-1",
        session_id="session-1",
        publish_event=AsyncMock(),
    )
    state = await toolkit.update_context(context)

    assert [tool.spec.name for tool in state.tools] == [
        "get_goal",
        "create_goal",
        "update_goal",
    ]
    assert "Ship goal" not in (await toolkit.get_static_prompt(context))
    store.load.assert_not_awaited()


def test_goal_snapshot_renders_unfinished_goal() -> None:
    """Goal compaction snapshot renders unfinished Goal state."""
    snapshot = render_goal_snapshot(
        GoalState(
            objective="Finish stacked PRs",
            status="active",
            created_at="2026-07-01T00:00:00+00:00",
            updated_at="2026-07-01T01:00:00+00:00",
        )
    )

    assert snapshot == (
        "## Goal Snapshot\n"
        "\n"
        "Session Goal state at compaction time:\n"
        "- Objective: Finish stacked PRs\n"
        "- Status: active\n"
        "- Created at: 2026-07-01T00:00:00+00:00\n"
        "- Updated at: 2026-07-01T01:00:00+00:00"
    )


@pytest.mark.parametrize(
    "state",
    [
        GoalState(),
        GoalState(objective="Done", status="complete"),
    ],
)
def test_goal_snapshot_omits_empty_or_complete_goal(state: GoalState) -> None:
    """Empty and completed Goals do not render compaction snapshots."""
    assert render_goal_snapshot(state) is None


async def test_goal_compaction_summary_hook_appends_snapshot() -> None:
    """Goal hook appends unfinished Goal snapshot to the generated summary."""
    store = AsyncMock()
    store.load.return_value = GoalState(
        objective="Finish stacked PRs",
        status="active",
    )
    toolkit = GoalToolkit(store=store, agent_id="agent-1", session_id="session-1")
    hook = toolkit.hooks().get("on_compaction_summary")
    assert hook is not None

    result = await hook(_compaction_context("Existing summary\n"))

    assert isinstance(result, CompactionSummaryReplace)
    assert result.summary == (
        "Existing summary\n"
        "\n"
        "## Goal Snapshot\n"
        "\n"
        "Session Goal state at compaction time:\n"
        "- Objective: Finish stacked PRs\n"
        "- Status: active"
    )
    store.load.assert_awaited_once_with("agent-1", "session-1")


async def test_goal_compaction_summary_hook_omits_complete_goal() -> None:
    """Goal hook leaves summary unchanged when Goal is complete."""
    store = AsyncMock()
    store.load.return_value = GoalState(objective="Done", status="complete")
    toolkit = GoalToolkit(store=store, agent_id="agent-1", session_id="session-1")
    hook = toolkit.hooks().get("on_compaction_summary")
    assert hook is not None

    result = await hook(_compaction_context())

    assert result is None
    store.load.assert_awaited_once_with("agent-1", "session-1")


def test_goal_prompt_is_stable_across_state() -> None:
    """Current Goal state does not change the toolkit prompt."""
    assert render_goal_prompt(GoalState()) == render_goal_prompt(
        GoalState(objective="Ship goal", status="active")
    )
    assert render_goal_prompt(GoalState()) == render_goal_prompt(
        GoalState(objective="Done goal", status="complete")
    )


async def test_goal_idle_hook_returns_continuation_for_active_goal() -> None:
    """Active Goal returns session idle continuation."""
    store = AsyncMock()
    store.load.return_value = GoalState(objective="Finish the feature", status="active")
    toolkit = GoalToolkit(store=store, agent_id="agent-1", session_id="session-1")

    idle_hook = toolkit.hooks().get("on_session_idle")
    assert idle_hook is not None
    result = await idle_hook(
        SessionIdleHookContext(
            workspace_id="workspace-1",
            agent_id="agent-1",
            session_id="session-1",
            run_id="run-1",
            reason="completed",
        )
    )

    assert result is not None
    assert len(result.continuations) == 1
    assert result.continuations[0].content == ""
    assert result.continuations[0].metadata == {
        "source": "goal",
        "provider_slug": "goal",
        "last_run_id": "run-1",
        "goal_objective": "Finish the feature",
        "goal_status": "active",
        "goal_created_at": "",
        "goal_updated_at": "",
    }


@pytest.mark.parametrize("status", ["paused", "blocked", "complete"])
async def test_goal_idle_hook_skips_inactive_goal(status: GoalStatus) -> None:
    """Non-active Goal does not create continuation."""
    store = AsyncMock()
    store.load.return_value = GoalState(objective="Done", status=status)
    toolkit = GoalToolkit(store=store, agent_id="agent-1", session_id="session-1")

    idle_hook = toolkit.hooks().get("on_session_idle")
    assert idle_hook is not None
    result = await idle_hook(
        SessionIdleHookContext(
            workspace_id="workspace-1",
            agent_id="agent-1",
            session_id="session-1",
            run_id="run-1",
            reason="completed",
        )
    )

    assert result is None


async def test_create_goal_rejects_existing_unfinished_goal() -> None:
    """create_goal mutator fails when unfinished Goal exists."""
    store = AsyncMock()

    async def update(
        _agent_id: str,
        _session_id: str,
        mutator: Callable[[GoalState], GoalState],
    ) -> GoalState:
        return mutator(GoalState(objective="Existing", status="active"))

    store.update.side_effect = update
    toolkit = GoalToolkit(store=store, agent_id="agent-1", session_id="session-1")
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
    create_goal = state.tools[1]

    with pytest.raises(FunctionToolError):
        await create_goal.handler('{"objective":"New"}')


async def test_update_goal_complete_appends_briefing_event() -> None:
    """Complete Goal stores completion briefing event."""
    store = AsyncMock()

    async def update(
        _agent_id: str,
        _session_id: str,
        mutator: Callable[[GoalState], GoalState],
    ) -> GoalState:
        return mutator(
            GoalState(
                objective="Ship the feature",
                status="active",
                created_at="2026-06-15T12:00:00+00:00",
                updated_at="2026-06-15T12:00:00+00:00",
            )
        )

    store.update.side_effect = update
    toolkit = GoalToolkit(store=store, agent_id="agent-1", session_id="session-1")
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
    update_goal = state.tools[2]

    await update_goal.handler('{"status":"complete"}')

    store.append_briefing_event.assert_awaited_once()
    _, kwargs = store.append_briefing_event.await_args
    assert kwargs["objective"] == "Ship the feature"
    assert kwargs["created_at"] == "2026-06-15T12:00:00+00:00"
    assert kwargs["duration_seconds"] is not None
    assert kwargs["duration_seconds"] >= 0


async def test_update_goal_blocked_does_not_append_briefing_event() -> None:
    """Blocked Goal does not store completion briefing event."""
    store = AsyncMock()

    async def update(
        _agent_id: str,
        _session_id: str,
        mutator: Callable[[GoalState], GoalState],
    ) -> GoalState:
        return mutator(GoalState(objective="Blocked goal", status="active"))

    store.update.side_effect = update
    toolkit = GoalToolkit(store=store, agent_id="agent-1", session_id="session-1")
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
    update_goal = state.tools[2]

    await update_goal.handler('{"status":"blocked"}')

    store.append_briefing_event.assert_not_awaited()
