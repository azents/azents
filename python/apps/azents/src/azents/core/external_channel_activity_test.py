"""Slack Activity Tracker presentation tests."""

import pytest

from azents.core.external_channel_activity import (
    ActivityTrackerTask,
    activity_tracker_payload,
    render_activity_tracker,
    render_persisted_activity_tracker,
    render_session_link,
)

_SESSION_URL = "https://azents.example/w/team/agents/agent-1/sessions/session-1"


def test_checking_tracker_has_no_title_or_session_link() -> None:
    """A new work cycle shows its state with a native status indicator."""
    presentation = render_activity_tracker(
        state="checking",
        tasks=(),
    )

    assert presentation.text == "Agent is checking your message"
    assert presentation.blocks == [
        {
            "type": "task_card",
            "task_id": "activity-status",
            "title": "Agent is checking your message",
            "status": "in_progress",
        }
    ]
    assert "Agent activity" not in str(presentation.blocks)
    assert "Open Azents session" not in str(presentation.blocks)


def test_working_tracker_renders_todos_in_one_native_plan() -> None:
    """One plan owns the summary while every nested task has a valid status."""
    presentation = render_activity_tracker(
        state="working",
        tasks=(
            ActivityTrackerTask(
                id="inspect",
                title="Inspect <@U1> and *literal markup*",
                status="in_progress",
            ),
            ActivityTrackerTask(
                id="publish",
                title="Publish result",
                status="pending",
            ),
            ActivityTrackerTask(
                id="old-step",
                title="Old step",
                status="completed",
            ),
        ),
    )

    assert presentation.text == (
        "Agent is working\n"
        "In progress: Inspect <@U1> and *literal markup*\n"
        "Pending: Publish result\n"
        "Completed: Old step"
    )
    assert presentation.blocks == [
        {
            "type": "plan",
            "title": "Agent is working",
            "tasks": [
                {
                    "type": "task_card",
                    "task_id": "inspect",
                    "title": "Inspect <@U1> and *literal markup*",
                    "status": "in_progress",
                },
                {
                    "type": "task_card",
                    "task_id": "publish",
                    "title": "Publish result",
                    "status": "pending",
                },
                {
                    "type": "task_card",
                    "task_id": "old-step",
                    "title": "Old step",
                    "status": "complete",
                },
            ],
        },
    ]


def test_working_tracker_without_todos_keeps_summary_indicator() -> None:
    """The summary card owns progress until the Agent publishes a Todo."""
    presentation = render_activity_tracker(
        state="working",
        tasks=(),
    )

    assert presentation.blocks == [
        {
            "type": "task_card",
            "task_id": "activity-status",
            "title": "Agent is working",
            "status": "in_progress",
        }
    ]


def test_session_link_message_contains_only_button_block() -> None:
    """Binding activation publishes a separate one-time navigation message."""
    presentation = render_session_link(_SESSION_URL)

    assert presentation.text == "Open Azents session"
    assert presentation.blocks == [
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
                    "url": _SESSION_URL,
                }
            ],
        }
    ]


def test_persisted_tracker_projection_is_validated_before_rendering() -> None:
    """Recovery uses the same validated presentation contract as live updates."""
    presentation = render_persisted_activity_tracker(
        {
            "state": "working",
            "tasks": [
                {
                    "id": "investigate",
                    "title": "Investigate",
                    "status": "pending",
                }
            ],
        }
    )
    payload = activity_tracker_payload(
        state="working",
        tasks=(
            ActivityTrackerTask(
                id="investigate",
                title="Investigate",
                status="pending",
            ),
        ),
    )

    assert presentation.text == "Agent is working\nPending: Investigate"
    assert presentation.blocks == [
        {
            "type": "plan",
            "title": "Agent is working",
            "tasks": [
                {
                    "type": "task_card",
                    "task_id": "investigate",
                    "title": "Investigate",
                    "status": "pending",
                }
            ],
        },
    ]
    assert payload == {
        "state": "working",
        "tasks": [
            {
                "id": "investigate",
                "title": "Investigate",
                "status": "pending",
            }
        ],
    }

    with pytest.raises(RuntimeError, match="task is invalid"):
        render_persisted_activity_tracker(
            {
                "state": "working",
                "tasks": [
                    {
                        "id": "investigate",
                        "title": "Investigate",
                        "status": "unexpected",
                    }
                ],
            }
        )
