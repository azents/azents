"""Tests for the fixture manifest foundation."""

import datetime as dt
import json
from pathlib import Path

import pytest

from testenv.fixture_errors import (
    FixtureManifestNotFoundError,
    FixtureManifestReadError,
    FixtureManifestSchemaError,
    FixtureSecretValidationError,
)
from testenv.fixture_manifest import (
    FIXTURE_SCHEMA_VERSION,
    DoctorCheck,
    DoctorSummary,
    FixtureManifest,
    WorktreeFingerprint,
    delete_fixture_manifest,
    fixture_manifest_exists,
    load_fixture_manifest,
    save_fixture_manifest,
    validate_manifest_has_no_secrets,
)
from testenv.fixture_paths import fixture_manifest_path, fixture_state_root, validate_fixture_id


def _sample_manifest(fixture_id: str = "agent-basic") -> FixtureManifest:
    """Create a fixture manifest for tests."""
    now = dt.datetime.now(dt.UTC)
    return FixtureManifest(
        schema_version=FIXTURE_SCHEMA_VERSION,
        fixture_id=fixture_id,
        status="ready",
        created_at=now,
        updated_at=now,
        worktree=WorktreeFingerprint(
            repo_root="/repo",
            head_sha="abcdef1",
            dirty_hash=None,
            env_hash=None,
            fingerprint="fingerprint-1",
        ),
        resources={"public_url": "http://localhost:8010"},
        provides={"user.email": "qa@example.com", "agent.id": "agent_123"},
        doctor=DoctorSummary(
            last_checked_at=now,
            last_result="pass",
            checks=[DoctorCheck(id="manifest", status="pass", message="Manifest is valid")],
        ),
    )


def test_fixture_paths_use_state_fixtures_root(tmp_path: Path) -> None:
    """Fixture path helpers use .state/fixtures JSON paths."""
    assert fixture_state_root(tmp_path) == tmp_path / ".state" / "fixtures"
    assert fixture_manifest_path("agent-basic", tmp_path) == (
        tmp_path / ".state" / "fixtures" / "agent-basic.json"
    )


@pytest.mark.parametrize("fixture_id", ["agent-basic", "devserver", "a", "agent-basic-2"])
def test_validate_fixture_id_accepts_safe_ids(fixture_id: str) -> None:
    """Fixture ids allow path-safe kebab-case values."""
    assert validate_fixture_id(fixture_id) == fixture_id


@pytest.mark.parametrize(
    "fixture_id",
    ["", ".hidden", "Agent", "agent_basic", "../agent", "agent/one", "-bad", "1agent", "a" * 64],
)
def test_validate_fixture_id_rejects_unsafe_ids(fixture_id: str) -> None:
    """Fixture ids reject path traversal and unsafe values."""
    with pytest.raises(FixtureManifestSchemaError) as exc_info:
        validate_fixture_id(fixture_id)

    assert exc_info.value.detail.code == "FIXTURE_MANIFEST_SCHEMA_ERROR"


def test_save_and_load_manifest_round_trip(tmp_path: Path) -> None:
    """Manifests round-trip through atomic save and model load."""
    manifest = _sample_manifest()

    path = save_fixture_manifest(manifest, tmp_path)
    loaded = load_fixture_manifest("agent-basic", tmp_path)

    assert path == tmp_path / ".state" / "fixtures" / "agent-basic.json"
    assert loaded == manifest
    assert fixture_manifest_exists("agent-basic", tmp_path) is True


def test_saved_manifest_is_json_without_tmp_files(tmp_path: Path) -> None:
    """Save writes event JSON without leaving temporary files."""
    manifest = _sample_manifest()

    path = save_fixture_manifest(manifest, tmp_path)
    raw = json.loads(path.read_text())

    assert raw["schema_version"] == 1
    assert raw["fixture_id"] == "agent-basic"
    assert list(path.parent.glob("*.tmp")) == []


def test_load_missing_manifest_raises_not_found(tmp_path: Path) -> None:
    """Missing manifest files raise a machine-readable not-found error."""
    with pytest.raises(FixtureManifestNotFoundError) as exc_info:
        load_fixture_manifest("agent-basic", tmp_path)

    assert exc_info.value.detail.code == "FIXTURE_MANIFEST_NOT_FOUND"


def test_load_corrupt_json_raises_read_error(tmp_path: Path) -> None:
    """Invalid JSON raises a read error."""
    path = fixture_manifest_path("agent-basic", tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text("{not-json")

    with pytest.raises(FixtureManifestReadError) as exc_info:
        load_fixture_manifest("agent-basic", tmp_path)

    assert exc_info.value.detail.code == "FIXTURE_MANIFEST_READ_ERROR"


def test_load_schema_mismatch_raises_schema_error(tmp_path: Path) -> None:
    """Schema version mismatch raises a schema error."""
    manifest = _sample_manifest()
    payload = manifest.model_dump(mode="json")
    payload["schema_version"] = 2
    path = fixture_manifest_path("agent-basic", tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(payload))

    with pytest.raises(FixtureManifestSchemaError) as exc_info:
        load_fixture_manifest("agent-basic", tmp_path)

    assert exc_info.value.detail.code == "FIXTURE_MANIFEST_SCHEMA_ERROR"


def test_load_unknown_manifest_field_raises_schema_error(tmp_path: Path) -> None:
    """Unknown manifest root fields raise a schema error."""
    manifest = _sample_manifest().model_dump(mode="json")
    manifest["unexpected_field"] = "unexpected"
    path = fixture_manifest_path("agent-basic", tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(manifest))

    with pytest.raises(FixtureManifestSchemaError) as exc_info:
        load_fixture_manifest("agent-basic", tmp_path)

    assert exc_info.value.detail.code == "FIXTURE_MANIFEST_SCHEMA_ERROR"


def test_load_fixture_id_path_mismatch_raises_schema_error(tmp_path: Path) -> None:
    """File fixture id must match the payload fixture id."""
    manifest = _sample_manifest(fixture_id="devserver")
    path = fixture_manifest_path("agent-basic", tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(manifest.model_dump(mode="json")))

    with pytest.raises(FixtureManifestSchemaError) as exc_info:
        load_fixture_manifest("agent-basic", tmp_path)

    assert exc_info.value.detail.message == "Fixture id does not match manifest path"


def test_delete_fixture_manifest_returns_whether_deleted(tmp_path: Path) -> None:
    """Delete helper returns whether a file was deleted."""
    save_fixture_manifest(_sample_manifest(), tmp_path)

    assert delete_fixture_manifest("agent-basic", tmp_path) is True
    assert fixture_manifest_exists("agent-basic", tmp_path) is False
    assert delete_fixture_manifest("agent-basic", tmp_path) is False


def test_secret_key_is_rejected_before_save(tmp_path: Path) -> None:
    """Secret-like keys block manifest save."""
    manifest = _sample_manifest().model_copy(update={"provides": {"access_token": "abc"}})

    with pytest.raises(FixtureSecretValidationError) as exc_info:
        save_fixture_manifest(manifest, tmp_path)

    assert exc_info.value.detail.code == "FIXTURE_SECRET_VALUE_REJECTED"


@pytest.mark.parametrize(
    ("field_name", "expected_path"),
    [
        ("session", "provides.session"),
        ("credential", "provides.credential"),
        ("authorization", "provides.authorization"),
        ("api_token", "provides.api_token"),
    ],
)
def test_secret_key_patterns_are_rejected(field_name: str, expected_path: str) -> None:
    """Raw secret-like key names are blocked even with public values."""
    manifest = _sample_manifest().model_copy(update={"provides": {field_name: "public-handle"}})

    with pytest.raises(FixtureSecretValidationError) as exc_info:
        validate_manifest_has_no_secrets(manifest)

    assert exc_info.value.detail.message == (
        f"Fixture manifest contains a secret-like value at {expected_path}"
    )


def test_load_rejects_manually_edited_manifest_with_secret_like_value(tmp_path: Path) -> None:
    """Manually edited manifests with secret-like values are blocked on load."""
    manifest = _sample_manifest().model_dump(mode="json")
    manifest["provides"] = {"session_token_ref": "sk-secret"}
    path = fixture_manifest_path("agent-basic", tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(manifest))

    with pytest.raises(FixtureSecretValidationError) as exc_info:
        load_fixture_manifest("agent-basic", tmp_path)

    assert exc_info.value.detail.code == "FIXTURE_SECRET_VALUE_REJECTED"


def test_secret_value_prefix_is_rejected() -> None:
    """Secret-like string prefixes are blocked."""
    manifest = _sample_manifest().model_copy(update={"resources": {"session_ref": "sk-secret"}})

    with pytest.raises(FixtureSecretValidationError):
        validate_manifest_has_no_secrets(manifest)


@pytest.mark.parametrize(
    ("field_name", "field_value"),
    [
        ("authorization_ref", "Bearer secret-value"),
        ("jwt_ref", "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.signature"),
        ("aws_access_key_ref", "AKIA" + "1234567890ABCDEF"),
        (
            "private_key_ref",
            "-----BEGIN " + "RSA PRIVATE KEY-----\nabc\n-----END RSA PRIVATE KEY-----",
        ),
        ("git_token_ref", "github" + "_pat" + "_1234567890secret"),
    ],
)
def test_secret_value_patterns_are_rejected(field_name: str, field_value: str) -> None:
    """Secret-like string values are blocked even under reference-like keys."""
    manifest = _sample_manifest().model_copy(update={"resources": {field_name: field_value}})

    with pytest.raises(FixtureSecretValidationError):
        validate_manifest_has_no_secrets(manifest)


def test_reference_like_secret_keys_and_public_values_are_allowed(tmp_path: Path) -> None:
    """Reference names and public values are allowed by secret validation."""
    manifest = _sample_manifest().model_copy(
        update={
            "resources": {
                "ssm_parameter_name": "/testenv/azents/browser-account/password",
                "has_dummy_key": True,
            },
            "provides": {
                "devserver.public_url": "http://localhost:8010",
                "session_token_ref": "state/session-token",
            },
        }
    )

    path = save_fixture_manifest(manifest, tmp_path)

    assert path.exists()


def test_naive_datetime_is_rejected() -> None:
    """Manifest timestamps must be timezone-aware."""
    naive = dt.datetime(2026, 5, 12, 1, 2, 3)

    with pytest.raises(ValueError, match="UTC timezone-aware"):
        FixtureManifest(
            schema_version=FIXTURE_SCHEMA_VERSION,
            fixture_id="agent-basic",
            status="ready",
            created_at=naive,
            updated_at=naive,
            worktree=WorktreeFingerprint(
                repo_root="/repo",
                head_sha="abcdef1",
                fingerprint="fingerprint-1",
            ),
        )


def test_updated_at_before_created_at_is_rejected() -> None:
    """updated_at before created_at fails schema validation."""
    created_at = dt.datetime(2026, 5, 12, 1, 2, 4, tzinfo=dt.UTC)
    updated_at = dt.datetime(2026, 5, 12, 1, 2, 3, tzinfo=dt.UTC)

    with pytest.raises(ValueError, match="greater than or equal"):
        FixtureManifest(
            schema_version=FIXTURE_SCHEMA_VERSION,
            fixture_id="agent-basic",
            status="ready",
            created_at=created_at,
            updated_at=updated_at,
            worktree=WorktreeFingerprint(
                repo_root="/repo",
                head_sha="abcdef1",
                fingerprint="fingerprint-1",
            ),
        )


def test_worktree_repo_root_must_be_absolute() -> None:
    """worktree.repo_root must be an absolute path."""
    with pytest.raises(ValueError, match="absolute path"):
        WorktreeFingerprint(
            repo_root="repo",
            head_sha="abcdef1",
            fingerprint="fingerprint-1",
        )


def test_worktree_head_sha_must_look_like_git_sha() -> None:
    """worktree.head_sha must look like a git SHA."""
    with pytest.raises(ValueError, match="lowercase hex SHA"):
        WorktreeFingerprint(
            repo_root="/repo",
            head_sha="abc123",
            fingerprint="fingerprint-1",
        )
