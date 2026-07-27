"""Simplify Runtime policy to complete Docker authority and enforceable limits."""

import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "6c42043df81f"
down_revision: str | Sequence[str] | None = "17a0f533cc20"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_DEFAULT_DOCKER_STORAGE_CAPACITY_BYTES = 16 * 1024**3


def upgrade() -> None:
    """Replace granular Docker and unenforceable nested-workload policy fields."""
    connection = op.get_bind()
    for table, key, document_column in (
        ("runtime_execution_profiles", "id", "policy"),
        ("workspace_runtime_execution_policies", "workspace_id", "restriction"),
        ("agent_runtime_execution_settings", "agent_id", "restriction"),
    ):
        rows = connection.execute(
            sa.text(f"SELECT {key}, {document_column} FROM {table}")
        ).mappings()
        for row in rows:
            document = row[document_column]
            if not isinstance(document, Mapping):
                continue
            transformed = _transform_policy(document)
            connection.execute(
                sa.text(
                    f"UPDATE {table} SET {document_column} = :document, "
                    f"digest = :digest WHERE {key} = :key"
                ).bindparams(
                    sa.bindparam("document", type_=postgresql.JSONB),
                    sa.bindparam("digest", type_=sa.String()),
                    sa.bindparam("key", type_=sa.String()),
                ),
                {
                    "document": transformed,
                    "digest": _digest(transformed),
                    "key": row[key],
                },
            )

    snapshots = connection.execute(
        sa.text(
            "SELECT id, resolved_execution_policy_json "
            "FROM runtime_policy_snapshots "
            "WHERE resolved_execution_policy_json IS NOT NULL"
        )
    ).mappings()
    transformed_snapshot_ids: list[str] = []
    for row in snapshots:
        document = json.loads(row["resolved_execution_policy_json"])
        if not isinstance(document, Mapping):
            continue
        transformed = _transform_policy(document)
        transformed_snapshot_ids.append(row["id"])
        connection.execute(
            sa.text(
                "UPDATE runtime_policy_snapshots SET "
                "resolved_execution_policy_json = :document, "
                "execution_target_digest = :digest, "
                "execution_reported_digest = NULL, "
                "execution_source_trace = NULL, "
                "execution_provider_compatibility = NULL, "
                "application_state = 'pending', "
                "provider_acknowledged_at = NULL "
                "WHERE id = :id"
            ),
            {
                "document": _canonical_json(transformed),
                "digest": _digest(transformed),
                "id": row["id"],
            },
        )
    if transformed_snapshot_ids:
        connection.execute(
            sa.text(
                "UPDATE agent_runtimes SET applied_runtime_policy_snapshot_id = NULL "
                "WHERE applied_runtime_policy_snapshot_id = ANY(:snapshot_ids)"
            ).bindparams(
                sa.bindparam(
                    "snapshot_ids",
                    type_=postgresql.ARRAY(sa.String()),
                )
            ),
            {"snapshot_ids": transformed_snapshot_ids},
        )


def downgrade() -> None:
    """Leave migrated v1 documents intact because the removed shape is lossy."""


def _canonical_json(document: Mapping[str, Any]) -> str:
    return json.dumps(
        document,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def _digest(document: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(document).encode()).hexdigest()


def _transform_policy(document: Mapping[str, Any]) -> dict[str, Any]:
    if "docker" in document:
        return dict(document)
    resources = document.get("resources")
    full_policy = isinstance(resources, Mapping) and "module_id" in resources
    return (
        _transform_full_policy(document)
        if full_policy
        else _transform_restriction(document)
    )


def _transform_full_policy(document: Mapping[str, Any]) -> dict[str, Any]:
    resources = _mapping(document.get("resources"))
    storage = _mapping(document.get("engine_storage"))
    docker_enabled = any(
        _mapping(document.get(field)).get("enabled") is True
        for field in ("image_build", "container_run", "compose")
    )
    storage_mode = storage.get("mode")
    storage_capacity = storage.get("capacity_bytes")
    if docker_enabled:
        if storage_mode not in {"ephemeral", "persistent"}:
            storage_mode = "ephemeral"
        if (
            not isinstance(storage_capacity, int)
            or isinstance(storage_capacity, bool)
            or storage_capacity < 1
        ):
            storage_capacity = _DEFAULT_DOCKER_STORAGE_CAPACITY_BYTES
    else:
        storage_mode = "none"
        storage_capacity = None
    return {
        "schema_version": 1,
        "docker": {
            "module_id": "docker",
            "version": 1,
            "enabled": docker_enabled,
            "storage_mode": storage_mode,
            "storage_capacity_bytes": storage_capacity,
        },
        "resources": {
            "module_id": "runtime.resources",
            "version": 1,
            **_resource_values(resources),
        },
    }


def _transform_restriction(document: Mapping[str, Any]) -> dict[str, Any]:
    storage_value = document.get("engine_storage")
    storage = _mapping(storage_value)
    disables_docker = storage.get("mode") == "none" or any(
        document.get(field) is not None
        for field in ("image_build", "container_run", "compose")
    )
    docker = None
    if disables_docker:
        docker = {
            "enabled": False,
            "storage_mode": None,
            "storage_capacity_bytes": None,
        }
    elif isinstance(storage_value, Mapping):
        docker = {
            "enabled": None,
            "storage_mode": storage.get("mode"),
            "storage_capacity_bytes": storage.get("capacity_bytes"),
        }
    resources_value = document.get("resources")
    resources = (
        _resource_values(_mapping(resources_value))
        if isinstance(resources_value, Mapping)
        else None
    )
    return {
        "schema_version": 1,
        "docker": docker,
        "resources": resources,
    }


def _resource_values(resources: Mapping[str, Any]) -> dict[str, Any]:
    return {
        field: resources.get(field)
        for field in (
            "cpu_request_millicores",
            "cpu_limit_millicores",
            "memory_request_bytes",
            "memory_limit_bytes",
            "ephemeral_storage_bytes",
            "persistent_storage_bytes",
        )
    }


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}
