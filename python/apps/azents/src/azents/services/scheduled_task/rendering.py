"""Provider-neutral Scheduled Task runtime message rendering."""

import datetime
import re

from azents.core.enums import ScheduledTaskScheduleType
from azents.repos.scheduled_task.schedule import (
    CanonicalSchedule,
    canonical_schedule_text,
)
from azents.repos.scheduled_task_cycle.data import ScheduledTaskCycleState

SCHEDULED_COMPACTION_HEADING = "## Scheduled Task Work Snapshot"
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_WHITESPACE = re.compile(r"\s+")
_TITLE_LIMIT = 200
_OBJECTIVE_LIMIT = 4_000
_PROGRESS_TITLE_LIMIT = 500
_TASK_LIMIT = 100
_TASK_TEXT_LIMIT = 1_000


def render_scheduled_task_runtime_message(
    *,
    title: str,
    objective: str,
    schedule_type: ScheduledTaskScheduleType,
    scheduled_at: datetime.datetime | None,
    cron_expression: str | None,
    timezone: str | None,
    scheduled_for: datetime.datetime,
) -> str:
    """Render complete canonical guidance for one Scheduled occurrence."""
    schedule = CanonicalSchedule(
        schedule_type=schedule_type,
        scheduled_at=scheduled_at,
        cron_expression=cron_expression,
        timezone=timezone,
        next_eligible_at=scheduled_for,
    )
    return (
        "Scheduled Task work is due.\n"
        f"Title: {title}\n"
        f"Objective: {objective}\n"
        f"Schedule: {canonical_schedule_text(schedule)}\n"
        f"Scheduled for: {_utc_text(scheduled_for)}\n"
        "Continue autonomously across Agent runs until the objective is complete. "
        "If required information, authority, user choice, or another prerequisite "
        "is unavailable after reasonable attempts, submit a failed result explaining "
        "what is missing. Submit a finished or failed Scheduled Task result explicitly."
    )


def render_scheduled_task_cycle_guidance(state: ScheduledTaskCycleState) -> str:
    """Render active-cycle-only dynamic execution guidance."""
    channel_guidance = (
        "Use `channel_action` only for interim progress and publication. "
        "Only `submit_scheduled_task_result` can finish this Scheduled Task cycle."
        if state.binding_id is not None
        else "This cycle is Session-only; no external provider publication is required."
    )
    runtime_message = render_scheduled_task_runtime_message(
        title=state.title,
        objective=state.objective,
        schedule_type=state.schedule_type,
        scheduled_at=state.scheduled_at,
        cron_expression=state.cron_expression,
        timezone=state.timezone,
        scheduled_for=state.scheduled_for,
    )
    return (
        "### Active Scheduled Task Work Cycle\n\n"
        f"{runtime_message}\n"
        "Ending this AgentRun does not finish the work cycle. Continue autonomously "
        "through idle continuations until the objective is terminal. "
        "Use `submit_scheduled_task_result` with `finished` only after achieving the "
        "objective, or with `failed` after reasonable attempts when required "
        "information, authority, a user choice, or another prerequisite remains "
        f"unavailable. {channel_guidance}"
    )


def render_scheduled_task_compaction_snapshot(
    states: list[ScheduledTaskCycleState],
) -> str | None:
    """Render bounded provider-neutral active work for canonical compaction."""
    if not states:
        return None
    lines = [
        SCHEDULED_COMPACTION_HEADING,
        "",
        "Current started Scheduled Task cycles at compaction time:",
    ]
    for index, state in enumerate(states, start=1):
        schedule = canonical_schedule_text(
            CanonicalSchedule(
                schedule_type=state.schedule_type,
                scheduled_at=state.scheduled_at,
                cron_expression=state.cron_expression,
                timezone=state.timezone,
                next_eligible_at=state.scheduled_for,
            )
        )
        lines.extend(
            [
                "",
                f"### Cycle {index}",
                f"- Title: {_bounded(state.title, _TITLE_LIMIT)}",
                f"- Objective: {_bounded(state.objective, _OBJECTIVE_LIMIT)}",
                f"- Schedule: {schedule}",
                f"- Scheduled for: {_utc_text(state.scheduled_for)}",
            ]
        )
        if state.progress_title:
            progress_title = _bounded(
                state.progress_title,
                _PROGRESS_TITLE_LIMIT,
            )
            lines.append(f"- Progress title: {progress_title}")
        if state.ordered_tasks:
            lines.append("- Ordered tasks:")
            lines.extend(
                f"  {task_index}. {_bounded(task, _TASK_TEXT_LIMIT)}"
                for task_index, task in enumerate(
                    state.ordered_tasks[:_TASK_LIMIT],
                    start=1,
                )
            )
        lines.append(
            "- Continue autonomously until terminal. Use "
            "`submit_scheduled_task_result` with `finished` or `failed`; ending one "
            "AgentRun does not finish the cycle."
        )
    return "\n".join(lines)


def replace_scheduled_compaction_snapshot(
    summary: str,
    snapshot: str | None,
) -> str:
    """Replace only the Scheduled snapshot section in an evolving summary."""
    marker = f"\n\n{SCHEDULED_COMPACTION_HEADING}"
    start = summary.find(marker)
    if start == -1 and summary.startswith(SCHEDULED_COMPACTION_HEADING):
        start = 0
    base = summary
    if start != -1:
        section_start = start + (2 if start > 0 else 0)
        next_heading = summary.find("\n\n## ", section_start + 3)
        if next_heading == -1:
            base = summary[:start]
        else:
            base = summary[:start] + summary[next_heading:]
    base = base.rstrip()
    if snapshot is None:
        return base
    return f"{base}\n\n{snapshot}" if base else snapshot


def _bounded(value: str, limit: int) -> str:
    """Normalize control characters and bound one model-visible value."""
    normalized = _WHITESPACE.sub(" ", _CONTROL_CHARS.sub(" ", value)).strip()
    if len(normalized) <= limit:
        return normalized
    return f"{normalized[: limit - 3].rstrip()}..."


def _utc_text(value: datetime.datetime) -> str:
    """Render one timezone-aware instant as canonical UTC RFC3339 text."""
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Scheduled Task runtime instant must be timezone-aware.")
    return value.astimezone(datetime.UTC).isoformat().replace("+00:00", "Z")
