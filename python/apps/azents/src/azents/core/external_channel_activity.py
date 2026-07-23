"""Deterministic Slack Activity Tracker presentation."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

ActivityTrackerState = Literal["checking", "working"]
ActivityTrackerTaskStatus = Literal["pending", "in_progress", "completed"]
MAX_ACTIVITY_TRACKER_TASKS = 49


@dataclass(frozen=True)
class ActivityTrackerTask:
    """One ordered task rendered in the Activity Tracker."""

    id: str
    title: str
    status: ActivityTrackerTaskStatus


@dataclass(frozen=True)
class ActivityTrackerPresentation:
    """Accessible fallback text and Slack Block Kit payload."""

    text: str
    blocks: list[dict[str, object]]


def activity_tracker_payload(
    *,
    state: ActivityTrackerState,
    tasks: Sequence[ActivityTrackerTask],
) -> dict[str, object]:
    """Build the durable desired Activity Tracker projection."""
    return {
        "state": state,
        "tasks": [
            {
                "id": task.id,
                "title": task.title,
                "status": task.status,
            }
            for task in tasks
        ],
    }


def render_activity_tracker(
    *,
    state: ActivityTrackerState,
    tasks: Sequence[ActivityTrackerTask],
) -> ActivityTrackerPresentation:
    """Render one complete Activity Tracker state."""
    status_text = {
        "checking": "Agent is checking your message",
        "working": "Agent is working",
    }[state]
    task_lines = [_task_fallback_line(task) for task in tasks]
    fallback_lines = [status_text, *task_lines]
    status_block: dict[str, object] = {
        "type": "task_card",
        "task_id": "activity-status",
        "title": status_text,
        "status": "in_progress",
    }
    blocks = [status_block, *[_task_card(task) for task in tasks]]
    return ActivityTrackerPresentation(
        text="\n".join(fallback_lines),
        blocks=blocks,
    )


def render_session_link(session_url: str) -> ActivityTrackerPresentation:
    """Render the one-time Session link message for a new binding."""
    return ActivityTrackerPresentation(
        text="Open Azents session",
        blocks=[
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "action_id": "open_azents_session",
                        "text": {
                            "type": "plain_text",
                            "text": "Open Azents session",
                        },
                        "url": session_url,
                    }
                ],
            }
        ],
    )


def render_persisted_activity_tracker(
    payload: object,
) -> ActivityTrackerPresentation:
    """Render one validated durable Activity Tracker projection."""
    if not isinstance(payload, dict):
        raise RuntimeError("Activity Tracker desired state is unavailable.")
    state = payload.get("state")
    if state not in {"checking", "working"}:
        raise RuntimeError("Activity Tracker state is invalid.")
    raw_tasks = payload.get("tasks")
    if not isinstance(raw_tasks, list):
        raise RuntimeError("Activity Tracker tasks are invalid.")
    tasks: list[ActivityTrackerTask] = []
    for raw_task in raw_tasks:
        if not isinstance(raw_task, dict):
            raise RuntimeError("Activity Tracker task is invalid.")
        task_id = raw_task.get("id")
        title = raw_task.get("title")
        status = raw_task.get("status")
        if (
            not isinstance(task_id, str)
            or not task_id
            or not isinstance(title, str)
            or not title
            or status not in {"pending", "in_progress", "completed"}
        ):
            raise RuntimeError("Activity Tracker task is invalid.")
        tasks.append(ActivityTrackerTask(id=task_id, title=title, status=status))
    return render_activity_tracker(
        state=state,
        tasks=tasks,
    )


def _task_fallback_line(task: ActivityTrackerTask) -> str:
    """Render accessible task state without imitating native status chrome."""
    status_label = {
        "pending": "Pending",
        "in_progress": "In progress",
        "completed": "Completed",
    }[task.status]
    return f"{status_label}: {task.title}"


def _task_card(task: ActivityTrackerTask) -> dict[str, object]:
    """Render one native Slack task card with meaningful status chrome."""
    card: dict[str, object] = {
        "type": "task_card",
        "task_id": task.id,
        "title": task.title,
    }
    if task.status == "in_progress":
        card["status"] = "in_progress"
    elif task.status == "completed":
        card["status"] = "complete"
    return card
