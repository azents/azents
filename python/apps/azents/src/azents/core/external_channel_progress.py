"""Provider-neutral External Channel progress value models."""

from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from azents.core.enums import ExternalChannelWorkTaskStatus

MAX_EXTERNAL_CHANNEL_WORK_TASKS = 49
MAX_EXTERNAL_CHANNEL_WORK_TITLE_LENGTH = 500
MAX_EXTERNAL_CHANNEL_TASK_TEXT_LENGTH = 3_000
MAX_EXTERNAL_CHANNEL_TASK_SOURCES = 20
MAX_EXTERNAL_CHANNEL_DESIRED_PROGRESS_BYTES = 64 * 1024


class _ProgressModel(BaseModel):
    """Immutable provider-neutral progress model."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
    )


class ExternalChannelWorkSource(_ProgressModel):
    """One labeled HTTP or HTTPS source associated with a work task."""

    url: str = Field(min_length=1, max_length=2_048)
    label: str = Field(min_length=1, max_length=500)

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        """Allow only absolute HTTP or HTTPS source URLs."""
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("Channel Work source URLs must use HTTP or HTTPS.")
        if parsed.username is not None or parsed.password is not None:
            raise ValueError("Channel Work source URLs cannot contain credentials.")
        return value


class ExternalChannelWorkTask(_ProgressModel):
    """One ordered task in canonical Channel Work."""

    id: str = Field(min_length=1, max_length=80)
    title: str = Field(min_length=1, max_length=500)
    status: ExternalChannelWorkTaskStatus
    details: str | None = Field(
        min_length=1,
        max_length=MAX_EXTERNAL_CHANNEL_TASK_TEXT_LENGTH,
    )
    output: str | None = Field(
        min_length=1,
        max_length=MAX_EXTERNAL_CHANNEL_TASK_TEXT_LENGTH,
    )
    sources: list[ExternalChannelWorkSource] = Field(
        max_length=MAX_EXTERNAL_CHANNEL_TASK_SOURCES,
    )


class ExternalChannelDesiredProgress(_ProgressModel):
    """One complete provider-neutral desired progress snapshot."""

    schema_version: Literal[2]
    state: Literal["checking", "working"]
    title: str | None = Field(
        min_length=1,
        max_length=MAX_EXTERNAL_CHANNEL_WORK_TITLE_LENGTH,
    )
    tasks: list[ExternalChannelWorkTask] = Field(
        max_length=MAX_EXTERNAL_CHANNEL_WORK_TASKS,
    )

    @model_validator(mode="after")
    def validate_state(self) -> "ExternalChannelDesiredProgress":
        """Keep checking and working snapshots internally consistent."""
        if self.state == "checking":
            if self.title is not None or self.tasks:
                raise ValueError("Checking progress cannot contain a title or tasks.")
            return self
        if self.title is None or not self.tasks:
            raise ValueError("Working progress requires a title and tasks.")
        task_ids = [task.id for task in self.tasks]
        if len(task_ids) != len(set(task_ids)):
            raise ValueError("Channel Work task IDs must be unique.")
        if (
            len(self.model_dump_json().encode())
            > MAX_EXTERNAL_CHANNEL_DESIRED_PROGRESS_BYTES
        ):
            raise ValueError("Channel Work progress exceeds the supported size.")
        return self


def checking_progress() -> ExternalChannelDesiredProgress:
    """Return the canonical checking snapshot created before Agent execution."""
    return ExternalChannelDesiredProgress(
        schema_version=2,
        state="checking",
        title=None,
        tasks=[],
    )
