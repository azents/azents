from typing import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a0dac2fe3ca2"
down_revision: str | Sequence[str] | None = "af654664e6b6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_RECONCILE_SQL = """
DO $$
DECLARE
    relation RECORD;
    allocated_ordinal BIGINT;
    allocated_namespace VARCHAR(128);
BEGIN
    FOR relation IN
        SELECT effective.*
        FROM (
            SELECT
                agent_toolkits.agent_id,
                toolkit_configs.id AS toolkit_id,
                toolkit_configs.slug AS base_slug,
                0 AS source_order,
                agent_toolkits.created_at AS effective_created_at
            FROM agent_toolkits
            JOIN toolkit_configs
                ON toolkit_configs.id = agent_toolkits.toolkit_id
            WHERE toolkit_configs.owner_agent_id IS NULL

            UNION ALL

            SELECT
                toolkit_configs.owner_agent_id AS agent_id,
                toolkit_configs.id AS toolkit_id,
                toolkit_configs.slug AS base_slug,
                1 AS source_order,
                toolkit_configs.created_at AS effective_created_at
            FROM toolkit_configs
            WHERE toolkit_configs.owner_agent_id IS NOT NULL
        ) AS effective
        LEFT JOIN agent_toolkit_namespace_reservations AS active
            ON active.agent_id = effective.agent_id
           AND active.toolkit_id = effective.toolkit_id
        WHERE active.id IS NULL
           OR active.base_slug != effective.base_slug
        ORDER BY
            effective.agent_id,
            effective.source_order,
            effective.effective_created_at,
            effective.toolkit_id
    LOOP
        UPDATE agent_toolkit_namespace_reservations AS stale
        SET toolkit_id = NULL
        WHERE stale.agent_id = relation.agent_id
          AND stale.toolkit_id = relation.toolkit_id
          AND stale.base_slug != relation.base_slug;

        SELECT sequences.last_ordinal
        INTO allocated_ordinal
        FROM agent_toolkit_namespace_sequences AS sequences
        WHERE sequences.agent_id = relation.agent_id
          AND sequences.base_slug = relation.base_slug;

        allocated_ordinal := COALESCE(allocated_ordinal, 0) + 1;
        LOOP
            allocated_namespace := CASE
                WHEN allocated_ordinal = 1 THEN relation.base_slug
                ELSE relation.base_slug || '_' || allocated_ordinal
            END;
            EXIT WHEN NOT EXISTS (
                SELECT 1
                FROM agent_toolkit_namespace_reservations AS reservations
                WHERE reservations.agent_id = relation.agent_id
                  AND reservations.namespace = allocated_namespace
            );
            allocated_ordinal := allocated_ordinal + 1;
        END LOOP;

        INSERT INTO agent_toolkit_namespace_reservations (
            id,
            agent_id,
            toolkit_id,
            base_slug,
            ordinal,
            namespace
        )
        VALUES (
            md5(
                'toolkit-namespace-reconcile:'
                || relation.agent_id
                || ':'
                || relation.toolkit_id
                || ':'
                || relation.base_slug
                || ':'
                || allocated_ordinal
            ),
            relation.agent_id,
            relation.toolkit_id,
            relation.base_slug,
            allocated_ordinal,
            allocated_namespace
        );

        INSERT INTO agent_toolkit_namespace_sequences (
            id,
            agent_id,
            base_slug,
            last_ordinal
        )
        VALUES (
            md5(
                'toolkit-namespace-sequence:'
                || relation.agent_id
                || ':'
                || relation.base_slug
            ),
            relation.agent_id,
            relation.base_slug,
            allocated_ordinal
        )
        ON CONFLICT (agent_id, base_slug)
        DO UPDATE SET
            last_ordinal = EXCLUDED.last_ordinal,
            updated_at = now();
    END LOOP;
END
$$;
"""


def upgrade() -> None:
    """Reconcile relations written during the Foundation rolling deployment."""
    op.execute(_RECONCILE_SQL)


def downgrade() -> None:
    """Retain valid namespace reservations when returning to Foundation persistence."""
