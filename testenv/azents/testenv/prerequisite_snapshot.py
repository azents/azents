"""Prerequisite snapshot read/write helper."""

import datetime as dt
import json
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from testenv.fixture_manifest import WorktreeFingerprint
from testenv.prerequisite_errors import (
    PrerequisiteErrorDetail,
    PrerequisiteSnapshotNotFoundError,
    PrerequisiteSnapshotReadError,
    PrerequisiteSnapshotSchemaError,
)
from testenv.prerequisite_paths import (
    prerequisite_snapshot_path,
    validate_contract_id,
    validate_snapshot_profile,
)

PREREQUISITE_SNAPSHOT_SCHEMA_VERSION = 1
SnapshotStatus = Literal["ready", "missing", "stale", "error"]
SnapshotCheckStatus = Literal["pass", "fail", "stale", "skip"]


class SnapshotCheck(BaseModel):
    """One prerequisite snapshot check result."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    status: SnapshotCheckStatus
    message: str = Field(min_length=1)

    @field_validator("id")
    @classmethod
    def _validate_id(cls, value: str) -> str:
        return validate_contract_id(value)


class PrerequisiteSnapshotEntry(BaseModel):
    """Snapshot entry for one contract."""

    model_config = ConfigDict(extra="forbid")

    contract_id: str = Field(min_length=1)
    kind: Literal["credential", "prerequisite"]
    status: SnapshotStatus
    checks: list[SnapshotCheck] = Field(min_length=1)
    guidance: str | None = None

    @field_validator("contract_id")
    @classmethod
    def _validate_contract_id(cls, value: str) -> str:
        return validate_contract_id(value)


class PrerequisiteSnapshot(BaseModel):
    """Prerequisite snapshot created during the prepare phase."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1]
    profile: str = Field(min_length=1)
    generated_at: dt.datetime
    max_age_seconds: int = Field(ge=1)
    contract_hash: str = Field(min_length=1)
    worktree: WorktreeFingerprint
    entries: list[PrerequisiteSnapshotEntry] = Field(default_factory=list)

    @field_validator("profile")
    @classmethod
    def _validate_profile(cls, value: str) -> str:
        return validate_snapshot_profile(value)

    @field_validator("generated_at")
    @classmethod
    def _validate_generated_at(cls, value: dt.datetime) -> dt.datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("generated_at must be timezone-aware")
        return value.astimezone(dt.UTC)

    def is_stale(self, now: dt.datetime) -> bool:
        """Return whether the snapshot is older than its TTL."""
        return (now - self.generated_at).total_seconds() > self.max_age_seconds


def save_prerequisite_snapshot(
    snapshot: PrerequisiteSnapshot,
    testenv_root: Path,
) -> Path:
    """Atomically save prerequisite snapshot JSON."""
    validate_snapshot_has_no_secrets(snapshot)
    path = prerequisite_snapshot_path(snapshot.profile, testenv_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(snapshot.model_dump(mode="json"), indent=2, ensure_ascii=False)
    temp_path = path.with_suffix(".tmp")
    temp_path.write_text(payload + "\n", encoding="utf-8")
    temp_path.replace(path)
    return path


def load_prerequisite_snapshot(profile: str, testenv_root: Path) -> PrerequisiteSnapshot:
    """Load and strictly validate the prerequisite snapshot for a profile."""
    path = prerequisite_snapshot_path(profile, testenv_root)
    if not path.exists():
        raise PrerequisiteSnapshotNotFoundError(
            PrerequisiteErrorDetail(
                code="PREREQUISITE_SNAPSHOT_NOT_FOUND",
                message="Prerequisite snapshot is missing",
                profile=profile,
                path=str(path),
            )
        )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise PrerequisiteSnapshotReadError(
            PrerequisiteErrorDetail(
                code="PREREQUISITE_SNAPSHOT_READ_ERROR",
                message=f"Failed to read prerequisite snapshot: {exc}",
                profile=profile,
                path=str(path),
            )
        ) from exc
    except json.JSONDecodeError as exc:
        raise PrerequisiteSnapshotReadError(
            PrerequisiteErrorDetail(
                code="PREREQUISITE_SNAPSHOT_READ_ERROR",
                message=f"Prerequisite snapshot is not valid JSON: {exc}",
                profile=profile,
                path=str(path),
            )
        ) from exc
    try:
        snapshot = PrerequisiteSnapshot.model_validate(payload)
    except ValidationError as exc:
        raise PrerequisiteSnapshotSchemaError(
            PrerequisiteErrorDetail(
                code="PREREQUISITE_SNAPSHOT_SCHEMA_ERROR",
                message=f"Prerequisite snapshot schema validation failed: {exc.errors()[0]['msg']}",
                profile=profile,
                path=str(path),
            )
        ) from exc
    if snapshot.profile != profile:
        raise PrerequisiteSnapshotSchemaError(
            PrerequisiteErrorDetail(
                code="PREREQUISITE_SNAPSHOT_SCHEMA_ERROR",
                message="Prerequisite snapshot profile does not match file name",
                profile=profile,
                path=str(path),
            )
        )
    validate_snapshot_has_no_secrets(snapshot)
    return snapshot


def validate_snapshot_has_no_secrets(snapshot: PrerequisiteSnapshot) -> None:
    """Reject secret-like keys and values from the snapshot payload."""
    payload = snapshot.model_dump(mode="json")
    for field_name in ("entries",):
        _reject_secret_like_values(
            payload.get(field_name),
            path=(field_name,),
            profile=snapshot.profile,
        )


def _reject_secret_like_values(value: Any, path: tuple[str, ...], profile: str) -> None:
    """Recursively reject secret-like keys and values in snapshot payloads."""
    if isinstance(value, Mapping):
        for key, child in value.items():
            key_text = str(key)
            child_path = (*path, key_text)
            if _secret_like_key(key_text):
                _raise_snapshot_secret_validation_error(profile, child_path)
            _reject_secret_like_values(child, child_path, profile)
        return

    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        for index, child in enumerate(value):
            _reject_secret_like_values(child, (*path, str(index)), profile)
        return

    if isinstance(value, str) and _secret_like_value(value):
        _raise_snapshot_secret_validation_error(profile, path)


def _secret_like_key(key: str) -> bool:
    """Return whether a key name looks like it may store a secret."""
    normalized = key.lower().replace("-", "_")
    if normalized.endswith(("_ref", "_path", "_source", "_source_path")):
        return False
    return any(
        part in normalized for part in ("secret", "token", "password", "api_key", "access_key")
    )


def _secret_like_value(value: str) -> bool:
    """Return whether a string value matches a secret-like prefix or pattern."""
    lowered = value.lower()
    if lowered.startswith(("sk-", "ghp_", "github_pat_", "eyj", "akia")):
        return True
    if "-----BEGIN " in value and " PRIVATE KEY-----" in value:
        return True
    return False


def _raise_snapshot_secret_validation_error(profile: str, path: Iterable[str]) -> None:
    """Raise a formatted error for a secret-like snapshot payload."""
    joined_path = ".".join(path)
    raise PrerequisiteSnapshotSchemaError(
        PrerequisiteErrorDetail(
            code="PREREQUISITE_SNAPSHOT_SECRET_VALUE_REJECTED",
            message=f"Prerequisite snapshot contains a secret-like value at {joined_path}",
            profile=profile,
        )
    )
