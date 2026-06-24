"""Tests for prerequisite snapshot consumer."""

import datetime as dt
from pathlib import Path

import pytest

from testenv.fixture_manifest import WorktreeFingerprint
from testenv.prerequisite_consumer import require_ready_prerequisite
from testenv.prerequisite_contracts import load_all_contracts
from testenv.prerequisite_errors import PrerequisiteError
from testenv.prerequisite_prepare import contract_hash
from testenv.prerequisite_snapshot import (
    PREREQUISITE_SNAPSHOT_SCHEMA_VERSION,
    PrerequisiteSnapshot,
    PrerequisiteSnapshotEntry,
    SnapshotCheck,
    SnapshotStatus,
    save_prerequisite_snapshot,
)


def _sample_worktree() -> WorktreeFingerprint:
    return WorktreeFingerprint(
        repo_root="/repo",
        head_sha="abcdef1",
        dirty_hash="sha256:dirty",
        env_hash="sha256:env",
        fingerprint="sha256:fingerprint",
    )


def test_require_ready_prerequisite_reads_snapshot_only(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Consumer checks snapshot readiness before a doctor/test run."""
    _write_contract(tmp_path)
    _write_snapshot(tmp_path, status="ready", worktree=_sample_worktree())
    monkeypatch.setattr(
        "testenv.prerequisite_consumer.current_worktree_fingerprint",
        lambda testenv_root: _sample_worktree(),
    )

    entry = require_ready_prerequisite(
        "bedrock-aws",
        profile="live",
        testenv_root=tmp_path,
        now=dt.datetime(2026, 5, 13, 10, 5, tzinfo=dt.UTC),
    )

    assert entry.contract_id == "bedrock-aws"
    assert entry.status == "ready"


def test_require_ready_prerequisite_rejects_missing_entry(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Non-ready snapshot entries return structured prerequisite errors."""
    _write_contract(tmp_path)
    _write_snapshot(tmp_path, status="missing", worktree=_sample_worktree())
    monkeypatch.setattr(
        "testenv.prerequisite_consumer.current_worktree_fingerprint",
        lambda testenv_root: _sample_worktree(),
    )

    with pytest.raises(PrerequisiteError) as exc_info:
        require_ready_prerequisite(
            "bedrock-aws",
            profile="live",
            testenv_root=tmp_path,
            now=dt.datetime(2026, 5, 13, 10, 5, tzinfo=dt.UTC),
        )

    assert exc_info.value.detail.code == "PREREQUISITE_NOT_READY"
    assert exc_info.value.detail.contract_id == "bedrock-aws"


def test_require_ready_prerequisite_rejects_stale_snapshot(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Snapshots older than TTL raise stale errors."""
    _write_contract(tmp_path)
    _write_snapshot(tmp_path, status="ready", worktree=_sample_worktree())
    monkeypatch.setattr(
        "testenv.prerequisite_consumer.current_worktree_fingerprint",
        lambda testenv_root: _sample_worktree(),
    )

    with pytest.raises(PrerequisiteError) as exc_info:
        require_ready_prerequisite(
            "bedrock-aws",
            profile="live",
            testenv_root=tmp_path,
            now=dt.datetime(2026, 5, 13, 10, 20, tzinfo=dt.UTC),
        )

    assert exc_info.value.detail.code == "PREREQUISITE_SNAPSHOT_STALE"


def _write_contract(testenv_root: Path) -> None:
    contracts = testenv_root / "contracts"
    contracts.mkdir()
    (contracts / "bedrock-aws.yaml").write_text(
        """---
kind: credential
schema_version: 1
id: bedrock-aws
title: Bedrock AWS shared credentials
source: aws-shared-credentials
secret_fields:
  - aws_access_key_id
required_fields:
  - aws_access_key_id
checks:
  - id: profile-present
    mode: read
    target: aws-shared-credentials:azents-bedrock
    description: azents-bedrock profile exists
---
""",
        encoding="utf-8",
    )


def _write_snapshot(
    testenv_root: Path,
    *,
    status: SnapshotStatus,
    worktree: WorktreeFingerprint,
) -> None:
    save_prerequisite_snapshot(
        PrerequisiteSnapshot(
            schema_version=PREREQUISITE_SNAPSHOT_SCHEMA_VERSION,
            profile="live",
            generated_at=dt.datetime(2026, 5, 13, 10, 0, tzinfo=dt.UTC),
            max_age_seconds=600,
            contract_hash=contract_hash(load_all_contracts(testenv_root)),
            worktree=worktree,
            entries=[
                PrerequisiteSnapshotEntry(
                    contract_id="bedrock-aws",
                    kind="credential",
                    status=status,
                    checks=[SnapshotCheck(id="profile-present", status="pass", message="ok")],
                )
            ],
        ),
        testenv_root,
    )
