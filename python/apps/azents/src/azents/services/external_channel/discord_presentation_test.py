"""Deterministic Discord message-part presentation tests."""

from azents.core.enums import ExternalChannelWorkTaskStatus
from azents.core.external_channel_progress import (
    ExternalChannelDesiredProgress,
    ExternalChannelWorkSource,
)
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


def test_checking_progress_uses_one_text_tracker() -> None:
    """Initial Discord activity is one plain-text Tracker without an Embed card."""
    presentation = render_discord_progress(
        ExternalChannelDesiredProgress(
            schema_version=2,
            state="checking",
            title=None,
            tasks=[],
        ),
        work_id="work-1",
        desired_progress_revision=1,
    )

    assert len(presentation.pages) == 1
    assert presentation.pages[0].text == "◉ Agent is checking your message"
    assert presentation.pages[0].embeds == []


def test_progress_uses_one_compact_checklist_message() -> None:
    """Discord Tracker retains rich tasks in one compact text message."""
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
                    status=ExternalChannelWorkTaskStatus.COMPLETED,
                    details=None,
                    output="Shared the final findings.",
                    sources=[
                        ExternalChannelWorkSource(
                            label="Incident report",
                            url="https://example.com/report",
                        )
                    ],
                ),
            ],
        ),
        work_id="work-1",
        desired_progress_revision=7,
    )

    assert len(presentation.pages) == 1
    assert presentation.pages[0].embeds == []
    assert presentation.pages[0].text == (
        "**Investigating the issue…** · 1/2 complete\n"
        "◉ Inspect the current incident\n"
        "  ↳ Read the provider logs.\n"
        "✓ Report the outcome\n"
        "  ↳ Shared the final findings.\n"
        "  Sources: [Incident report](https://example.com/report)"
    )


def test_progress_keeps_every_task_in_one_bounded_message() -> None:
    """Oversized rich task snapshots retain every ordered checklist item."""
    tasks = [
        ChannelWorkTask(
            id=f"task-{ordinal}",
            title=f"Task {ordinal:02d} " + ("title " * 70),
            status=(
                ExternalChannelWorkTaskStatus.IN_PROGRESS
                if ordinal == 24
                else ExternalChannelWorkTaskStatus.PENDING
            ),
            details="detail " * 50,
            output=None,
            sources=[],
        )
        for ordinal in range(49)
    ]

    presentation = render_discord_progress(
        ExternalChannelDesiredProgress(
            schema_version=2,
            state="working",
            title="Large plan",
            tasks=tasks,
        ),
        work_id="work-2",
        desired_progress_revision=8,
    )

    assert len(presentation.pages) == 1
    assert presentation.pages[0].embeds == []
    assert len(presentation.pages[0].text) <= DISCORD_DELIVERY_TEXT_LIMIT
    for ordinal in range(49):
        assert f"Task {ordinal:02d}" in presentation.pages[0].text
