"""Separate semantic catalog identity from execution descriptors."""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "4550a9c9083a"
down_revision: str | Sequence[str] | None = "43a0fbdc96fe"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Preserve catalog state while removing executable identity dimensions."""
    connection = op.get_bind()
    # Keep preflight and DDL under one stable catalog view, including writers
    # that have not yet acquired the deployment's migration advisory lock.
    connection.execute(
        sa.text("LOCK TABLE llm_catalogs, llm_catalog_entries IN ACCESS EXCLUSIVE MODE")
    )
    collisions: list[str] = []
    for scope, identity in (
        ("system", "provider, purpose"),
        ("integration", "provider_integration_id, purpose"),
    ):
        rows = connection.execute(
            sa.text(
                f"SELECT {identity}, COUNT(*) AS catalogs FROM llm_catalogs "
                f"WHERE scope = '{scope}' GROUP BY {identity} "
                f"HAVING COUNT(*) > 1 ORDER BY {identity} LIMIT 5"
            )
        ).all()
        collisions.extend(
            f"{scope}({row[0]}, {row[1]}): {row[2]} catalogs" for row in rows
        )
    if collisions:
        raise RuntimeError(
            "Catalog execution-descriptor removal blocked by semantic identity "
            "collisions; no catalogs were merged or deleted: " + "; ".join(collisions)
        )

    op.drop_index(
        "uq_llm_catalogs_system_scope_provider_target_purpose", "llm_catalogs"
    )
    op.drop_index("uq_llm_catalogs_integration_target_purpose", "llm_catalogs")
    op.create_index(
        "uq_llm_catalogs_system_scope_provider_purpose",
        "llm_catalogs",
        ["provider", "purpose"],
        unique=True,
        postgresql_where=sa.text("scope = 'system'"),
    )
    op.create_index(
        "uq_llm_catalogs_integration_purpose",
        "llm_catalogs",
        ["provider_integration_id", "purpose"],
        unique=True,
        postgresql_where=sa.text("scope = 'integration'"),
    )
    # Only active, adapter-owned conversation projection metadata is mutable.
    # Historical projections, selections, source payloads and native artifacts
    # remain evidence; nested similarly named keys are not execution fields.
    connection.execute(
        sa.text(
            "UPDATE llm_catalog_entries AS entry "
            "SET projection_metadata = entry.projection_metadata "
            "- 'lowerer_target' - 'runtime_model_identifier' "
            "FROM llm_catalogs AS catalog "
            "WHERE entry.catalog_id = catalog.id "
            "AND entry.snapshot_id = catalog.current_snapshot_id "
            "AND catalog.purpose = 'conversation' "
            "AND jsonb_typeof(entry.projection_metadata) = 'object' "
            "AND entry.projection_metadata ?| "
            "ARRAY['lowerer_target', 'runtime_model_identifier']"
        )
    )
    op.drop_column("llm_catalog_entries", "runtime_model_identifier")
    op.drop_column("llm_catalog_entries", "lowerer_target")
    op.drop_column("llm_catalogs", "lowerer_target")
    op.execute(sa.text("DROP TYPE llm_catalog_lowerer_target"))


def downgrade() -> None:
    """Require a forward fix or coordinated database/application restoration."""
    raise RuntimeError(
        "Catalog execution descriptor removal is irreversible; use a forward fix "
        "or coordinated compatible database/application restoration."
    )
