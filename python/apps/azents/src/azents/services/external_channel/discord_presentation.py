"""Bounded Discord text presentation helpers for ordered delivery parts."""

from dataclasses import dataclass
from typing import assert_never

from azents.core.enums import ExternalChannelWorkTaskStatus
from azents.core.external_channel_progress import (
    ExternalChannelDesiredProgress,
    ExternalChannelWorkTask,
)
from azents.core.external_channel_session_presence import (
    ExternalChannelSessionPresenceState,
)

_DISCORD_MESSAGE_CONTENT_LIMIT = 2_000
_DISCORD_AGENT_PREFIX_RESERVE = 200
DISCORD_DELIVERY_TEXT_LIMIT = (
    _DISCORD_MESSAGE_CONTENT_LIMIT - _DISCORD_AGENT_PREFIX_RESERVE
)
_PROGRESS_TITLE_MAX_LENGTH = 160
_TASK_TITLE_MAX_LENGTH = 120
_TASK_CONTEXT_MAX_LENGTH = 240
_TRACKER_COLOR = 0x5865F2
_SESSION_JOINED_COLOR = 0x57F287
_SESSION_LEFT_COLOR = 0x99AAB5


@dataclass(frozen=True)
class DiscordProgressPage:
    """One bounded Discord progress-message presentation."""

    text: str
    embeds: list[dict[str, object]]


@dataclass(frozen=True)
class DiscordProgressPresentation:
    """Ordered Discord-native pages for one canonical Channel Work snapshot."""

    pages: tuple[DiscordProgressPage, ...]


@dataclass(frozen=True)
class DiscordSessionPresencePresentation:
    """One Discord-native Session binding presence control."""

    text: str
    embeds: list[dict[str, object]]
    components: list[dict[str, object]]


def render_discord_session_presence(
    *,
    agent_name: str,
    session_url: str,
    state: ExternalChannelSessionPresenceState,
) -> DiscordSessionPresencePresentation:
    """Render one Session binding presence Embed with navigation."""
    escaped_name = (
        agent_name.replace("\\", "\\\\")
        .replace("*", "\\*")
        .replace("_", "\\_")
        .replace("~", "\\~")
        .replace("`", "\\`")
    )
    verb = "joined" if state == "joined" else "left"
    description = f"**{escaped_name}** {verb} this conversation."
    return DiscordSessionPresencePresentation(
        text="",
        embeds=[
            {
                "description": description,
                "color": (
                    _SESSION_JOINED_COLOR if state == "joined" else _SESSION_LEFT_COLOR
                ),
            }
        ],
        components=[
            {
                "type": 1,
                "components": [
                    {
                        "type": 2,
                        "style": 5,
                        "label": "View session",
                        "url": session_url,
                    }
                ],
            }
        ],
    )


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
    """Lower one canonical progress snapshot to one compact Discord Tracker."""
    del work_id, desired_progress_revision
    if progress.state == "checking":
        return DiscordProgressPresentation(
            pages=(
                DiscordProgressPage(
                    text="",
                    embeds=_tracker_embeds(
                        title="Channel Work",
                        description="◉ Agent is checking your message",
                    ),
                ),
            )
        )
    if progress.title is None:
        raise AssertionError("Validated working progress must contain a title.")
    title = _truncate(_single_line(progress.title), _PROGRESS_TITLE_MAX_LENGTH)
    return DiscordProgressPresentation(
        pages=(
            DiscordProgressPage(
                text="",
                embeds=_tracker_embeds(
                    title=title,
                    description=_compact_progress_description(progress),
                ),
            ),
        )
    )


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
    """Render compact completion counts for one Tracker header."""
    completed = sum(
        task.status is ExternalChannelWorkTaskStatus.COMPLETED for task in tasks
    )
    failed = sum(task.status is ExternalChannelWorkTaskStatus.FAILED for task in tasks)
    summary = f"{completed}/{len(tasks)} complete"
    return f"{summary} · {failed} failed" if failed else summary


def _tracker_embeds(
    *,
    title: str,
    description: str,
) -> list[dict[str, object]]:
    """Render one bounded Discord-native Channel Work Embed."""
    return [
        {
            "title": title,
            "description": description,
            "color": _TRACKER_COLOR,
        }
    ]


def _compact_progress_description(progress: ExternalChannelDesiredProgress) -> str:
    """Render every task in one bounded Embed description."""
    if progress.title is None:
        raise AssertionError("Validated working progress must contain a title.")
    summary = f"**{_progress_summary(progress.tasks)}**"
    task_lines = _bounded_task_title_lines(
        progress.tasks,
        maximum=DISCORD_DELIVERY_TEXT_LIMIT - len(summary) - 1,
    )
    extras: list[list[str]] = [[] for _ in progress.tasks]
    base = "\n".join((summary, *task_lines))
    remaining = DISCORD_DELIVERY_TEXT_LIMIT - len(base)

    task_ordinals = sorted(
        range(len(progress.tasks)),
        key=lambda ordinal: (
            _task_context_priority(progress.tasks[ordinal].status),
            ordinal,
        ),
    )
    for ordinal in task_ordinals:
        context = _task_context(progress.tasks[ordinal])
        if context is None:
            continue
        prefix = "  ↳ "
        maximum = min(
            _TASK_CONTEXT_MAX_LENGTH,
            remaining - len(prefix) - 1,
        )
        if maximum < 8:
            break
        line = f"{prefix}{_truncate(_single_line(context), maximum)}"
        extras[ordinal].append(line)
        remaining -= len(line) + 1

    for ordinal in task_ordinals:
        if remaining <= 0:
            break
        source_line = _bounded_source_line(
            progress.tasks[ordinal],
            maximum=remaining - 1,
        )
        if source_line is None:
            continue
        extras[ordinal].append(source_line)
        remaining -= len(source_line) + 1

    lines = [summary]
    for ordinal, task_line in enumerate(task_lines):
        lines.append(task_line)
        lines.extend(extras[ordinal])
    rendered = "\n".join(lines)
    if len(rendered) > DISCORD_DELIVERY_TEXT_LIMIT:
        raise AssertionError(
            "Discord Tracker Embed description exceeded its bounded limit."
        )
    return rendered


def _bounded_task_title_lines(
    tasks: list[ExternalChannelWorkTask],
    *,
    maximum: int,
) -> list[str]:
    """Keep every ordered task visible while fitting the Tracker message."""
    markers = [_task_status_marker(task.status) for task in tasks]
    titles = [
        _truncate(_single_line(task.title), _TASK_TITLE_MAX_LENGTH) for task in tasks
    ]
    lines = [f"{marker} {title}" for marker, title in zip(markers, titles, strict=True)]
    if len("\n".join(lines)) <= maximum:
        return lines

    fixed_length = sum(len(marker) + 1 for marker in markers) + len(tasks) - 1
    title_budget = maximum - fixed_length
    if title_budget < len(tasks):
        raise AssertionError("Discord Tracker cannot retain every task title.")
    remaining_budget = title_budget
    bounded_titles: list[str] = []
    for ordinal, title in enumerate(titles):
        remaining_tasks = len(titles) - ordinal
        item_budget = max(1, remaining_budget // remaining_tasks)
        bounded = _truncate(title, item_budget)
        bounded_titles.append(bounded)
        remaining_budget -= len(bounded)
    return [
        f"{marker} {title}"
        for marker, title in zip(markers, bounded_titles, strict=True)
    ]


def _task_status_marker(status: ExternalChannelWorkTaskStatus) -> str:
    match status:
        case ExternalChannelWorkTaskStatus.PENDING:
            return "○"
        case ExternalChannelWorkTaskStatus.IN_PROGRESS:
            return "◉"
        case ExternalChannelWorkTaskStatus.COMPLETED:
            return "✓"
        case ExternalChannelWorkTaskStatus.FAILED:
            return "✕"
        case _ as unreachable:
            assert_never(unreachable)


def _task_context_priority(status: ExternalChannelWorkTaskStatus) -> int:
    """Prioritize the most operationally relevant compact task context."""
    match status:
        case ExternalChannelWorkTaskStatus.IN_PROGRESS:
            return 0
        case ExternalChannelWorkTaskStatus.FAILED:
            return 1
        case ExternalChannelWorkTaskStatus.COMPLETED:
            return 2
        case ExternalChannelWorkTaskStatus.PENDING:
            return 3
        case _ as unreachable:
            assert_never(unreachable)


def _task_context(task: ExternalChannelWorkTask) -> str | None:
    """Select the status-relevant task prose for the compact Tracker."""
    if task.status in {
        ExternalChannelWorkTaskStatus.COMPLETED,
        ExternalChannelWorkTaskStatus.FAILED,
    }:
        return task.output or task.details
    return task.details


def _bounded_source_line(
    task: ExternalChannelWorkTask,
    *,
    maximum: int,
) -> str | None:
    """Render as many labeled sources as fit without dropping another task."""
    prefix = "  Sources: "
    if not task.sources or maximum <= len(prefix):
        return None
    links: list[str] = []
    for source in task.sources:
        label = _truncate(_single_line(source.label), 80)
        link = f"[{label}]({source.url})"
        candidate = f"{prefix}{' · '.join((*links, link))}"
        if len(candidate) > maximum:
            break
        links.append(link)
    return f"{prefix}{' · '.join(links)}" if links else None


def _single_line(value: str) -> str:
    """Collapse multiline task prose into a compact Tracker line."""
    return " ".join(value.split())


def _truncate(value: str, maximum: int) -> str:
    """Bound visible prose while preserving deterministic ellipsis."""
    if len(value) <= maximum:
        return value
    if maximum <= 1:
        return "…"
    return f"{value[: maximum - 1].rstrip()}…"
