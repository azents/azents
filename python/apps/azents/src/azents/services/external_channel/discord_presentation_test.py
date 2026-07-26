"""Deterministic Discord message-part presentation tests."""

from azents.core.enums import ExternalChannelWorkTaskStatus
from azents.core.external_channel_progress import ExternalChannelDesiredProgress
from azents.repos.external_channel.work_data import ChannelWorkTask
from azents.services.external_channel.discord_presentation import (
    DISCORD_DELIVERY_TEXT_LIMIT,
    render_discord_progress,
    split_discord_markdown,
)


def test_splits_long_text_at_readable_boundaries() -> None:
    """Every persisted part leaves room for current Agent attribution."""
    text = ("word " * 500).strip()

    parts = split_discord_markdown(text)

    assert len(parts) > 1
    assert "".join(part.replace("\n", "") for part in parts).replace(" ", "") == (
        text.replace(" ", "")
    )
    assert all(len(part) <= DISCORD_DELIVERY_TEXT_LIMIT for part in parts)


def test_reopens_and_closes_fenced_code_when_a_part_crosses_its_body() -> None:
    """Code fences stay balanced in every visible Discord message part."""
    text = "Before\n```python\n" + ("x = 1\n" * 400) + "```\nAfter"

    parts = split_discord_markdown(text)

    assert len(parts) > 1
    assert all(part.count("```") % 2 == 0 for part in parts)
    assert any(part.endswith("\n```") for part in parts[:-1])
    assert any(part.startswith("```python\n") for part in parts[1:])


def test_progress_uses_a_summary_page_then_ordered_bounded_task_pages() -> None:
    """Discord Tracker pages retain canonical task order and bounded presentation."""
    presentation = render_discord_progress(
        ExternalChannelDesiredProgress(
            schema_version=2,
            state="working",
            title="Investigating the issue…",
            tasks=[
                ChannelWorkTask(
                    id="investigate",
                    title="Inspect the current incident",
                    status=ExternalChannelWorkTaskStatus.IN_PROGRESS,
                    details="Read the provider logs.",
                    output=None,
                    sources=[],
                ),
                ChannelWorkTask(
                    id="report",
                    title="Report the outcome",
                    status=ExternalChannelWorkTaskStatus.PENDING,
                    details=None,
                    output=None,
                    sources=[],
                ),
            ],
        ),
        work_id="work-1",
        desired_progress_revision=7,
    )

    assert presentation.pages[0] == (
        "## Investigating the issue…\n"
        "2 task(s) · 1 in progress · 1 pending · 0 completed · 0 failed"
    )
    assert "Inspect the current incident" in "".join(presentation.pages[1:])
    assert "Report the outcome" in "".join(presentation.pages[1:])
    assert all(len(page) <= DISCORD_DELIVERY_TEXT_LIMIT for page in presentation.pages)
