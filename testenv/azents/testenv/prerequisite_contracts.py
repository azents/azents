"""Credential/prerequisite contract strict schema loader."""

from collections.abc import Mapping
from pathlib import Path
from typing import Literal

import frontmatter
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from testenv.prerequisite_errors import (
    PrerequisiteContractReadError,
    PrerequisiteContractSchemaError,
    PrerequisiteErrorDetail,
)
from testenv.prerequisite_paths import contracts_root, validate_contract_id

CONTRACT_SCHEMA_VERSION = 1

ContractSource = Literal["env", "aws-shared-credentials", "file", "browser-state", "manual"]
CheckMode = Literal["static", "read", "live", "setup"]


class ContractCheckDefinition(BaseModel):
    """One check defined by a contract."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    mode: CheckMode
    target: str = Field(min_length=1)
    description: str = Field(min_length=1)

    @field_validator("id")
    @classmethod
    def _validate_id(cls, value: str) -> str:
        return validate_contract_id(value)


class BaseContractDocument(BaseModel):
    """Fields shared by credential and prerequisite contracts."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1]
    id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    source: ContractSource
    secret_fields: list[str] = Field(default_factory=list)
    checks: list[ContractCheckDefinition] = Field(min_length=1)

    @field_validator("id")
    @classmethod
    def _validate_id(cls, value: str) -> str:
        return validate_contract_id(value)

    @field_validator("secret_fields")
    @classmethod
    def _validate_secret_fields(cls, values: list[str]) -> list[str]:
        if not values:
            raise ValueError("secret_fields must not be empty")
        for value in values:
            if not value.strip():
                raise ValueError("secret_fields must not contain empty values")
        return values


class CredentialContract(BaseContractDocument):
    """Contract that verifies whether a secret source exists."""

    kind: Literal["credential"]
    required_fields: list[str] = Field(min_length=1)

    @field_validator("required_fields")
    @classmethod
    def _validate_required_fields(cls, values: list[str]) -> list[str]:
        for value in values:
            if not value.strip():
                raise ValueError("required_fields must not contain empty values")
        return values


class PrerequisiteContract(BaseContractDocument):
    """Contract for external state or local preparation required before a run."""

    kind: Literal["prerequisite"]
    credential_contract_ids: list[str]

    @field_validator("credential_contract_ids")
    @classmethod
    def _validate_credential_ids(cls, values: list[str]) -> list[str]:
        return [validate_contract_id(value) for value in values]


Contract = CredentialContract | PrerequisiteContract


def load_contract(path: Path) -> Contract:
    """Load and strictly validate one contract YAML file."""
    try:
        document = frontmatter.load(str(path))
    except OSError as exc:
        raise PrerequisiteContractReadError(
            PrerequisiteErrorDetail(
                code="PREREQUISITE_CONTRACT_READ_ERROR",
                message=f"Failed to read contract: {exc}",
                path=str(path),
            )
        ) from exc
    except Exception as exc:  # noqa: BLE001
        raise PrerequisiteContractReadError(
            PrerequisiteErrorDetail(
                code="PREREQUISITE_CONTRACT_READ_ERROR",
                message=f"Failed to parse contract frontmatter: {exc}",
                path=str(path),
            )
        ) from exc

    metadata = dict(document.metadata)
    kind = metadata.get("kind")
    if kind not in {"credential", "prerequisite"}:
        raise PrerequisiteContractSchemaError(
            PrerequisiteErrorDetail(
                code="PREREQUISITE_CONTRACT_SCHEMA_ERROR",
                message="Contract kind must be 'credential' or 'prerequisite'",
                path=str(path),
            )
        )

    model = CredentialContract if kind == "credential" else PrerequisiteContract
    try:
        contract = model.model_validate(metadata)
    except ValidationError as exc:
        raise PrerequisiteContractSchemaError(
            PrerequisiteErrorDetail(
                code="PREREQUISITE_CONTRACT_SCHEMA_ERROR",
                message=f"Contract schema validation failed: {exc.errors()[0]['msg']}",
                contract_id=str(metadata.get("id") or ""),
                path=str(path),
            )
        ) from exc

    expected_id = path.stem
    if contract.id != expected_id:
        raise PrerequisiteContractSchemaError(
            PrerequisiteErrorDetail(
                code="PREREQUISITE_CONTRACT_SCHEMA_ERROR",
                message="Contract id does not match file name",
                contract_id=contract.id,
                path=str(path),
            )
        )
    return contract


def load_all_contracts(testenv_root: Path) -> dict[str, Contract]:
    """Load every YAML contract under contracts/."""
    loaded: dict[str, Contract] = {}
    for path in sorted(contracts_root(testenv_root).glob("*.yaml")):
        if path.name == "README.md":
            continue
        contract = load_contract(path)
        loaded[contract.id] = contract
    return loaded


def dump_contract_metadata(contract: Contract) -> Mapping[str, object]:
    """Return snapshot-safe metadata for a contract."""
    metadata: dict[str, object] = {
        "schema_version": CONTRACT_SCHEMA_VERSION,
        "id": contract.id,
        "kind": contract.kind,
        "source": contract.source,
        "secret_fields": sorted(contract.secret_fields),
        "checks": [
            {
                "id": check.id,
                "mode": check.mode,
                "target": check.target,
                "description": check.description,
            }
            for check in contract.checks
        ],
    }
    if isinstance(contract, CredentialContract):
        metadata["required_fields"] = sorted(contract.required_fields)
    else:
        metadata["credential_contract_ids"] = sorted(contract.credential_contract_ids)
    return metadata
