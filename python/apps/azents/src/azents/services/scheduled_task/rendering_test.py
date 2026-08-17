"""Scheduled Task runtime rendering tests."""

import datetime

from azents.core.enums import ScheduledTaskScheduleType
from azents.repos.scheduled_task_cycle.data import ScheduledTaskCycleState

from .rendering import (
    SCHEDULED_COMPACTION_HEADING,
    render_scheduled_task_compaction_snapshot,
    render_scheduled_task_cycle_guidance,
    render_scheduled_task_runtime_message,
    render_scheduled_task_schedule,
    replace_scheduled_compaction_snapshot,
)

_NOW = datetime.datetime(2026, 8, 16, 12, 0, tzinfo=datetime.UTC)


def _state(
    *,
    cycle_id: str = "c" * 32,
    binding_id: str | None = None,
    title: str = "Daily report",
    objective: str = "Prepare the report.",
    progress_title: str | None = None,
    ordered_tasks: list[str] | None = None,
) -> ScheduledTaskCycleState:
    """Build one started cycle fixture."""
    return ScheduledTaskCycleState(
        cycle_id=cycle_id,
        task_id="t" * 32,
        phase="started",
        workspace_id="w" * 32,
        agent_id="a" * 32,
        session_id="s" * 32,
        binding_id=binding_id,
        title=title,
        objective=objective,
        schedule_type=ScheduledTaskScheduleType.CRON,
        scheduled_at=None,
        cron_expression="0 9 * * *",
        timezone="America/New_York",
        scheduled_for=_NOW,
        current_run_id="r" * 32,
        started_at=_NOW,
        progress_title=progress_title,
        ordered_tasks=ordered_tasks or [],
    )


def test_cycle_guidance_distinguishes_session_and_channel_execution() -> None:
    """Dynamic guidance keeps provider publication scoped to bound cycles."""
    session_guidance = render_scheduled_task_cycle_guidance(_state())
    channel_guidance = render_scheduled_task_cycle_guidance(_state(binding_id="b" * 32))

    assert "no external provider publication is available" in session_guidance
    assert "`channel_action` only for interim progress" in channel_guidance
    assert "files set to null" in session_guidance
    assert "`submit_scheduled_task_result`" in session_guidance
    assert "exact same bound conversation" in channel_guidance
    assert "another Slack or Discord channel" in channel_guidance


def test_schedule_presentation_uses_human_first_and_canonical_secondary_text() -> None:
    """Common recurring schedules present readable timing before cron detail."""
    presentation = render_scheduled_task_schedule(
        schedule_type=ScheduledTaskScheduleType.CRON,
        scheduled_at=None,
        cron_expression="0 9 * * 1-5",
        timezone="America/New_York",
        scheduled_for=datetime.datetime(2026, 8, 17, 13, 0, tzinfo=datetime.UTC),
    )

    assert presentation.summary == "Every weekday at 9:00 AM EDT"
    assert presentation.canonical == "0 9 * * 1-5 (America/New_York)"
    assert presentation.occurrence == "August 17, 2026 at 9:00 AM EDT"
    assert presentation.occurrence_canonical == "2026-08-17T13:00:00Z"


def test_runtime_message_keeps_exact_prompt_after_structured_schedule() -> None:
    """Trigger content exposes readable metadata and leaves the prompt exact."""
    objective = "Prepare the report.\nKeep this second line exactly."

    message = render_scheduled_task_runtime_message(
        title="Daily report",
        objective=objective,
        schedule_type=ScheduledTaskScheduleType.ONCE,
        scheduled_at=_NOW,
        cron_expression=None,
        timezone=None,
        scheduled_for=_NOW,
    )

    assert "Schedule: August 16, 2026 at 12:00 PM UTC" in message
    assert "Schedule details: 2026-08-16T12:00:00Z" in message
    assert "Scheduled for details: 2026-08-16T12:00:00Z" in message
    assert message.endswith(f"Prompt:\n{objective}")


def test_compaction_snapshot_is_bounded_sanitized_and_identifier_free() -> None:
    """The canonical summary includes active work without internal identities."""
    state = _state(
        title="Daily\n## injected\x00 report",
        objective="Prepare\r\nall\tsections.",
        progress_title="Draft\nready",
        ordered_tasks=["Collect\nmetrics", "Write\tbriefing"],
    )

    snapshot = render_scheduled_task_compaction_snapshot([state])

    assert snapshot is not None
    assert "Title: Daily ## injected report" in snapshot
    assert "Objective: Prepare all sections." in snapshot
    assert "Progress title: Draft ready" in snapshot
    assert "1. Collect metrics" in snapshot
    assert "2. Write briefing" in snapshot
    assert state.cycle_id not in snapshot
    assert state.task_id not in snapshot
    assert state.workspace_id not in snapshot
    assert state.agent_id not in snapshot
    assert state.session_id not in snapshot
    assert state.current_run_id is not None
    assert state.current_run_id not in snapshot


def test_compaction_snapshot_replaces_stale_section_deterministically() -> None:
    """Repeated compaction replaces only the prior Scheduled snapshot."""
    old = (
        "Existing summary\n\n"
        f"{SCHEDULED_COMPACTION_HEADING}\n\nOld work\n\n"
        "## Other Snapshot\n\nKeep this."
    )
    new_snapshot = render_scheduled_task_compaction_snapshot([_state()])
    assert new_snapshot is not None

    replaced = replace_scheduled_compaction_snapshot(old, new_snapshot)
    repeated = replace_scheduled_compaction_snapshot(replaced, new_snapshot)

    assert "Old work" not in replaced
    assert "## Other Snapshot\n\nKeep this." in replaced
    assert replaced.count(SCHEDULED_COMPACTION_HEADING) == 1
    assert repeated == replaced


def test_compaction_snapshot_is_removed_when_no_cycle_remains() -> None:
    """Terminalized work disappears from the next canonical summary."""
    summary = f"Existing summary\n\n{SCHEDULED_COMPACTION_HEADING}\n\nCurrent work"

    assert replace_scheduled_compaction_snapshot(summary, None) == "Existing summary"
