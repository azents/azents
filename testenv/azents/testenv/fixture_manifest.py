"""Fixture manifest models and persistence API."""

import datetime as dt
import json
import re
import uuid
from collections.abc import Iterable, Mapping, Sequence
from json import JSONDecodeError
from pathlib import Path
from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    ValidationError,
    ValidationInfo,
    field_validator,
)

from testenv.fixture_errors import (
    FixtureErrorDetail,
    FixtureManifestNotFoundError,
    FixtureManifestReadError,
    FixtureManifestSchemaError,
    FixtureSecretValidationError,
)
from testenv.fixture_paths import fixture_manifest_path, validate_fixture_id

FIXTURE_SCHEMA_VERSION = 1
_UTC = dt.UTC
_SHA_RE = re.compile(r"^[0-9a-f]{7,40}$")

_SECRET_KEY_PARTS = frozenset(
    {
        "access_token",
        "api_key",
        "authorization",
        "cookie",
        "credential",
        "id_token",
        "password",
        "passwd",
        "private_key",
        "refresh_token",
        "secret",
        "session",
        "token",
    }
)
_SECRET_REFERENCE_SUFFIXES = ("_ref", "_name", "_path", "_id")
_SECRET_VALUE_PREFIXES = ("sk-", "ghp_", "github_pat_", "bearer ")
_JWT_RE = re.compile(r"^[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$")
_AWS_ACCESS_KEY_RE = re.compile(r"^(AKIA|ASIA)[A-Z0-9]{16}$")


class WorktreeFingerprint(BaseModel):
    """Worktree fingerprint captured when a fixture is prepared."""

    model_config = ConfigDict(extra="forbid")

    repo_root: str
    head_sha: str
    dirty_hash: str | None = None
    env_hash: str | None = None
    fingerprint: str

    @field_validator("repo_root")
    @classmethod
    def _require_absolute_repo_root(cls, value: str) -> str:
        """Validate that repo_root is an absolute path string."""
        if not Path(value).is_absolute():
            msg = "repo_root must be an absolute path"
            raise ValueError(msg)
        return value

    @field_validator("head_sha")
    @classmethod
    def _require_sha_shape(cls, value: str) -> str:
        """Validate that head_sha looks like a git SHA."""
        if not _SHA_RE.fullmatch(value):
            msg = "head_sha must be a 7-40 character lowercase hex SHA"
            raise ValueError(msg)
        return value

    @field_validator("fingerprint")
    @classmethod
    def _require_non_empty_fingerprint(cls, value: str) -> str:
        """Validate that fingerprint is not empty."""
        if not value:
            msg = "fingerprint must not be empty"
            raise ValueError(msg)
        return value


class DoctorCheck(BaseModel):
    """Single fixture doctor check result."""

    model_config = ConfigDict(extra="forbid")

    id: str
    status: Literal["pass", "fail", "stale", "skip"]
    message: str | None = None


class DoctorSummary(BaseModel):
    """Summary of the latest fixture doctor run."""

    model_config = ConfigDict(extra="forbid")

    last_checked_at: dt.datetime | None = None
    last_result: Literal["pass", "fail", "stale"] | None = None
    checks: list[DoctorCheck] = Field(default_factory=list)

    @field_validator("last_checked_at")
    @classmethod
    def _require_aware_last_checked_at(
        cls,
        value: dt.datetime | None,
    ) -> dt.datetime | None:
        """Validate that the doctor timestamp is UTC timezone-aware."""
        if value is not None and value.tzinfo != _UTC:
            msg = "last_checked_at must be UTC timezone-aware"
            raise ValueError(msg)
        return value


class FixtureManifest(BaseModel):
    """Logical manifest for a prepared fixture."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1]
    fixture_id: str
    status: Literal["ready", "stale", "error"]
    created_at: dt.datetime
    updated_at: dt.datetime
    worktree: WorktreeFingerprint
    resources: dict[str, JsonValue] = Field(default_factory=dict)
    provides: dict[str, JsonValue] = Field(default_factory=dict)
    doctor: DoctorSummary | None = None

    @field_validator("fixture_id")
    @classmethod
    def _validate_fixture_id(cls, value: str) -> str:
        """Validate that fixture_id is path-safe."""
        return validate_fixture_id(value)

    @field_validator("created_at", "updated_at")
    @classmethod
    def _require_aware_datetime(cls, value: dt.datetime) -> dt.datetime:
        """Validate that manifest timestamps are UTC timezone-aware."""
        if value.tzinfo != _UTC:
            msg = "manifest timestamps must be UTC timezone-aware"
            raise ValueError(msg)
        return value

    @field_validator("updated_at")
    @classmethod
    def _validate_updated_not_before_created(
        cls,
        value: dt.datetime,
        info: ValidationInfo,
    ) -> dt.datetime:
        """Validate that updated_at is not earlier than created_at."""
        created_at = info.data.get("created_at")
        if isinstance(created_at, dt.datetime) and value < created_at:
            msg = "updated_at must be greater than or equal to created_at"
            raise ValueError(msg)
        return value


def fixture_manifest_exists(fixture_id: str, testenv_root: Path | None = None) -> bool:
    """Return whether the manifest file exists."""
    return fixture_manifest_path(fixture_id, testenv_root).exists()


def load_fixture_manifest(
    fixture_id: str,
    testenv_root: Path | None = None,
) -> FixtureManifest:
    """Load the manifest for a fixture id and validate its schema."""
    path = fixture_manifest_path(fixture_id, testenv_root)
    if not path.exists():
        detail = FixtureErrorDetail(
            code="FIXTURE_MANIFEST_NOT_FOUND",
            message=f"Fixture manifest not found: {fixture_id}",
            fixture_id=fixture_id,
            path=path,
        )
        raise FixtureManifestNotFoundError(detail)

    try:
        raw_text = path.read_text()
        raw_json = json.loads(raw_text)
        manifest = FixtureManifest.model_validate(raw_json)
    except (OSError, JSONDecodeError) as exc:
        detail = FixtureErrorDetail(
            code="FIXTURE_MANIFEST_READ_ERROR",
            message=f"Failed to read fixture manifest: {fixture_id}",
            fixture_id=fixture_id,
            path=path,
        )
        raise FixtureManifestReadError(detail) from exc
    except ValidationError as exc:
        detail = FixtureErrorDetail(
            code="FIXTURE_MANIFEST_SCHEMA_ERROR",
            message=f"Invalid fixture manifest schema: {fixture_id}",
            fixture_id=fixture_id,
            path=path,
        )
        raise FixtureManifestSchemaError(detail) from exc

    if manifest.fixture_id != fixture_id:
        detail = FixtureErrorDetail(
            code="FIXTURE_MANIFEST_SCHEMA_ERROR",
            message="Fixture id does not match manifest path",
            fixture_id=fixture_id,
            path=path,
        )
        raise FixtureManifestSchemaError(detail)

    validate_manifest_has_no_secrets(manifest)

    return manifest


def save_fixture_manifest(
    manifest: FixtureManifest,
    testenv_root: Path | None = None,
) -> Path:
    """Atomically write the manifest to .state/fixtures/<fixture-id>.json."""
    validate_manifest_has_no_secrets(manifest)
    path = fixture_manifest_path(manifest.fixture_id, testenv_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    raw = json.dumps(
        manifest.model_dump(mode="json"),
        indent=2,
        ensure_ascii=False,
        sort_keys=True,
    )
    tmp.write_text(raw)
    tmp.replace(path)
    return path


def delete_fixture_manifest(fixture_id: str, testenv_root: Path | None = None) -> bool:
    """Delete the manifest file and return whether it was removed."""
    path = fixture_manifest_path(fixture_id, testenv_root)
    if not path.exists():
        return False
    path.unlink()
    return True


def validate_manifest_has_no_secrets(manifest: FixtureManifest) -> None:
    """Reject secret-like values in resources, provides, and doctor fields."""
    payload = manifest.model_dump(mode="json")
    for field_name in ("resources", "provides", "doctor"):
        _reject_secret_like_values(
            payload.get(field_name),
            path=(field_name,),
            fixture_id=manifest.fixture_id,
        )


def _reject_secret_like_values(value: Any, path: tuple[str, ...], fixture_id: str) -> None:
    """Recursively reject secret-like keys and values in a payload."""
    if isinstance(value, Mapping):
        for key, child in value.items():
            key_text = str(key)
            child_path = (*path, key_text)
            if _secret_like_key(key_text):
                _raise_secret_validation_error(fixture_id, child_path)
            _reject_secret_like_values(child, child_path, fixture_id)
        return

    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        for index, child in enumerate(value):
            _reject_secret_like_values(child, (*path, str(index)), fixture_id)
        return

    if isinstance(value, str) and _secret_like_value(value):
        _raise_secret_validation_error(fixture_id, path)


def _secret_like_key(key: str) -> bool:
    """Return whether a key name looks like it may store a secret."""
    normalized = key.lower().replace("-", "_")
    if normalized.startswith("has_"):
        return False
    if normalized.endswith(_SECRET_REFERENCE_SUFFIXES):
        return False
    return any(part in normalized for part in _SECRET_KEY_PARTS)


def _secret_like_value(value: str) -> bool:
    """Return whether a string value looks like a secret by prefix or shape."""
    lowered = value.lower()
    if lowered.startswith(_SECRET_VALUE_PREFIXES):
        return True
    if _JWT_RE.fullmatch(value):
        return True
    if _AWS_ACCESS_KEY_RE.fullmatch(value):
        return True
    if "-----BEGIN " in value and " PRIVATE KEY-----" in value:
        return True
    return False


def _raise_secret_validation_error(fixture_id: str, path: Iterable[str]) -> None:
    """Raise a formatted secret validation error."""
    joined_path = ".".join(path)
    detail = FixtureErrorDetail(
        code="FIXTURE_SECRET_VALUE_REJECTED",
        message=f"Fixture manifest contains a secret-like value at {joined_path}",
        fixture_id=fixture_id,
    )
    raise FixtureSecretValidationError(detail)
