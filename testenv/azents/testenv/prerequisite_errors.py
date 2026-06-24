"""Prerequisite snapshot/contract error model."""

from dataclasses import dataclass


@dataclass(frozen=True)
class PrerequisiteErrorDetail:
    """Machine-readable prerequisite error detail."""

    code: str
    message: str
    contract_id: str | None = None
    path: str | None = None
    profile: str | None = None


class PrerequisiteError(RuntimeError):
    """Base exception for prerequisite snapshot/contract errors."""

    def __init__(self, detail: PrerequisiteErrorDetail):
        super().__init__(detail.message)
        self.detail = detail


class PrerequisiteContractReadError(PrerequisiteError):
    """Contract file read failure."""


class PrerequisiteContractSchemaError(PrerequisiteError):
    """Contract schema validation failure."""


class PrerequisiteSnapshotNotFoundError(PrerequisiteError):
    """Snapshot file is missing."""


class PrerequisiteSnapshotReadError(PrerequisiteError):
    """Snapshot file read failure."""


class PrerequisiteSnapshotSchemaError(PrerequisiteError):
    """Snapshot schema validation failure."""
