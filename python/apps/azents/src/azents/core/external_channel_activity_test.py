"""Slack Activity Tracker presentation tests."""

import pytest

from azents.core.external_channel_activity import (
    ActivityTrackerTask,
    activity_tracker_payload,
    render_activity_tracker,
    render_persisted_activity_tracker,
)

_SESSION_URL = "https://azents.example/w/team/agents/agent-1/sessions/session-1"


def test_checking_tracker_always_contains_session_button() -> None:
    """A new work cycle is visible before any Todo exists."""
    presentation = render_activity_tracker(
        state="checking",
        tasks=(),
        session_url=_SESSION_URL,
    )

    assert presentation.text == "Agent is checking your message"
    assert presentation.blocks[-1] == {
        "type": "actions",
        "elements": [
            {
                "type": "button",
                "action_id": "open_azents_session",
                "text": {"type": "plain_text", "text": "Open Azents session"},
                "url": _SESSION_URL,
            }
        ],
    }


def test_working_tracker_renders_tasks_as_plain_text() -> None:
    """Task titles cannot inject Slack mrkdwn into operational presentation."""
    presentation = render_activity_tracker(
        state="working",
        tasks=(
            ActivityTrackerTask(
                title="Inspect <@U1> and *literal markup*",
                status="in_progress",
            ),
        ),
        session_url=_SESSION_URL,
    )

    assert presentation.text == (
        "Agent is working\n◐ Inspect <@U1> and *literal markup*"
    )
    assert presentation.blocks[2] == {
        "type": "section",
        "text": {
            "type": "plain_text",
            "text": "◐ Inspect <@U1> and *literal markup*",
        },
    }


def test_completed_tracker_removes_tasks_and_retains_link() -> None:
    """Normal completion updates rather than deletes the Tracker."""
    presentation = render_activity_tracker(
        state="completed",
        tasks=(ActivityTrackerTask(title="Old task", status="completed"),),
        session_url=_SESSION_URL,
    )
    payload = activity_tracker_payload(
        state="completed",
        tasks=(),
        session_url=_SESSION_URL,
    )

    assert presentation.text == "Answer complete"
    assert len(presentation.blocks) == 3
    assert all("Old task" not in str(block) for block in presentation.blocks)
    assert presentation.blocks[-1]["elements"][0]["url"] == _SESSION_URL  # type: ignore[index]
    assert payload == {
        "state": "completed",
        "tasks": [],
        "session_url": _SESSION_URL,
    }


def test_persisted_tracker_projection_is_validated_before_rendering() -> None:
    """Recovery uses the same validated presentation contract as live updates."""
    presentation = render_persisted_activity_tracker(
        {
            "state": "working",
            "tasks": [{"title": "Investigate", "status": "pending"}],
            "session_url": _SESSION_URL,
        }
    )

    assert presentation.text == "Agent is working\n○ Investigate"

    with pytest.raises(RuntimeError, match="task is invalid"):
        render_persisted_activity_tracker(
            {
                "state": "working",
                "tasks": [{"title": "Investigate", "status": "unexpected"}],
                "session_url": _SESSION_URL,
            }
        )
