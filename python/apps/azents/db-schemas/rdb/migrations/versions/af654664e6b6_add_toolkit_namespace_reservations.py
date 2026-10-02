from typing import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "af654664e6b6"
down_revision: str | Sequence[str] | None = "d29225579621"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "agent_toolkit_namespace_sequences",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("agent_id", sa.String(length=32), nullable=False),
        sa.Column("base_slug", sa.String(length=100), nullable=False),
        sa.Column(
            "last_ordinal",
            sa.BigInteger(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["agent_id"],
            ["agents.id"],
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "last_ordinal >= 0",
            name="ck_agent_toolkit_namespace_sequences_last_ordinal_nonnegative",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "agent_id",
            "base_slug",
            name="uq_agent_toolkit_namespace_sequences_agent_base",
        ),
    )
    op.create_table(
        "agent_toolkit_namespace_reservations",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("agent_id", sa.String(length=32), nullable=False),
        sa.Column("toolkit_id", sa.String(length=32), nullable=True),
        sa.Column("base_slug", sa.String(length=100), nullable=False),
        sa.Column("ordinal", sa.BigInteger(), nullable=False),
        sa.Column("namespace", sa.String(length=128), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["agent_id"],
            ["agents.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["toolkit_id"],
            ["toolkit_configs.id"],
            ondelete="SET NULL",
        ),
        sa.CheckConstraint(
            "ordinal >= 1",
            name="ck_agent_toolkit_namespace_reservations_ordinal_positive",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "agent_id",
            "base_slug",
            "ordinal",
            name="uq_agent_toolkit_namespace_reservations_agent_base_ordinal",
        ),
        sa.UniqueConstraint(
            "agent_id",
            "namespace",
            name="uq_agent_toolkit_namespace_reservations_agent_namespace",
        ),
    )
    op.create_index(
        "ix_agent_toolkit_namespace_reservations_toolkit_id",
        "agent_toolkit_namespace_reservations",
        ["toolkit_id"],
        unique=False,
    )
    op.create_index(
        "uq_agent_toolkit_namespace_reservations_active_agent_toolkit",
        "agent_toolkit_namespace_reservations",
        ["agent_id", "toolkit_id"],
        unique=True,
        postgresql_where=sa.text("toolkit_id IS NOT NULL"),
    )
    op.execute(
        """
        DO $$
        DECLARE
            relation RECORD;
            allocated_ordinal BIGINT;
            allocated_namespace VARCHAR(128);
        BEGIN
            FOR relation IN
                SELECT *
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
                ORDER BY
                    effective.agent_id,
                    effective.source_order,
                    effective.effective_created_at,
                    effective.toolkit_id
            LOOP
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
                        'toolkit-namespace-reservation:'
                        || relation.agent_id
                        || ':'
                        || relation.toolkit_id
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
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        "uq_agent_toolkit_namespace_reservations_active_agent_toolkit",
        table_name="agent_toolkit_namespace_reservations",
        postgresql_where=sa.text("toolkit_id IS NOT NULL"),
    )
    op.drop_index(
        "ix_agent_toolkit_namespace_reservations_toolkit_id",
        table_name="agent_toolkit_namespace_reservations",
    )
    op.drop_table("agent_toolkit_namespace_reservations")
    op.drop_table("agent_toolkit_namespace_sequences")
