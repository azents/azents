"""Upgrade Runtime resource policies."""

import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "142ffe7ca6e9"
down_revision: str | Sequence[str] | None = "e0615474dc27"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _digest(document: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        document,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _upgrade_resources(resources: Mapping[str, Any]) -> dict[str, Any]:
    upgraded = dict(resources)
    cpu_limit = upgraded.pop("cpu_millicores", None)
    memory_limit = upgraded.pop("memory_bytes", None)
    if upgraded.get("module_id") == "container.resources":
        upgraded["version"] = 2
    upgraded.update(
        {
            "cpu_request_millicores": None,
            "cpu_limit_millicores": cpu_limit,
            "memory_request_bytes": None,
            "memory_limit_bytes": memory_limit,
            "persistent_storage_bytes": None,
        }
    )
    return upgraded


def _downgrade_resources(resources: Mapping[str, Any]) -> dict[str, Any]:
    downgraded = dict(resources)
    cpu_limit = downgraded.pop("cpu_limit_millicores", None)
    cpu_request = downgraded.pop("cpu_request_millicores", None)
    memory_limit = downgraded.pop("memory_limit_bytes", None)
    memory_request = downgraded.pop("memory_request_bytes", None)
    downgraded.pop("persistent_storage_bytes", None)
    if downgraded.get("module_id") == "container.resources":
        downgraded["version"] = 1
    downgraded.update(
        {
            "cpu_millicores": cpu_limit if cpu_limit is not None else cpu_request,
            "memory_bytes": (
                memory_limit if memory_limit is not None else memory_request
            ),
        }
    )
    return downgraded


def _transform_document(
    document: Mapping[str, Any],
    transform: Callable[[Mapping[str, Any]], dict[str, Any]],
) -> dict[str, Any]:
    transformed = dict(document)
    resources = transformed.get("resources")
    if isinstance(resources, dict):
        transformed["resources"] = transform(resources)
    return transformed


def _transform_optional_document(
    document: object,
    transform: Callable[[Mapping[str, Any]], dict[str, Any]],
) -> dict[str, Any] | None:
    """Transform JSON policy objects while preserving JSON null snapshots."""
    if not isinstance(document, Mapping):
        return None
    return _transform_document(document, transform)


def _transform_current_documents(
    *,
    table: str,
    key: str,
    document_column: str,
    transform: Callable[[Mapping[str, Any]], dict[str, Any]],
) -> None:
    bind = op.get_bind()
    rows = bind.execute(
        sa.text(f"SELECT {key}, {document_column} FROM {table}")
    ).mappings()
    for row in rows:
        document = _transform_document(row[document_column], transform)
        bind.execute(
            sa.text(
                f"UPDATE {table} SET {document_column} = :document, "
                "digest = :digest WHERE "
                f"{key} = :key"
            ).bindparams(
                sa.bindparam("document", type_=postgresql.JSONB),
                sa.bindparam("digest", type_=sa.String()),
                sa.bindparam("key", type_=sa.String()),
            ),
            {
                "document": document,
                "digest": _digest(document),
                "key": row[key],
            },
        )


def _transform_snapshots(
    transform: Callable[[Mapping[str, Any]], dict[str, Any]],
) -> None:
    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            "SELECT id, resolved_execution_policy FROM runtime_policy_snapshots "
            "WHERE jsonb_typeof(resolved_execution_policy) = 'object'"
        )
    ).mappings()
    for row in rows:
        document = _transform_optional_document(
            row["resolved_execution_policy"], transform
        )
        if document is None:
            continue
        bind.execute(
            sa.text(
                "UPDATE runtime_policy_snapshots SET "
                "resolved_execution_policy = :document, "
                "execution_target_digest = :digest, "
                "execution_reported_digest = NULL, "
                "application_state = 'pending', "
                "provider_acknowledged_at = NULL "
                "WHERE id = :id"
            ).bindparams(
                sa.bindparam("document", type_=postgresql.JSONB),
                sa.bindparam("digest", type_=sa.String()),
                sa.bindparam("id", type_=sa.String()),
            ),
            {
                "document": document,
                "digest": _digest(document),
                "id": row["id"],
            },
        )


def _transform_all(
    transform: Callable[[Mapping[str, Any]], dict[str, Any]],
) -> None:
    _transform_current_documents(
        table="runtime_execution_profiles",
        key="id",
        document_column="policy",
        transform=transform,
    )
    _transform_current_documents(
        table="workspace_runtime_execution_policies",
        key="workspace_id",
        document_column="restriction",
        transform=transform,
    )
    _transform_current_documents(
        table="agent_runtime_execution_settings",
        key="agent_id",
        document_column="restriction",
        transform=transform,
    )
    _transform_snapshots(transform)


def upgrade() -> None:
    """Add Kubernetes requests and persistent workspace storage."""
    _transform_all(_upgrade_resources)


def downgrade() -> None:
    """Collapse Kubernetes requests and limits into legacy limits."""
    _transform_all(_downgrade_resources)
