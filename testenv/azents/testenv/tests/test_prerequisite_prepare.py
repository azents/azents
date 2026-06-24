"""Tests for prerequisite prepare command."""

from pathlib import Path

import pytest
from typer.testing import CliRunner

from testenv.cli import app
from testenv.fixture_manifest import WorktreeFingerprint
from testenv.prerequisite_prepare import prepare_prerequisite_snapshot

_RUNNER = CliRunner()


def _sample_worktree() -> WorktreeFingerprint:
    return WorktreeFingerprint(
        repo_root="/repo",
        head_sha="abcdef1",
        dirty_hash="sha256:dirty",
        env_hash="sha256:env",
        fingerprint="sha256:fingerprint",
    )


def test_prerequisite_cli_registers_prepare_group() -> None:
    """Typer app wires the prerequisite prepare subcommand."""
    result = _RUNNER.invoke(app, ["prerequisite", "--help"])

    assert result.exit_code == 0
    assert "External credential/prerequisite snapshot commands." in result.stdout


def test_prepare_prerequisite_snapshot_writes_safe_metadata(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """prepare saves a secret-free contract readiness snapshot."""
    _write_default_contracts(tmp_path)
    _write_aws_files(tmp_path)
    (tmp_path / "runs" / "_state").mkdir(parents=True)
    (tmp_path / "runs" / "_state" / "browser-oauth.json").write_text(
        "{}",
        encoding="utf-8",
    )
    (tmp_path / ".env").write_text(
        "AZENTS_PUBLIC_BASE_URL=http://localhost:3000\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("testenv.prerequisite_prepare.Path.home", lambda: tmp_path)
    monkeypatch.setattr(
        "testenv.prerequisite_prepare.current_worktree_fingerprint",
        lambda testenv_root: _sample_worktree(),
    )

    result = prepare_prerequisite_snapshot(tmp_path, profile="live", max_age_seconds=60)

    assert result.status == "ready"
    assert result.path == tmp_path / ".state" / "prerequisites" / "live.json"
    assert {entry.contract_id: entry.status for entry in result.snapshot.entries} == {
        "bedrock-aws": "ready",
        "browser-oauth": "ready",
    }
    payload = result.path.read_text(encoding="utf-8")
    assert "AKIA" not in payload
    assert "secret" not in payload.lower()


def test_prepare_prerequisite_snapshot_marks_missing_without_secrets(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Missing credential source is reported as a structured prepare result."""
    _write_default_contracts(tmp_path)
    monkeypatch.setattr("testenv.prerequisite_prepare.Path.home", lambda: tmp_path)
    monkeypatch.setattr(
        "testenv.prerequisite_prepare.current_worktree_fingerprint",
        lambda testenv_root: _sample_worktree(),
    )

    result = prepare_prerequisite_snapshot(tmp_path, profile="live", max_age_seconds=60)

    assert result.status == "missing"
    entries = {entry.contract_id: entry for entry in result.snapshot.entries}
    assert entries["bedrock-aws"].status == "missing"
    assert entries["browser-oauth"].status == "missing"
    assert entries["bedrock-aws"].guidance == (
        "Prepare credential source for bedrock-aws before running live tests."
    )


def _write_default_contracts(testenv_root: Path) -> None:
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
  - aws_secret_access_key
required_fields:
  - aws_access_key_id
  - aws_secret_access_key
checks:
  - id: profile-present
    mode: read
    target: aws-shared-credentials:azents-bedrock
    description: azents-bedrock profile exists
  - id: region-present
    mode: read
    target: aws-shared-config:azents-bedrock
    description: region is configured
---
""",
        encoding="utf-8",
    )
    (contracts / "browser-oauth.yaml").write_text(
        """---
kind: prerequisite
schema_version: 1
id: browser-oauth
title: Browser OAuth storage state
source: browser-state
secret_fields:
  - storage_state_ref
credential_contract_ids: []
checks:
  - id: storage-state-artifact
    mode: read
    target: path:runs/_state/browser-oauth.json
    description: Browser OAuth storage state artifact exists
  - id: oauth-callback-config
    mode: read
    target: env-file:.env:AZENTS_PUBLIC_BASE_URL
    description: Browser OAuth callback base URL is configured
---
""",
        encoding="utf-8",
    )


def _write_aws_files(home: Path) -> None:
    aws_root = home / ".aws"
    aws_root.mkdir()
    (aws_root / "credentials").write_text(
        """[azents-bedrock]
aws_access_key_id = EXAMPLE_AWS_ACCESS_KEY_ID
aws_secret_access_key = secret-value
""",
        encoding="utf-8",
    )
    (aws_root / "config").write_text(
        """[profile azents-bedrock]
region = us-east-1
""",
        encoding="utf-8",
    )
