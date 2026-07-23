"""Provider-neutral External Channel progress model tests."""

import pytest
from pydantic import ValidationError

from azents.core.enums import ExternalChannelWorkTaskStatus
from azents.core.external_channel_progress import (
    MAX_EXTERNAL_CHANNEL_DESIRED_PROGRESS_BYTES,
    ExternalChannelDesiredProgress,
    ExternalChannelWorkSource,
    ExternalChannelWorkTask,
    checking_progress,
)


def test_checking_progress_is_versioned_and_empty() -> None:
    assert checking_progress().model_dump(mode="json") == {
        "schema_version": 2,
        "state": "checking",
        "title": None,
        "tasks": [],
    }


def test_working_progress_requires_title_tasks_and_unique_ids() -> None:
    task = ExternalChannelWorkTask(
        id="inspect",
        title="Inspect failures",
        status=ExternalChannelWorkTaskStatus.IN_PROGRESS,
        details=None,
        output=None,
        sources=[],
    )

    progress = ExternalChannelDesiredProgress(
        schema_version=2,
        state="working",
        title="Investigating error logs…",
        tasks=[task],
    )

    assert progress.tasks == [task]
    with pytest.raises(ValidationError, match="requires a title and tasks"):
        ExternalChannelDesiredProgress(
            schema_version=2,
            state="working",
            title=None,
            tasks=[task],
        )
    with pytest.raises(ValidationError, match="task IDs must be unique"):
        ExternalChannelDesiredProgress(
            schema_version=2,
            state="working",
            title="Investigating error logs…",
            tasks=[task, task],
        )


def test_sources_accept_only_safe_http_urls_without_credentials() -> None:
    source = ExternalChannelWorkSource(
        url="https://example.com/logs",
        label="Error log dashboard",
    )

    assert source.url == "https://example.com/logs"
    with pytest.raises(ValidationError, match="HTTP or HTTPS"):
        ExternalChannelWorkSource(url="file:///tmp/log", label="Local log")
    with pytest.raises(ValidationError, match="cannot contain credentials"):
        ExternalChannelWorkSource(
            url="https://user:password@example.com/logs",
            label="Unsafe log",
        )


def test_working_progress_enforces_an_aggregate_snapshot_limit() -> None:
    source = ExternalChannelWorkSource(
        url=f"https://example.com/{'a' * 2_000}",
        label="S" * 500,
    )
    tasks = [
        ExternalChannelWorkTask(
            id=f"task-{index}",
            title=f"Task {index}",
            status=ExternalChannelWorkTaskStatus.IN_PROGRESS,
            details="D" * 3_000,
            output="O" * 3_000,
            sources=[source] * 20,
        )
        for index in range(2)
    ]

    with pytest.raises(ValidationError, match="exceeds the supported size"):
        ExternalChannelDesiredProgress(
            schema_version=2,
            state="working",
            title="Investigating oversized progress…",
            tasks=tasks,
        )

    assert MAX_EXTERNAL_CHANNEL_DESIRED_PROGRESS_BYTES == 64 * 1024
