"""Slack-native External Channel progress presentation tests."""

from azents.core.enums import ExternalChannelWorkTaskStatus
from azents.core.external_channel_progress import (
    ExternalChannelDesiredProgress,
    ExternalChannelWorkSource,
    ExternalChannelWorkTask,
    checking_progress,
)
from azents.core.slack_external_channel_progress import (
    SLACK_FALLBACK_TEXT_MAX_LENGTH,
    render_slack_persisted_progress,
    render_slack_progress,
    render_slack_session_presence,
)

_SESSION_URL = "https://azents.example/w/team/agents/agent-1/sessions/session-1"


def test_checking_tracker_has_revision_specific_block_identity() -> None:
    presentation = render_slack_progress(
        checking_progress(),
        work_id="work-1",
        desired_progress_revision=1,
    )

    assert presentation.text == "Agent is checking your message"
    assert presentation.blocks == [
        {
            "type": "task_card",
            "block_id": "work_work-1_1",
            "task_id": "activity-status",
            "title": "Agent is checking your message",
            "status": "in_progress",
        }
    ]


def test_working_tracker_renders_one_rich_native_plan() -> None:
    progress = ExternalChannelDesiredProgress(
        schema_version=2,
        state="working",
        title="Investigating error logs…",
        tasks=[
            ExternalChannelWorkTask(
                id="inspect",
                title="Inspect <@U1> and *literal markup*",
                status=ExternalChannelWorkTaskStatus.IN_PROGRESS,
                details="Comparing recent failures",
                output=None,
                sources=[
                    ExternalChannelWorkSource(
                        url="https://example.com/logs",
                        label="Error log dashboard",
                    )
                ],
            ),
            ExternalChannelWorkTask(
                id="summarize",
                title="Summarize the root cause",
                status=ExternalChannelWorkTaskStatus.FAILED,
                details=None,
                output="The trace was incomplete.",
                sources=[],
            ),
        ],
    )

    presentation = render_slack_progress(
        progress,
        work_id="work-1",
        desired_progress_revision=7,
    )

    assert presentation.text == (
        "Investigating error logs…\n"
        "In progress: Inspect &lt;＠U1&gt; and ＊literal markup＊\n"
        "Failed: Summarize the root cause"
    )
    assert presentation.blocks == [
        {
            "type": "plan",
            "block_id": "work_work-1_7",
            "title": "Investigating error logs…",
            "tasks": [
                {
                    "task_id": "inspect",
                    "title": "Inspect <@U1> and *literal markup*",
                    "status": "in_progress",
                    "details": {
                        "type": "rich_text",
                        "elements": [
                            {
                                "type": "rich_text_section",
                                "elements": [
                                    {
                                        "type": "text",
                                        "text": "Comparing recent failures",
                                    }
                                ],
                            }
                        ],
                    },
                    "sources": [
                        {
                            "type": "url",
                            "url": "https://example.com/logs",
                            "text": "Error log dashboard",
                        }
                    ],
                },
                {
                    "task_id": "summarize",
                    "title": "Summarize the root cause",
                    "status": "error",
                    "output": {
                        "type": "rich_text",
                        "elements": [
                            {
                                "type": "rich_text_section",
                                "elements": [
                                    {
                                        "type": "text",
                                        "text": "The trace was incomplete.",
                                    }
                                ],
                            }
                        ],
                    },
                },
            ],
        }
    ]
    assert "plan_id" not in str(presentation.blocks)
    assert '"type": "task_card"' not in str(presentation.blocks)


def test_working_tracker_bounds_long_fallback_text() -> None:
    progress = ExternalChannelDesiredProgress(
        schema_version=2,
        state="working",
        title="Reviewing the complete incident timeline…",
        tasks=[
            ExternalChannelWorkTask(
                id=f"task-{index}",
                title=f"Inspect evidence {index} " + "x" * 450,
                status=ExternalChannelWorkTaskStatus.PENDING,
                details=None,
                output=None,
                sources=[],
            )
            for index in range(49)
        ],
    )

    presentation = render_slack_progress(
        progress,
        work_id="work-1",
        desired_progress_revision=8,
    )

    assert len(presentation.text) == SLACK_FALLBACK_TEXT_MAX_LENGTH
    assert presentation.text.endswith("…")
    assert presentation.text.startswith("Reviewing the complete incident timeline…")


def test_persisted_progress_uses_the_same_renderer() -> None:
    payload = {
        "schema_version": 2,
        "state": "working",
        "title": "Reviewing evidence…",
        "tasks": [
            {
                "id": "review",
                "title": "Review evidence",
                "status": "pending",
                "details": None,
                "output": None,
                "sources": [],
            }
        ],
    }

    assert render_slack_persisted_progress(
        payload,
        work_id="work-2",
        desired_progress_revision=3,
    ) == render_slack_progress(
        ExternalChannelDesiredProgress.model_validate(payload),
        work_id="work-2",
        desired_progress_revision=3,
    )


def test_session_presence_contains_copy_and_navigation() -> None:
    presentation = render_slack_session_presence(
        agent_name="Research Agent",
        session_url=_SESSION_URL,
        state="joined",
    )

    assert presentation.text == "Research Agent joined this conversation."
    assert presentation.blocks == [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "*Research Agent* joined this conversation.",
            },
        },
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "action_id": "view_azents_session",
                    "text": {
                        "type": "plain_text",
                        "text": "View session",
                    },
                    "url": _SESSION_URL,
                }
            ],
        },
    ]

    left = render_slack_session_presence(
        agent_name="Research Agent",
        session_url=_SESSION_URL,
        state="left",
    )
    assert left.text == "Research Agent left this conversation."
    assert left.blocks[0]["text"] == {
        "type": "mrkdwn",
        "text": "*Research Agent* left this conversation.",
    }
