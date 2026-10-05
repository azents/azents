"""Detached file cleanup database operation snapshots."""

import dataclasses

from azents.repos.artifact.data import Artifact
from azents.repos.exchange_file.data import ExchangeFile
from azents.repos.model_file.data import ModelFile


@dataclasses.dataclass(frozen=True)
class PendingBlobDeletionIds:
    """IDs eligible for blob deletion before the current cleanup pass."""

    artifact_ids: frozenset[str]
    exchange_file_ids: frozenset[str]
    model_file_ids: frozenset[str]


@dataclasses.dataclass(frozen=True)
class FileLifecycleBlobDeletionSummary:
    """Result of the bounded terminal-blob deletion stage."""

    attempted: int
    artifact_blobs_deleted: int
    exchange_file_blobs_deleted: int
    model_file_blobs_deleted: int
    pending_attempts: int
    failures: int


@dataclasses.dataclass(frozen=True)
class ModelFileCleanupResult:
    """Result of one ModelFile metadata cleanup pass."""

    deleted_count: int
    sessions_advanced: int


@dataclasses.dataclass(frozen=True)
class PendingBlobDeletionBatch:
    """Terminal file metadata captured before external object deletion."""

    artifacts: list[Artifact]
    exchange_files: list[ExchangeFile]
    model_files: list[ModelFile]
