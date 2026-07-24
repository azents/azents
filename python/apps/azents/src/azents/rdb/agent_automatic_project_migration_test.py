"""Migration tests for Agent automatic Project policies."""

from collections.abc import Generator

import sqlalchemy as sa
from alembic import command as alembic_command
from alembic.config import Config as AlembicConfig
from azcommon.testing.images import get_docker_hub_image
from testcontainers.postgres import PostgresContainer

from azents.consts import PROJECT_ROOT

_PARENT_REVISION = "b976b12168b5"
_POLICY_REVISION = "995d915ed6d6"


def _migration_database() -> Generator[tuple[AlembicConfig, sa.Engine], None, None]:
    """Create an isolated PostgreSQL database for migration verification."""
    with PostgresContainer(
        get_docker_hub_image("postgres:17"),
        driver="psycopg",
    ) as postgres:
        url = postgres.get_connection_url()
        config = AlembicConfig(PROJECT_ROOT / "db-schemas" / "rdb" / "alembic.ini")
        config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
        engine = sa.create_engine(url)
        try:
            yield config, engine
        finally:
            engine.dispose()


def _seed_pre_policy_agent(connection: sa.Connection) -> None:
    """Seed one parent-revision Agent and unrelated recency default."""
    connection.execute(
        sa.text(
            """
            INSERT INTO workspaces (id, name, handle)
            VALUES ('workspace-policy-migration', 'Migration test', 'policy-migration')
            """
        )
    )
    connection.execute(
        sa.text(
            """
            INSERT INTO agents (
                id,
                workspace_id,
                name,
                model_selection,
                lightweight_model_selection,
                selectable_model_options,
                main_model_label,
                lightweight_model_label
            )
            VALUES (
                'agent-policy-migration',
                'workspace-policy-migration',
                'Migration test Agent',
                '{}'::jsonb,
                '{}'::jsonb,
                '[
                    {
                        "label": "default",
                        "model_selection": {},
                        "settings": {
                            "context_window_tokens": null,
                            "max_output_tokens": null,
                            "builtin_tools": [],
                            "subagent_enabled": true,
                            "subagent_guidance": null
                        }
                    }
                ]'::jsonb,
                'default',
                'default'
            )
            """
        )
    )
    connection.execute(
        sa.text(
            """
            INSERT INTO agent_project_defaults (
                id,
                agent_id,
                path,
                position,
                item_type
            )
            VALUES (
                'legacy-policy-default',
                'agent-policy-migration',
                '/workspace/agent/recency-default',
                0,
                'existing_project'::agent_project_default_item_type
            )
            """
        )
    )


def test_automatic_project_policy_migration_round_trip(
    check_docker_availability: None,
) -> None:
    """Backfill empty policies without reusing recency defaults."""
    del check_docker_availability
    migration_database = _migration_database()
    config, engine = next(migration_database)
    try:
        alembic_command.upgrade(config, _PARENT_REVISION)
        with engine.begin() as connection:
            _seed_pre_policy_agent(connection)

        alembic_command.upgrade(config, _POLICY_REVISION)
        with engine.connect() as connection:
            setting = (
                connection.execute(
                    sa.text(
                        """
                    SELECT
                        revision,
                        updated_by_workspace_user_id
                    FROM agent_automatic_project_settings
                    WHERE agent_id = 'agent-policy-migration'
                    """
                    )
                )
                .mappings()
                .one()
            )
            item_count = connection.scalar(
                sa.text(
                    """
                    SELECT count(*)
                    FROM agent_automatic_project_items
                    WHERE agent_id = 'agent-policy-migration'
                    """
                )
            )
            constraint_names = set(
                connection.scalars(
                    sa.text(
                        """
                        SELECT conname
                        FROM pg_constraint
                        WHERE conrelid = 'agent_automatic_project_items'::regclass
                        """
                    )
                )
            )
            index_names = set(
                connection.scalars(
                    sa.text(
                        """
                        SELECT indexname
                        FROM pg_indexes
                        WHERE schemaname = 'public'
                          AND tablename = 'agent_automatic_project_items'
                        """
                    )
                )
            )

            assert setting == {
                "revision": 1,
                "updated_by_workspace_user_id": None,
            }
            assert item_count == 0
            assert "uq_agent_automatic_project_items_agent_path" in constraint_names
            assert "uq_agent_automatic_project_items_agent_position" in constraint_names
            assert "ix_agent_automatic_project_items_agent_position" in index_names

        alembic_command.downgrade(config, _PARENT_REVISION)
        with engine.connect() as connection:
            assert (
                connection.scalar(
                    sa.text(
                        "SELECT to_regclass('public.agent_automatic_project_settings')"
                    )
                )
                is None
            )
            assert (
                connection.scalar(
                    sa.text(
                        "SELECT to_regclass('public.agent_automatic_project_items')"
                    )
                )
                is None
            )
            assert (
                connection.scalar(
                    sa.text(
                        """
                    SELECT count(*)
                    FROM agent_project_defaults
                    WHERE agent_id = 'agent-policy-migration'
                    """
                    )
                )
                == 1
            )
    finally:
        migration_database.close()
