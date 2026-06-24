"""Prerequisite contract/snapshot path helper."""

import re
from pathlib import Path

from testenv.fixture_paths import default_testenv_root
from testenv.prerequisite_errors import (
    PrerequisiteContractSchemaError,
    PrerequisiteErrorDetail,
    PrerequisiteSnapshotSchemaError,
)

_ID_RE = re.compile(r"^[a-z][a-z0-9-]{0,62}$")


def validate_contract_id(contract_id: str) -> str:
    """Validate that a contract id is safe for file paths."""
    if not _ID_RE.fullmatch(contract_id):
        raise PrerequisiteContractSchemaError(
            PrerequisiteErrorDetail(
                code="PREREQUISITE_CONTRACT_SCHEMA_ERROR",
                message="Contract id must match ^[a-z][a-z0-9-]{0,62}$",
                contract_id=contract_id,
            )
        )
    return contract_id


def validate_snapshot_profile(profile: str) -> str:
    """Validate that a snapshot profile is safe for file paths."""
    if not _ID_RE.fullmatch(profile):
        raise PrerequisiteSnapshotSchemaError(
            PrerequisiteErrorDetail(
                code="PREREQUISITE_SNAPSHOT_SCHEMA_ERROR",
                message="Snapshot profile must match ^[a-z][a-z0-9-]{0,62}$",
                profile=profile,
            )
        )
    return profile


def contracts_root(testenv_root: Path | None = None) -> Path:
    """Return the directory containing contract YAML files."""
    root = testenv_root if testenv_root is not None else default_testenv_root()
    return root / "contracts"


def contract_path(contract_id: str, testenv_root: Path | None = None) -> Path:
    """Return the YAML path for a contract id."""
    return contracts_root(testenv_root) / f"{validate_contract_id(contract_id)}.yaml"


def prerequisite_state_root(testenv_root: Path | None = None) -> Path:
    """Return the prerequisite snapshot state directory."""
    root = testenv_root if testenv_root is not None else default_testenv_root()
    return root / ".state" / "prerequisites"


def prerequisite_snapshot_path(profile: str, testenv_root: Path | None = None) -> Path:
    """Return the prerequisite snapshot JSON path for a profile."""
    return prerequisite_state_root(testenv_root) / f"{validate_snapshot_profile(profile)}.json"
