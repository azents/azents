"""Deterministic Slack Activity Tracker presentation."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

ActivityTrackerState = Literal["checking", "working", "completed"]
ActivityTrackerTaskStatus = Literal["pending", "in_progress", "completed"]


@dataclass(frozen=True)
class ActivityTrackerTask:
    """One ordered task rendered in the Activity Tracker."""

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
    session_url: str,
) -> dict[str, object]:
    """Build the durable desired Activity Tracker projection."""
    return {
        "state": state,
        "tasks": [
            {
                "title": task.title,
                "status": task.status,
            }
            for task in tasks
        ],
        "session_url": session_url,
    }


def render_activity_tracker(
    *,
    state: ActivityTrackerState,
    tasks: Sequence[ActivityTrackerTask],
    session_url: str,
) -> ActivityTrackerPresentation:
    """Render one complete Activity Tracker state."""
    status_text = {
        "checking": "Agent is checking your message",
        "working": "Agent is working",
        "completed": "Answer complete",
    }[state]
    task_lines = [
        f"{_task_marker(task.status)} {task.title}"
        for task in tasks
        if state != "completed"
    ]
    fallback_lines = [status_text, *task_lines]
    blocks: list[dict[str, object]] = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": "Agent activity"},
        },
        {
            "type": "section",
            "text": {"type": "plain_text", "text": status_text},
        },
    ]
    if task_lines:
        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "plain_text",
                    "text": "\n".join(task_lines),
                },
            }
        )
    blocks.append(
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "action_id": "open_azents_session",
                    "text": {"type": "plain_text", "text": "Open Azents session"},
                    "url": session_url,
                }
            ],
        }
    )
    return ActivityTrackerPresentation(
        text="\n".join(fallback_lines),
        blocks=blocks,
    )


def render_persisted_activity_tracker(
    payload: object,
) -> ActivityTrackerPresentation:
    """Render one validated durable Activity Tracker projection."""
    if not isinstance(payload, dict):
        raise RuntimeError("Activity Tracker desired state is unavailable.")
    state = payload.get("state")
    if state not in {"checking", "working", "completed"}:
        raise RuntimeError("Activity Tracker state is invalid.")
    session_url = payload.get("session_url")
    if not isinstance(session_url, str) or not session_url:
        raise RuntimeError("Activity Tracker Session URL is invalid.")
    raw_tasks = payload.get("tasks")
    if not isinstance(raw_tasks, list):
        raise RuntimeError("Activity Tracker tasks are invalid.")
    tasks: list[ActivityTrackerTask] = []
    for raw_task in raw_tasks:
        if not isinstance(raw_task, dict):
            raise RuntimeError("Activity Tracker task is invalid.")
        title = raw_task.get("title")
        status = raw_task.get("status")
        if (
            not isinstance(title, str)
            or not title
            or status not in {"pending", "in_progress", "completed"}
        ):
            raise RuntimeError("Activity Tracker task is invalid.")
        tasks.append(ActivityTrackerTask(title=title, status=status))
    return render_activity_tracker(
        state=state,
        tasks=tasks,
        session_url=session_url,
    )


def _task_marker(status: ActivityTrackerTaskStatus) -> str:
    """Return the plain-text marker for one task state."""
    return {
        "pending": "○",
        "in_progress": "◐",
        "completed": "●",
    }[status]
