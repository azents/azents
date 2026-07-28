"""Bounded Discord text presentation helpers for ordered delivery parts."""

from dataclasses import dataclass
from typing import assert_never

from azents.core.enums import ExternalChannelWorkTaskStatus
from azents.core.external_channel_progress import (
    ExternalChannelDesiredProgress,
    ExternalChannelWorkTask,
)

_DISCORD_MESSAGE_CONTENT_LIMIT = 2_000
_DISCORD_AGENT_PREFIX_RESERVE = 200
DISCORD_DELIVERY_TEXT_LIMIT = (
    _DISCORD_MESSAGE_CONTENT_LIMIT - _DISCORD_AGENT_PREFIX_RESERVE
)


@dataclass(frozen=True)
class DiscordProgressPage:
    """One bounded accessible fallback and native Embed presentation."""

    text: str
    embeds: list[dict[str, object]]


@dataclass(frozen=True)
class DiscordProgressPresentation:
    """Ordered Discord-native pages for one canonical Channel Work snapshot."""

    pages: tuple[DiscordProgressPage, ...]


def split_discord_markdown(text: str) -> tuple[str, ...]:
    """Split text into bounded readable parts while balancing fenced code blocks."""
    if not text:
        return ("",)
    parts: list[str] = []
    remaining = text
    active_fence: str | None = None
    while remaining:
        prefix = "" if active_fence is None else f"{active_fence}\n"
        available = DISCORD_DELIVERY_TEXT_LIMIT - len(prefix)
        if available <= 0:
            raise ValueError("Discord code fence prefix exceeds the message limit.")
        if len(remaining) <= available:
            parts.append(f"{prefix}{remaining}")
            break
        split_at = _split_at(remaining, available)
        chunk = remaining[:split_at]
        remaining = remaining[split_at:]
        part_start_fence = active_fence
        active_fence = _active_fence_after(chunk, part_start_fence)
        suffix = "\n```" if active_fence is not None else ""
        if len(prefix) + len(chunk) + len(suffix) > DISCORD_DELIVERY_TEXT_LIMIT:
            split_at = _split_at(chunk, available - len(suffix))
            remaining = chunk[split_at:] + remaining
            chunk = chunk[:split_at]
            active_fence = _active_fence_after(chunk, part_start_fence)
            suffix = "\n```" if active_fence is not None else ""
        parts.append(f"{prefix}{chunk}{suffix}")
    return tuple(parts)


def render_discord_progress(
    progress: ExternalChannelDesiredProgress,
    *,
    work_id: str,
    desired_progress_revision: int,
) -> DiscordProgressPresentation:
    """Lower one canonical progress snapshot to stable bounded Discord pages."""
    del work_id, desired_progress_revision
    if progress.state == "checking":
        return DiscordProgressPresentation(
            pages=(
                DiscordProgressPage(
                    text="Agent is checking your message.",
                    embeds=[
                        {
                            "title": "Agent is checking your message",
                            "description": (
                                "The Agent is preparing the first response for this "
                                "conversation."
                            ),
                            "color": 0x5865F2,
                        }
                    ],
                ),
            )
        )
    if progress.title is None:
        raise AssertionError("Validated working progress must contain a title.")
    summary = _progress_summary(progress.tasks)
    overview = f"## {progress.title}\n{summary}"
    pages = [
        DiscordProgressPage(
            text=overview,
            embeds=[
                {
                    "title": _bounded_embed_title(progress.title),
                    "description": summary,
                    "color": 0x5865F2,
                }
            ],
        )
    ]
    for task in progress.tasks:
        task_text = _task_page(task)
        parts = split_discord_markdown(task_text)
        pages.extend(
            DiscordProgressPage(
                text=part,
                embeds=[
                    {
                        "title": _bounded_embed_title(
                            f"{_task_status_label(task.status)} — {task.title}"
                            + (
                                f" ({ordinal + 1}/{len(parts)})"
                                if len(parts) > 1
                                else ""
                            )
                        ),
                        "description": part,
                        "color": _task_status_color(task.status),
                    }
                ],
            )
            for ordinal, part in enumerate(parts)
        )
    return DiscordProgressPresentation(pages=tuple(pages))


def render_discord_persisted_progress(
    payload: object,
    *,
    work_id: str,
    desired_progress_revision: int,
) -> DiscordProgressPresentation:
    """Validate and render one durable canonical Discord progress snapshot."""
    return render_discord_progress(
        ExternalChannelDesiredProgress.model_validate(payload),
        work_id=work_id,
        desired_progress_revision=desired_progress_revision,
    )


def _split_at(value: str, maximum: int) -> int:
    """Prefer a newline or whitespace boundary without emitting an empty part."""
    if maximum <= 0:
        raise ValueError("Discord split maximum must be positive.")
    if len(value) <= maximum:
        return len(value)
    for separator in ("\n", " "):
        index = value.rfind(separator, 1, maximum + 1)
        if index > 0:
            return index + (1 if separator == "\n" else 0)
    return maximum


def _active_fence_after(value: str, active_fence: str | None) -> str | None:
    """Return the active triple-backtick opener after one Markdown fragment."""
    current = active_fence
    for line in value.splitlines():
        stripped = line.lstrip()
        if not stripped.startswith("```"):
            continue
        if current is None:
            current = stripped
        else:
            current = None
    return current


def _progress_summary(tasks: list[ExternalChannelWorkTask]) -> str:
    """Render a short, literal summary for the durable overview page."""
    counts = {
        ExternalChannelWorkTaskStatus.PENDING: 0,
        ExternalChannelWorkTaskStatus.IN_PROGRESS: 0,
        ExternalChannelWorkTaskStatus.COMPLETED: 0,
        ExternalChannelWorkTaskStatus.FAILED: 0,
    }
    for task in tasks:
        counts[task.status] += 1
    return (
        f"{len(tasks)} task(s) · "
        f"{counts[ExternalChannelWorkTaskStatus.IN_PROGRESS]} in progress · "
        f"{counts[ExternalChannelWorkTaskStatus.PENDING]} pending · "
        f"{counts[ExternalChannelWorkTaskStatus.COMPLETED]} completed · "
        f"{counts[ExternalChannelWorkTaskStatus.FAILED]} failed"
    )


def _task_page(task: ExternalChannelWorkTask) -> str:
    """Lower one canonical task without inventing provider-only state."""
    lines = [f"### {_task_status_label(task.status)} — {task.title}"]
    if task.details is not None:
        lines.extend(("**Details**", task.details))
    if task.output is not None:
        lines.extend(("**Output**", task.output))
    if task.sources:
        lines.append("**Sources**")
        lines.extend(f"- [{source.label}]({source.url})" for source in task.sources)
    return "\n".join(lines)


def _task_status_label(status: ExternalChannelWorkTaskStatus) -> str:
    match status:
        case ExternalChannelWorkTaskStatus.PENDING:
            return "Pending"
        case ExternalChannelWorkTaskStatus.IN_PROGRESS:
            return "In progress"
        case ExternalChannelWorkTaskStatus.COMPLETED:
            return "Completed"
        case ExternalChannelWorkTaskStatus.FAILED:
            return "Failed"
        case _ as unreachable:
            assert_never(unreachable)


def _task_status_color(status: ExternalChannelWorkTaskStatus) -> int:
    """Use a stable visual status without retaining provider-specific work state."""
    match status:
        case ExternalChannelWorkTaskStatus.PENDING:
            return 0x99AAB5
        case ExternalChannelWorkTaskStatus.IN_PROGRESS:
            return 0x5865F2
        case ExternalChannelWorkTaskStatus.COMPLETED:
            return 0x57F287
        case ExternalChannelWorkTaskStatus.FAILED:
            return 0xED4245
        case _ as unreachable:
            assert_never(unreachable)


def _bounded_embed_title(value: str) -> str:
    """Keep each generated title inside Discord's bounded Embed title field."""
    maximum = 256
    return value if len(value) <= maximum else f"{value[: maximum - 1]}…"
