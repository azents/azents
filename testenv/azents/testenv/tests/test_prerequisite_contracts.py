"""Tests for prerequisite contract and snapshot foundation."""

import datetime as dt
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from testenv.fixture_manifest import WorktreeFingerprint
from testenv.prerequisite_contracts import (
    CONTRACT_SCHEMA_VERSION,
    CredentialContract,
    PrerequisiteContract,
    dump_contract_metadata,
    load_all_contracts,
    load_contract,
)
from testenv.prerequisite_errors import (
    PrerequisiteContractSchemaError,
    PrerequisiteSnapshotNotFoundError,
    PrerequisiteSnapshotReadError,
    PrerequisiteSnapshotSchemaError,
)
from testenv.prerequisite_paths import (
    contract_path,
    contracts_root,
    prerequisite_snapshot_path,
    prerequisite_state_root,
    validate_contract_id,
    validate_snapshot_profile,
)
from testenv.prerequisite_snapshot import (
    PREREQUISITE_SNAPSHOT_SCHEMA_VERSION,
    PrerequisiteSnapshot,
    PrerequisiteSnapshotEntry,
    SnapshotCheck,
    load_prerequisite_snapshot,
    save_prerequisite_snapshot,
)


def _write(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def _sample_worktree() -> WorktreeFingerprint:
    return WorktreeFingerprint(
        repo_root="/repo",
        head_sha="abcdef1",
        dirty_hash="sha256:dirty",
        env_hash="sha256:env",
        fingerprint="sha256:fingerprint",
    )


def test_contract_and_snapshot_paths(tmp_path: Path) -> None:
    assert contracts_root(tmp_path) == tmp_path / "contracts"
    assert contract_path("bedrock-aws", tmp_path) == tmp_path / "contracts" / "bedrock-aws.yaml"
    assert prerequisite_state_root(tmp_path) == tmp_path / ".state" / "prerequisites"
    assert prerequisite_snapshot_path("live", tmp_path) == (
        tmp_path / ".state" / "prerequisites" / "live.json"
    )


@pytest.mark.parametrize("value", ["bedrock-aws", "browser-oauth", "a"])
def test_validate_safe_ids(value: str) -> None:
    assert validate_contract_id(value) == value
    assert validate_snapshot_profile(value) == value


@pytest.mark.parametrize("value", ["", "Bad", "../bad", "bad_id", "1bad", ".bad"])
def test_validate_unsafe_ids(value: str) -> None:
    with pytest.raises(PrerequisiteContractSchemaError):
        validate_contract_id(value)
    with pytest.raises(PrerequisiteSnapshotSchemaError):
        validate_snapshot_profile(value)


def test_load_credential_contract(tmp_path: Path) -> None:
    _write(
        tmp_path / "contracts" / "bedrock-aws.yaml",
        """---
kind: credential
schema_version: 1
id: bedrock-aws
title: Bedrock AWS credential
source: aws-shared-credentials
secret_fields:
  - aws_access_key_id
  - aws_secret_access_key
required_fields:
  - aws_access_key_id
  - aws_secret_access_key
checks:
  - id: profile-present
    mode: read
    target: ~/.aws/credentials
    description: Named profile exists
---
""",
    )
    contract = load_contract(tmp_path / "contracts" / "bedrock-aws.yaml")
    assert isinstance(contract, CredentialContract)
    assert contract.id == "bedrock-aws"
    assert dump_contract_metadata(contract) == {
        "schema_version": CONTRACT_SCHEMA_VERSION,
        "id": "bedrock-aws",
        "kind": "credential",
        "source": "aws-shared-credentials",
        "secret_fields": ["aws_access_key_id", "aws_secret_access_key"],
        "required_fields": ["aws_access_key_id", "aws_secret_access_key"],
        "checks": [
            {
                "id": "profile-present",
                "mode": "read",
                "target": "~/.aws/credentials",
                "description": "Named profile exists",
            }
        ],
    }


def test_load_prerequisite_contract(tmp_path: Path) -> None:
    _write(
        tmp_path / "contracts" / "browser-oauth.yaml",
        """---
kind: prerequisite
schema_version: 1
id: browser-oauth
title: Browser OAuth prerequisite
source: browser-state
secret_fields:
  - storage_state_ref
credential_contract_ids:
  - bedrock-aws
checks:
  - id: storage-state-present
    mode: read
    target: .state/browser/oauth.json
    description: Browser storage state exists
---
""",
    )
    contract = load_contract(tmp_path / "contracts" / "browser-oauth.yaml")
    assert isinstance(contract, PrerequisiteContract)
    assert contract.credential_contract_ids == ["bedrock-aws"]


def test_load_contract_rejects_bad_schema(tmp_path: Path) -> None:
    _write(
        tmp_path / "contracts" / "bad.yaml",
        """---
kind: credential
schema_version: 1
id: different-id
title: Bad contract
source: env
secret_fields:
  - token
required_fields:
  - token
checks:
  - id: check
    mode: read
    target: env
    description: desc
---
""",
    )
    with pytest.raises(PrerequisiteContractSchemaError, match="does not match"):
        load_contract(tmp_path / "contracts" / "bad.yaml")


def test_load_all_contracts(tmp_path: Path) -> None:
    _write(
        tmp_path / "contracts" / "one.yaml",
        """---
kind: credential
schema_version: 1
id: one
title: One
source: env
secret_fields:
  - token
required_fields:
  - token
checks:
  - id: one-check
    mode: static
    target: env
    description: desc
---
""",
    )
    _write(
        tmp_path / "contracts" / "two.yaml",
        """---
kind: prerequisite
schema_version: 1
id: two
title: Two
source: file
secret_fields:
  - token-ref
credential_contract_ids:
  - one
checks:
  - id: two-check
    mode: read
    target: file
    description: desc
---
""",
    )
    loaded = load_all_contracts(tmp_path)
    assert list(loaded) == ["one", "two"]


def test_dump_contract_metadata_changes_when_contract_semantics_change(
    tmp_path: Path,
) -> None:
    """Contract hash includes target and dependency metadata."""
    contract_path = tmp_path / "contracts" / "bedrock-aws.yaml"
    _write(
        contract_path,
        """---
kind: credential
schema_version: 1
id: bedrock-aws
title: Bedrock AWS credential
source: aws-shared-credentials
secret_fields:
  - aws_access_key_id
required_fields:
  - aws_access_key_id
checks:
  - id: profile-present
    mode: read
    target: aws-shared-credentials:azents-bedrock
    description: Named profile exists
---
""",
    )
    original = dump_contract_metadata(load_contract(contract_path))

    _write(
        contract_path,
        """---
kind: credential
schema_version: 1
id: bedrock-aws
title: Bedrock AWS credential
source: aws-shared-credentials
secret_fields:
  - aws_access_key_id
required_fields:
  - aws_access_key_id
checks:
  - id: profile-present
    mode: read
    target: aws-shared-credentials:default
    description: Named profile exists
---
""",
    )

    assert dump_contract_metadata(load_contract(contract_path)) != original


def test_save_and_load_snapshot_round_trip(tmp_path: Path) -> None:
    snapshot = PrerequisiteSnapshot(
        schema_version=PREREQUISITE_SNAPSHOT_SCHEMA_VERSION,
        profile="live",
        generated_at=dt.datetime(2026, 5, 13, 3, 0, tzinfo=dt.UTC),
        max_age_seconds=600,
        contract_hash="sha256:contracts",
        worktree=_sample_worktree(),
        entries=[
            PrerequisiteSnapshotEntry(
                contract_id="bedrock-aws",
                kind="credential",
                status="ready",
                checks=[SnapshotCheck(id="profile-present", status="pass", message="ok")],
                guidance=None,
            )
        ],
    )
    path = save_prerequisite_snapshot(snapshot, tmp_path)
    loaded = load_prerequisite_snapshot("live", tmp_path)
    assert path == tmp_path / ".state" / "prerequisites" / "live.json"
    assert loaded == snapshot
    assert loaded.is_stale(dt.datetime(2026, 5, 13, 3, 9, 59, tzinfo=dt.UTC)) is False
    assert loaded.is_stale(dt.datetime(2026, 5, 13, 3, 10, 1, tzinfo=dt.UTC)) is True


def test_snapshot_requires_timezone_aware_generated_at(tmp_path: Path) -> None:
    del tmp_path
    with pytest.raises(ValidationError, match="timezone-aware"):
        PrerequisiteSnapshot(
            schema_version=PREREQUISITE_SNAPSHOT_SCHEMA_VERSION,
            profile="live",
            generated_at=dt.datetime(2026, 5, 13, 3, 0),
            max_age_seconds=600,
            contract_hash="sha256:contracts",
            worktree=_sample_worktree(),
            entries=[
                PrerequisiteSnapshotEntry(
                    contract_id="bedrock-aws",
                    kind="credential",
                    status="ready",
                    checks=[SnapshotCheck(id="profile-present", status="pass", message="ok")],
                )
            ],
        )


def test_snapshot_rejects_secret_like_payload(tmp_path: Path) -> None:
    snapshot = PrerequisiteSnapshot(
        schema_version=PREREQUISITE_SNAPSHOT_SCHEMA_VERSION,
        profile="live",
        generated_at=dt.datetime(2026, 5, 13, 3, 0, tzinfo=dt.UTC),
        max_age_seconds=600,
        contract_hash="sha256:contracts",
        worktree=_sample_worktree(),
        entries=[
            PrerequisiteSnapshotEntry(
                contract_id="bedrock-aws",
                kind="credential",
                status="ready",
                checks=[
                    SnapshotCheck(
                        id="profile-present",
                        status="pass",
                        message="sk-secret-token",
                    )
                ],
            )
        ],
    )

    with pytest.raises(PrerequisiteSnapshotSchemaError, match="secret-like"):
        save_prerequisite_snapshot(snapshot, tmp_path)


def test_load_snapshot_missing_read_and_schema_errors(tmp_path: Path) -> None:
    with pytest.raises(PrerequisiteSnapshotNotFoundError):
        load_prerequisite_snapshot("live", tmp_path)

    path = prerequisite_snapshot_path("live", tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{bad", encoding="utf-8")
    with pytest.raises(PrerequisiteSnapshotReadError):
        load_prerequisite_snapshot("live", tmp_path)

    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "profile": "other",
                "generated_at": "2026-05-13T03:00:00Z",
                "max_age_seconds": 600,
                "contract_hash": "sha256:contracts",
                "worktree": _sample_worktree().model_dump(mode="json"),
                "entries": [],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(PrerequisiteSnapshotSchemaError, match="does not match"):
        load_prerequisite_snapshot("live", tmp_path)


def test_validate_snapshot_profile_uses_snapshot_error() -> None:
    with pytest.raises(PrerequisiteSnapshotSchemaError):
        validate_snapshot_profile("Bad")
