"""Slack-native presentation of provider-neutral Channel Work progress."""

from dataclasses import dataclass
from typing import assert_never

from azents.core.enums import ExternalChannelWorkTaskStatus
from azents.core.external_channel_progress import (
    ExternalChannelDesiredProgress,
    ExternalChannelWorkTask,
)

_CHECKING_TITLE = "Agent is checking your message"
SLACK_FALLBACK_TEXT_MAX_LENGTH = 4_000
_FALLBACK_LITERAL_TRANSLATION = str.maketrans(
    {
        "@": "＠",
        "#": "＃",
        "*": "＊",
        "_": "＿",
        "~": "～",
        "`": "｀",
    }
)


@dataclass(frozen=True)
class SlackProgressPresentation:
    """Accessible fallback text and Slack Block Kit payload."""

    text: str
    blocks: list[dict[str, object]]


def render_slack_progress(
    progress: ExternalChannelDesiredProgress,
    *,
    work_id: str,
    desired_progress_revision: int,
) -> SlackProgressPresentation:
    """Render one complete desired snapshot for a Slack Tracker message."""
    block_id = _block_id(work_id, desired_progress_revision)
    if progress.state == "checking":
        return SlackProgressPresentation(
            text=_CHECKING_TITLE,
            blocks=[
                {
                    "type": "task_card",
                    "block_id": block_id,
                    "task_id": "activity-status",
                    "title": _CHECKING_TITLE,
                    "status": "in_progress",
                }
            ],
        )
    if progress.title is None:
        raise AssertionError("Validated working progress must contain a title.")
    return SlackProgressPresentation(
        text=_bounded_fallback_text(
            [
                _fallback_literal(progress.title),
                *[_task_fallback_line(task) for task in progress.tasks],
            ]
        ),
        blocks=[
            {
                "type": "plan",
                "block_id": block_id,
                "title": progress.title,
                "tasks": [_plan_task(task) for task in progress.tasks],
            }
        ],
    )


def render_slack_persisted_progress(
    payload: object,
    *,
    work_id: str,
    desired_progress_revision: int,
) -> SlackProgressPresentation:
    """Validate and render one durable canonical desired snapshot."""
    progress = ExternalChannelDesiredProgress.model_validate(payload)
    return render_slack_progress(
        progress,
        work_id=work_id,
        desired_progress_revision=desired_progress_revision,
    )


def render_slack_session_link(session_url: str) -> SlackProgressPresentation:
    """Render the one-time Session link message for a new binding."""
    return SlackProgressPresentation(
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


def _block_id(work_id: str, desired_progress_revision: int) -> str:
    """Derive provider-only message-iteration identity."""
    return f"work_{work_id}_{desired_progress_revision}"


def _task_fallback_line(task: ExternalChannelWorkTask) -> str:
    """Render an accessible task-state summary."""
    match task.status:
        case ExternalChannelWorkTaskStatus.PENDING:
            status_label = "Pending"
        case ExternalChannelWorkTaskStatus.IN_PROGRESS:
            status_label = "In progress"
        case ExternalChannelWorkTaskStatus.COMPLETED:
            status_label = "Completed"
        case ExternalChannelWorkTaskStatus.FAILED:
            status_label = "Failed"
        case _ as unreachable:
            assert_never(unreachable)
    return f"{status_label}: {_fallback_literal(task.title)}"


def _fallback_literal(value: str) -> str:
    """Prevent provider markup in accessible fallback text."""
    escaped = value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return escaped.translate(_FALLBACK_LITERAL_TRANSLATION)


def _bounded_fallback_text(lines: list[str]) -> str:
    """Keep Slack fallback text within its provider-supported limit."""
    text = "\n".join(lines)
    if len(text) <= SLACK_FALLBACK_TEXT_MAX_LENGTH:
        return text
    return f"{text[: SLACK_FALLBACK_TEXT_MAX_LENGTH - 1].rstrip()}…"


def _plan_task(task: ExternalChannelWorkTask) -> dict[str, object]:
    """Lower one canonical task to Slack's nested Plan task shape."""
    result: dict[str, object] = {
        "task_id": task.id,
        "title": task.title,
        "status": _slack_task_status(task.status),
    }
    if task.details is not None:
        result["details"] = _literal_rich_text(task.details)
    if task.output is not None:
        result["output"] = _literal_rich_text(task.output)
    if task.sources:
        result["sources"] = [
            {
                "type": "url",
                "url": source.url,
                "text": source.label,
            }
            for source in task.sources
        ]
    return result


def _slack_task_status(status: ExternalChannelWorkTaskStatus) -> str:
    match status:
        case ExternalChannelWorkTaskStatus.PENDING:
            return "pending"
        case ExternalChannelWorkTaskStatus.IN_PROGRESS:
            return "in_progress"
        case ExternalChannelWorkTaskStatus.COMPLETED:
            return "complete"
        case ExternalChannelWorkTaskStatus.FAILED:
            return "error"
        case _ as unreachable:
            assert_never(unreachable)


def _literal_rich_text(text: str) -> dict[str, object]:
    """Place untrusted task prose in literal Slack rich-text elements."""
    return {
        "type": "rich_text",
        "elements": [
            {
                "type": "rich_text_section",
                "elements": [{"type": "text", "text": text}],
            }
        ],
    }
