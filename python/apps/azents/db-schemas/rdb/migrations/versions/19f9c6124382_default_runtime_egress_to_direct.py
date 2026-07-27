"""Default Runtime egress to direct."""

import json
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "19f9c6124382"
down_revision: str | Sequence[str] | None = "f18c05d9d547"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD_STANDARD_DIGEST = (
    "277fff74ee7d60ad1f0f26ac30635d6fb6a0844dcf6d89787afa090fbd092c3f"
)
_DIRECT_STANDARD_DIGEST = (
    "bb0f40cfa69fb1e1567069f725ef6928090d2aa32c054249feb02e0bf8415f17"
)


def _standard_policy(network_mode: str) -> dict[str, object]:
    return {
        "schema_version": 1,
        "image_build": {
            "module_id": "container.image_build",
            "version": 1,
            "enabled": False,
        },
        "container_run": {
            "module_id": "container.run",
            "version": 1,
            "enabled": False,
        },
        "compose": {
            "module_id": "container.compose",
            "version": 1,
            "enabled": False,
        },
        "resources": {
            "module_id": "container.resources",
            "version": 1,
            "cpu_millicores": None,
            "memory_bytes": None,
            "pids": None,
            "container_count": None,
            "ephemeral_storage_bytes": None,
        },
        "engine_storage": {
            "module_id": "engine.storage",
            "version": 1,
            "mode": "none",
            "capacity_bytes": None,
        },
        "network_egress": {
            "module_id": "network.egress",
            "version": 1,
            "mode": network_mode,
            "allowed_destinations": [],
            "denied_destinations": [],
        },
    }


_OLD_STANDARD_POLICY = _standard_policy("none")
_DIRECT_STANDARD_POLICY = _standard_policy("direct")


def _replace_untouched_defaults(
    *,
    source_policy: dict[str, object],
    source_digest: str,
    target_policy: dict[str, object],
    target_digest: str,
    source_version: int,
) -> None:
    target_policy_json = json.dumps(
        target_policy,
        sort_keys=True,
        separators=(",", ":"),
    )
    source_policy_json = json.dumps(
        source_policy,
        sort_keys=True,
        separators=(",", ":"),
    )
    op.execute(
        sa.text(
            """
            UPDATE runtime_execution_platform_policies
            SET
                version = version + 1,
                policy = CAST(:target_policy AS jsonb),
                digest = :target_digest,
                updated_at = now()
            WHERE id = 'platform'
              AND version = :source_version
              AND updated_by_user_id IS NULL
              AND digest = :source_digest
              AND policy = CAST(:source_policy AS jsonb)
            """
        ).bindparams(
            sa.bindparam(
                "source_policy",
                value=source_policy_json,
                type_=sa.String(),
                literal_execute=True,
            ),
            sa.bindparam(
                "target_policy",
                value=target_policy_json,
                type_=sa.String(),
                literal_execute=True,
            ),
            sa.bindparam(
                "source_digest",
                value=source_digest,
                type_=sa.String(),
                literal_execute=True,
            ),
            sa.bindparam(
                "target_digest",
                value=target_digest,
                type_=sa.String(),
                literal_execute=True,
            ),
            sa.bindparam(
                "source_version",
                value=source_version,
                type_=sa.Integer(),
                literal_execute=True,
            ),
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE runtime_execution_profiles
            SET
                version = version + 1,
                policy = CAST(:target_policy AS jsonb),
                digest = :target_digest,
                updated_at = now()
            WHERE id = 'system-standard'
              AND system_key = 'system-standard'
              AND reserved IS TRUE
              AND version = :source_version
              AND updated_by_user_id IS NULL
              AND digest = :source_digest
              AND policy = CAST(:source_policy AS jsonb)
            """
        ).bindparams(
            sa.bindparam(
                "source_policy",
                value=source_policy_json,
                type_=sa.String(),
                literal_execute=True,
            ),
            sa.bindparam(
                "target_policy",
                value=target_policy_json,
                type_=sa.String(),
                literal_execute=True,
            ),
            sa.bindparam(
                "source_digest",
                value=source_digest,
                type_=sa.String(),
                literal_execute=True,
            ),
            sa.bindparam(
                "target_digest",
                value=target_digest,
                type_=sa.String(),
                literal_execute=True,
            ),
            sa.bindparam(
                "source_version",
                value=source_version,
                type_=sa.Integer(),
                literal_execute=True,
            ),
        )
    )


def upgrade() -> None:
    """Permit direct outbound networking for untouched default policies."""
    _replace_untouched_defaults(
        source_policy=_OLD_STANDARD_POLICY,
        source_digest=_OLD_STANDARD_DIGEST,
        target_policy=_DIRECT_STANDARD_POLICY,
        target_digest=_DIRECT_STANDARD_DIGEST,
        source_version=1,
    )


def downgrade() -> None:
    """Restore the previous untouched default policies."""
    _replace_untouched_defaults(
        source_policy=_DIRECT_STANDARD_POLICY,
        source_digest=_DIRECT_STANDARD_DIGEST,
        target_policy=_OLD_STANDARD_POLICY,
        target_digest=_OLD_STANDARD_DIGEST,
        source_version=2,
    )
