"""Detached archive purge operation snapshots."""

import dataclasses

from azents.repos.archived_session_retention.data import ArchivedSessionPurgeJob
from azents.repos.artifact.data import Artifact
from azents.repos.exchange_file.data import ExchangeFile
from azents.repos.model_file.data import ModelFile


@dataclasses.dataclass(frozen=True)
class ArchivedSessionPurgeJobSummary:
    """Result of advancing one claimed archived-session purge job."""

    completed: bool
    retry_scheduled: bool
    model_file_count: int
    artifact_count: int
    exchange_file_count: int
    worktree_count: int


@dataclasses.dataclass(frozen=True)
class PurgeFileCleanupState:
    """Durable file cleanup scope selected before external object deletion."""

    model_files: list[ModelFile]
    artifacts: list[Artifact]
    exchange_files: list[ExchangeFile]
    model_file_count: int
    artifact_count: int
    exchange_file_count: int


@dataclasses.dataclass(frozen=True)
class PurgeClaim:
    """Committed job and captured materialization failure for retry attribution."""

    job: ArchivedSessionPurgeJob | None
    materialization_error: RuntimeError | ValueError | None


@dataclasses.dataclass(frozen=True)
class PurgeRootPreparation:
    """Committed owner fencing, stop requests and detached root membership."""

    terminal: ArchivedSessionPurgeJobSummary | None
    session_ids: tuple[str, ...]
    active: bool
    preserve_scheduled: bool
