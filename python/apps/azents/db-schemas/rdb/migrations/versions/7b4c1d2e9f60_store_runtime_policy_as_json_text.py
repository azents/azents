"""Normalize Runtime policy v1 and store snapshots as canonical JSON text."""

import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "7b4c1d2e9f60"
down_revision: str | Sequence[str] | None = "142ffe7ca6e9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _canonical_json(document: Mapping[str, Any]) -> str:
    return json.dumps(
        document,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def _digest(document: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(document).encode()).hexdigest()


def _set_resource_module_version(
    document: Mapping[str, Any],
    *,
    version: int,
) -> dict[str, Any]:
    """Normalize the unreleased resource module without a compatibility branch."""
    normalized = dict(document)
    resources = normalized.get("resources")
    if isinstance(resources, Mapping) and (
        resources.get("module_id") == "container.resources"
    ):
        normalized["resources"] = {**resources, "version": version}
    return normalized


def _rewrite_policy_documents(*, version: int) -> None:
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
            normalized = _set_resource_module_version(document, version=version)
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
                    "document": normalized,
                    "digest": _digest(normalized),
                    "key": row[key],
                },
            )

    snapshots = connection.execute(
        sa.text(
            "SELECT id, resolved_execution_policy FROM runtime_policy_snapshots "
            "WHERE jsonb_typeof(resolved_execution_policy) = 'object'"
        )
    ).mappings()
    for row in snapshots:
        document = row["resolved_execution_policy"]
        if not isinstance(document, Mapping):
            continue
        normalized = _set_resource_module_version(document, version=version)
        connection.execute(
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
                "document": normalized,
                "digest": _digest(normalized),
                "id": row["id"],
            },
        )


def upgrade() -> None:
    """Normalize unreleased policy v1 and replace snapshot Struct-shaped JSONB."""
    _rewrite_policy_documents(version=1)
    op.execute(
        sa.text(
            "DELETE FROM runtime_provider_contract_revisions AS stale "
            "WHERE stale.accepted_at IS NULL AND EXISTS ("
            "SELECT 1 FROM runtime_provider_contract_revisions AS newer "
            "WHERE newer.provider_id = stale.provider_id AND ("
            "newer.created_at > stale.created_at OR ("
            "newer.created_at = stale.created_at AND newer.id > stale.id"
            ")"
            ")"
            ")"
        )
    )
    op.drop_constraint(
        "uq_runtime_provider_contract_revisions_provider_digest",
        "runtime_provider_contract_revisions",
        type_="unique",
    )
    op.alter_column(
        "runtime_policy_snapshots",
        "resolved_execution_policy",
        existing_type=postgresql.JSONB(astext_type=sa.Text()),
        type_=sa.Text(),
        new_column_name="resolved_execution_policy_json",
        existing_nullable=True,
        postgresql_using=(
            "CASE "
            "WHEN jsonb_typeof(resolved_execution_policy) = 'object' "
            "THEN resolved_execution_policy::text "
            "ELSE NULL END"
        ),
    )
    connection = op.get_bind()
    rows = connection.execute(
        sa.text(
            "SELECT id, resolved_execution_policy_json "
            "FROM runtime_policy_snapshots "
            "WHERE resolved_execution_policy_json IS NOT NULL"
        )
    ).mappings()
    for row in rows:
        document = json.loads(row["resolved_execution_policy_json"])
        if not isinstance(document, dict):
            raise ValueError("Resolved Runtime execution policy must be an object.")
        connection.execute(
            sa.text(
                "UPDATE runtime_policy_snapshots "
                "SET resolved_execution_policy_json = :document "
                "WHERE id = :id"
            ),
            {
                "id": row["id"],
                "document": _canonical_json(document),
            },
        )


def downgrade() -> None:
    """Restore JSONB snapshots while keeping the unreleased policy on v1."""
    op.alter_column(
        "runtime_policy_snapshots",
        "resolved_execution_policy_json",
        existing_type=sa.Text(),
        type_=postgresql.JSONB(astext_type=sa.Text()),
        new_column_name="resolved_execution_policy",
        existing_nullable=True,
        postgresql_using="resolved_execution_policy_json::jsonb",
    )
