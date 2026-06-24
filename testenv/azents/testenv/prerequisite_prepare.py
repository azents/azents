"""Prerequisite contract prepare command implementation."""

import datetime as dt
import hashlib
import json
from configparser import RawConfigParser
from dataclasses import dataclass
from pathlib import Path

from testenv.fixture_worktree import current_worktree_fingerprint
from testenv.prerequisite_contracts import (
    Contract,
    ContractCheckDefinition,
    CredentialContract,
    PrerequisiteContract,
    dump_contract_metadata,
    load_all_contracts,
)
from testenv.prerequisite_errors import PrerequisiteContractSchemaError, PrerequisiteErrorDetail
from testenv.prerequisite_snapshot import (
    PREREQUISITE_SNAPSHOT_SCHEMA_VERSION,
    PrerequisiteSnapshot,
    PrerequisiteSnapshotEntry,
    SnapshotCheck,
    SnapshotStatus,
    save_prerequisite_snapshot,
)

DEFAULT_PREREQUISITE_PROFILE = "live"
DEFAULT_MAX_AGE_SECONDS = 3600
_DEFAULT_AWS_REGION = "us-east-1"


@dataclass(frozen=True)
class PrerequisitePrepareResult:
    """Prepare run result and saved snapshot path."""

    snapshot: PrerequisiteSnapshot
    path: Path

    @property
    def status(self) -> str:
        """Return the aggregate snapshot status."""
        if all(entry.status == "ready" for entry in self.snapshot.entries):
            return "ready"
        if any(entry.status == "error" for entry in self.snapshot.entries):
            return "error"
        if any(entry.status == "stale" for entry in self.snapshot.entries):
            return "stale"
        return "missing"

    def to_json_dict(self) -> dict[str, object]:
        """Return the CLI JSON output dict."""
        return {
            "profile": self.snapshot.profile,
            "status": self.status,
            "path": str(self.path),
            "generated_at": self.snapshot.generated_at.isoformat(),
            "entries": [entry.model_dump(mode="json") for entry in self.snapshot.entries],
        }


def prepare_prerequisite_snapshot(
    testenv_root: Path,
    *,
    profile: str = DEFAULT_PREREQUISITE_PROFILE,
    max_age_seconds: int = DEFAULT_MAX_AGE_SECONDS,
) -> PrerequisitePrepareResult:
    """Evaluate contracts and save a prerequisite snapshot."""
    contracts = load_all_contracts(testenv_root)
    entries = _build_snapshot_entries(testenv_root, contracts)
    snapshot = PrerequisiteSnapshot(
        schema_version=PREREQUISITE_SNAPSHOT_SCHEMA_VERSION,
        profile=profile,
        generated_at=dt.datetime.now(dt.UTC),
        max_age_seconds=max_age_seconds,
        contract_hash=contract_hash(contracts),
        worktree=current_worktree_fingerprint(testenv_root),
        entries=entries,
    )
    path = save_prerequisite_snapshot(snapshot, testenv_root)
    return PrerequisitePrepareResult(snapshot=snapshot, path=path)


def contract_hash(contracts: dict[str, Contract]) -> str:
    """Return the hash of contract metadata used by the snapshot."""
    payload = {
        contract_id: dump_contract_metadata(contract)
        for contract_id, contract in sorted(contracts.items())
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _build_snapshot_entries(
    testenv_root: Path,
    contracts: dict[str, Contract],
) -> list[PrerequisiteSnapshotEntry]:
    """Build snapshot entries for every contract."""
    entries: dict[str, PrerequisiteSnapshotEntry] = {}
    for contract in contracts.values():
        entries[contract.id] = _evaluate_contract(testenv_root, contract, entries)
    return [entries[contract_id] for contract_id in sorted(entries)]


def _evaluate_contract(
    testenv_root: Path,
    contract: Contract,
    entries: dict[str, PrerequisiteSnapshotEntry],
) -> PrerequisiteSnapshotEntry:
    """Evaluate one contract."""
    checks = [_evaluate_check(testenv_root, check) for check in contract.checks]

    if isinstance(contract, PrerequisiteContract):
        checks.extend(_dependency_checks(contract, entries))

    status = _status_from_checks(checks)
    return PrerequisiteSnapshotEntry(
        contract_id=contract.id,
        kind=contract.kind,
        status=status,
        checks=checks,
        guidance=_guidance_from_status(contract, status),
    )


def _dependency_checks(
    contract: PrerequisiteContract,
    entries: dict[str, PrerequisiteSnapshotEntry],
) -> list[SnapshotCheck]:
    """Check credential dependency status for a prerequisite contract."""
    checks: list[SnapshotCheck] = []
    for credential_id in contract.credential_contract_ids:
        dependency = entries.get(credential_id)
        if dependency is None:
            raise PrerequisiteContractSchemaError(
                PrerequisiteErrorDetail(
                    code="PREREQUISITE_CONTRACT_SCHEMA_ERROR",
                    message="Prerequisite references an unknown credential contract",
                    contract_id=credential_id,
                )
            )
        checks.append(
            SnapshotCheck(
                id=f"credential-{credential_id}",
                status="pass" if dependency.status == "ready" else "fail",
                message=f"Credential contract {credential_id} is {dependency.status}",
            )
        )
    return checks


def _evaluate_check(testenv_root: Path, check: ContractCheckDefinition) -> SnapshotCheck:
    """Evaluate one contract check target."""
    if check.target.startswith("path:"):
        return _evaluate_path_check(testenv_root, check)
    if check.target.startswith("env-file:"):
        return _evaluate_env_file_check(testenv_root, check)
    if check.target.startswith("aws-shared-credentials:"):
        return _evaluate_aws_credentials_check(check)
    if check.target.startswith("aws-shared-config:"):
        return _evaluate_aws_config_check(check)
    return SnapshotCheck(
        id=check.id,
        status="skip",
        message=f"No prerequisite check evaluator for target {check.target}",
    )


def _evaluate_path_check(testenv_root: Path, check: ContractCheckDefinition) -> SnapshotCheck:
    """Check whether a path under the testenv root exists."""
    relative_path = check.target.removeprefix("path:")
    path = testenv_root / relative_path
    if path.exists():
        return SnapshotCheck(id=check.id, status="pass", message=f"Path exists: {relative_path}")
    return SnapshotCheck(id=check.id, status="fail", message=f"Path is missing: {relative_path}")


def _evaluate_env_file_check(testenv_root: Path, check: ContractCheckDefinition) -> SnapshotCheck:
    """Check whether a dotenv file contains a configured key."""
    target = check.target.removeprefix("env-file:")
    try:
        relative_path, key = target.split(":", 1)
    except ValueError:
        return SnapshotCheck(
            id=check.id,
            status="fail",
            message="Env file check target must be env-file:<path>:<key>",
        )
    path = testenv_root / relative_path
    if not path.exists():
        return SnapshotCheck(
            id=check.id, status="fail", message=f"Env file is missing: {relative_path}"
        )
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        current_key, value = line.split("=", 1)
        if current_key.strip() == key and value.strip():
            return SnapshotCheck(
                id=check.id, status="pass", message=f"Env key is configured: {key}"
            )
    return SnapshotCheck(id=check.id, status="fail", message=f"Env key is missing: {key}")


def _evaluate_aws_credentials_check(check: ContractCheckDefinition) -> SnapshotCheck:
    """Check whether an AWS shared credentials profile has required keys."""
    profile = check.target.removeprefix("aws-shared-credentials:")
    credentials_path = Path.home() / ".aws" / "credentials"
    credentials = RawConfigParser()
    credentials.read(credentials_path)
    section = profile if credentials.has_section(profile) else "default"
    if not credentials.has_section(section):
        return SnapshotCheck(id=check.id, status="fail", message=f"AWS profile missing: {profile}")
    missing_fields = [
        field
        for field in ("aws_access_key_id", "aws_secret_access_key")
        if credentials.get(section, field, fallback=None) is None
    ]
    if missing_fields:
        return SnapshotCheck(
            id=check.id,
            status="fail",
            message=f"AWS profile {section} is missing required credential fields",
        )
    return SnapshotCheck(id=check.id, status="pass", message=f"AWS profile available: {section}")


def _evaluate_aws_config_check(check: ContractCheckDefinition) -> SnapshotCheck:
    """Check AWS shared config for region metadata without reading secrets."""
    profile = check.target.removeprefix("aws-shared-config:")
    config_path = Path.home() / ".aws" / "config"
    config = RawConfigParser()
    config.read(config_path)
    profile_section = f"profile {profile}"
    section = profile_section if config.has_section(profile_section) else profile
    region = config.get(section, "region", fallback=None) if config.has_section(section) else None
    if region is None:
        return SnapshotCheck(
            id=check.id,
            status="pass",
            message=f"AWS region uses default {_DEFAULT_AWS_REGION}",
        )
    return SnapshotCheck(id=check.id, status="pass", message=f"AWS region configured: {region}")


def _status_from_checks(checks: list[SnapshotCheck]) -> SnapshotStatus:
    """Convert check statuses into a contract snapshot status."""
    if any(check.status == "fail" for check in checks):
        return "missing"
    if any(check.status == "stale" for check in checks):
        return "stale"
    return "ready"


def _guidance_from_status(contract: Contract, status: SnapshotStatus) -> str | None:
    """Return user guidance for non-ready status."""
    if status == "ready":
        return None
    if isinstance(contract, CredentialContract):
        return f"Prepare credential source for {contract.id} before running live tests."
    return f"Prepare prerequisite state for {contract.id} before running live tests."
