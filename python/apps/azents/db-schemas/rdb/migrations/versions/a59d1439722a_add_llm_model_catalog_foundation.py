"""add llm model catalog foundation"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "a59d1439722a"
down_revision: str | Sequence[str] | None = "40c351dfc8d7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


llm_model_lifecycle_status = postgresql.ENUM(
    "active",
    "deprecated",
    "removed_from_source",
    "local_only",
    "disabled",
    name="llm_model_lifecycle_status",
)
llm_catalog_source_type = postgresql.ENUM(
    "external_catalog",
    "provider_adapter",
    "local_override",
    name="llm_catalog_source_type",
)
llm_catalog_source_status = postgresql.ENUM(
    "active",
    "failed",
    "disabled",
    "unknown",
    name="llm_catalog_source_status",
)


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()
    llm_model_lifecycle_status.create(bind, checkfirst=True)
    llm_catalog_source_type.create(bind, checkfirst=True)
    llm_catalog_source_status.create(bind, checkfirst=True)

    op.create_table(
        "llm_catalog_sources",
        sa.Column("key", sa.String(length=255), nullable=False),
        sa.Column(
            "type",
            postgresql.ENUM(
                "external_catalog",
                "provider_adapter",
                "local_override",
                name="llm_catalog_source_type",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column(
            "status",
            postgresql.ENUM(
                "active",
                "failed",
                "disabled",
                "unknown",
                name="llm_catalog_source_status",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("version", sa.String(length=255), nullable=True),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "raw_summary", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("key"),
    )
    op.create_index(
        "ix_llm_catalog_sources_last_success_at",
        "llm_catalog_sources",
        ["last_success_at"],
        unique=False,
    )
    op.create_index(
        "ix_llm_catalog_sources_status",
        "llm_catalog_sources",
        ["status"],
        unique=False,
    )

    op.create_table(
        "llm_model_overrides",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column(
            "provider",
            postgresql.ENUM(name="llm_provider", create_type=False),
            nullable=False,
        ),
        sa.Column("model_identifier", sa.String(length=255), nullable=False),
        sa.Column("override", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("updated_by", sa.String(length=255), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "provider",
            "model_identifier",
            name="uq_llm_model_overrides_provider_model_identifier",
        ),
    )
    op.create_index(
        "ix_llm_model_overrides_expires_at",
        "llm_model_overrides",
        ["expires_at"],
        unique=False,
    )

    op.add_column(
        "llm_models", sa.Column("source_key", sa.String(length=255), nullable=True)
    )
    op.add_column(
        "llm_models", sa.Column("source_model_id", sa.String(length=255), nullable=True)
    )
    op.create_index(
        "ix_llm_models_source_key", "llm_models", ["source_key"], unique=False
    )
    op.create_foreign_key(
        "fk_llm_models_source_key_llm_catalog_sources",
        "llm_models",
        "llm_catalog_sources",
        ["source_key"],
        ["key"],
        ondelete="RESTRICT",
    )

    op.add_column(
        "llm_provider_models",
        sa.Column(
            "lifecycle_status",
            postgresql.ENUM(
                "active",
                "deprecated",
                "removed_from_source",
                "local_only",
                "disabled",
                name="llm_model_lifecycle_status",
                create_type=False,
            ),
            nullable=True,
        ),
    )
    op.add_column(
        "llm_provider_models",
        sa.Column(
            "capabilities", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
    )
    op.add_column(
        "llm_provider_models",
        sa.Column(
            "raw_source_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )
    op.add_column(
        "llm_provider_models",
        sa.Column("source_key", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "llm_provider_models",
        sa.Column("source_record_id", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "llm_provider_models",
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.execute(
        sa.text(
            """
            UPDATE llm_provider_models
            SET
                lifecycle_status = 'active'::llm_model_lifecycle_status,
                capabilities = jsonb_build_object(
                    'context_window', jsonb_build_object(
                        'max_input_tokens', CASE
                            WHEN metadata ? 'max_input_tokens'
                                 AND jsonb_typeof(
                                     metadata -> 'max_input_tokens'
                                 ) = 'number'
                                 AND (metadata ->> 'max_input_tokens') ~ '^[1-9][0-9]*$'
                            THEN to_jsonb((metadata ->> 'max_input_tokens')::integer)
                            ELSE 'null'::jsonb
                        END,
                        'max_output_tokens', 'null'::jsonb
                    ),
                    'modalities', jsonb_build_object(
                        'input', '[]'::jsonb,
                        'output', '[]'::jsonb
                    ),
                    'tool_calling', jsonb_build_object(
                        'supported', false,
                        'parallel_tool_calls', 'null'::jsonb,
                        'strict_json_schema', 'null'::jsonb
                    ),
                    'reasoning', jsonb_build_object(
                        'supported', thinking,
                        'effort_levels', '[]'::jsonb,
                        'summaries', 'null'::jsonb
                    ),
                    'built_in_tools', jsonb_build_object(
                        'supported', COALESCE((
                            SELECT jsonb_agg(tool_id ORDER BY tool_id)
                            FROM jsonb_array_elements_text(
                                CASE
                                    WHEN jsonb_typeof(
                                        metadata -> 'supported_builtin_tools'
                                    ) = 'array'
                                    THEN metadata -> 'supported_builtin_tools'
                                    ELSE '[]'::jsonb
                                END
                            ) AS tool_id
                            WHERE tool_id IN (
                                  'web_search',
                                  'web_fetch',
                                  'image_generation'
                              )
                        ), '[]'::jsonb)
                    ),
                    'compatibility', jsonb_build_object(
                        'provider_family', 'null'::jsonb,
                        'responses_api', 'null'::jsonb,
                        'unsupported_media_policy', 'null'::jsonb
                    )
                )
            """
        )
    )
    op.alter_column("llm_provider_models", "lifecycle_status", nullable=False)
    op.alter_column("llm_provider_models", "capabilities", nullable=False)
    op.create_index(
        "ix_llm_provider_models_last_synced_at",
        "llm_provider_models",
        ["last_synced_at"],
        unique=False,
    )
    op.create_index(
        "ix_llm_provider_models_lifecycle_status",
        "llm_provider_models",
        ["lifecycle_status"],
        unique=False,
    )
    op.create_index(
        "ix_llm_provider_models_source_key",
        "llm_provider_models",
        ["source_key"],
        unique=False,
    )
    op.create_foreign_key(
        "fk_llm_provider_models_source_key_llm_catalog_sources",
        "llm_provider_models",
        "llm_catalog_sources",
        ["source_key"],
        ["key"],
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(
        "fk_llm_provider_models_source_key_llm_catalog_sources",
        "llm_provider_models",
        type_="foreignkey",
    )
    op.drop_index("ix_llm_provider_models_source_key", table_name="llm_provider_models")
    op.drop_index(
        "ix_llm_provider_models_lifecycle_status", table_name="llm_provider_models"
    )
    op.drop_index(
        "ix_llm_provider_models_last_synced_at", table_name="llm_provider_models"
    )
    op.drop_column("llm_provider_models", "last_synced_at")
    op.drop_column("llm_provider_models", "source_record_id")
    op.drop_column("llm_provider_models", "source_key")
    op.drop_column("llm_provider_models", "raw_source_metadata")
    op.drop_column("llm_provider_models", "capabilities")
    op.drop_column("llm_provider_models", "lifecycle_status")

    op.drop_constraint(
        "fk_llm_models_source_key_llm_catalog_sources",
        "llm_models",
        type_="foreignkey",
    )
    op.drop_index("ix_llm_models_source_key", table_name="llm_models")
    op.drop_column("llm_models", "source_model_id")
    op.drop_column("llm_models", "source_key")

    op.drop_index("ix_llm_model_overrides_expires_at", table_name="llm_model_overrides")
    op.drop_table("llm_model_overrides")

    op.drop_index("ix_llm_catalog_sources_status", table_name="llm_catalog_sources")
    op.drop_index(
        "ix_llm_catalog_sources_last_success_at", table_name="llm_catalog_sources"
    )
    op.drop_table("llm_catalog_sources")

    bind = op.get_bind()
    llm_catalog_source_status.drop(bind, checkfirst=True)
    llm_catalog_source_type.drop(bind, checkfirst=True)
    llm_model_lifecycle_status.drop(bind, checkfirst=True)
