"""PostgreSQL migration tests for Agent-scoped Toolkit ownership."""

from collections.abc import Generator
from contextlib import contextmanager

import pytest
import sqlalchemy as sa
from alembic import command as alembic_command
from alembic.config import Config as AlembicConfig
from sqlalchemy.exc import IntegrityError
from testcontainers.postgres import PostgresContainer

from azents.consts import PROJECT_ROOT

_PARENT_REVISION = "4ab7015e39b5"
_OWNERSHIP_REVISION = "39f7b371c71d"


@contextmanager
def _migration_database() -> Generator[tuple[AlembicConfig, sa.Engine]]:
    """Create an isolated PostgreSQL database for migration verification."""
    with PostgresContainer("postgres:17", driver="psycopg") as postgres:
        url = postgres.get_connection_url()
        config = AlembicConfig(PROJECT_ROOT / "db-schemas" / "rdb" / "alembic.ini")
        config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
        engine = sa.create_engine(url)
        try:
            yield config, engine
        finally:
            engine.dispose()


def _seed_workspace_agents_and_toolkit(connection: sa.Connection) -> None:
    """Seed existing shared Toolkit state at the parent revision."""
    connection.execute(
        sa.text(
            """
            INSERT INTO workspaces (id, name, handle)
            VALUES ('workspace-toolkit-owner', 'Toolkit owner', 'toolkit-owner')
            """
        )
    )
    for agent_id in ("agent-toolkit-owner-1", "agent-toolkit-owner-2"):
        connection.execute(
            sa.text(
                """
                INSERT INTO agents (
                    id, workspace_id, name, model_selection,
                    lightweight_model_selection, selectable_model_options,
                    main_model_label, lightweight_model_label
                )
                VALUES (
                    :agent_id,
                    'workspace-toolkit-owner',
                    :agent_id,
                    '{}'::jsonb,
                    '{}'::jsonb,
                    '[{"label":"default","model_selection":{}}]'::jsonb,
                    'default',
                    'default'
                )
                """
            ),
            {"agent_id": agent_id},
        )
    connection.execute(
        sa.text(
            """
            INSERT INTO toolkit_configs (
                id, workspace_id, toolkit_type, slug, name, config
            )
            VALUES (
                'toolkit-shared-existing',
                'workspace-toolkit-owner',
                'mcp',
                'shared',
                'Existing shared',
                '{}'::jsonb
            )
            """
        )
    )


def _insert_owned_toolkit(
    connection: sa.Connection,
    *,
    toolkit_id: str,
    agent_id: str,
    slug: str,
) -> None:
    """Insert one Agent-owned Toolkit after the ownership migration."""
    connection.execute(
        sa.text(
            """
            INSERT INTO toolkit_configs (
                id, workspace_id, owner_agent_id, toolkit_type, slug, name, config
            )
            VALUES (
                :toolkit_id,
                'workspace-toolkit-owner',
                :agent_id,
                'mcp',
                :slug,
                :toolkit_id,
                '{}'::jsonb
            )
            """
        ),
        {
            "toolkit_id": toolkit_id,
            "agent_id": agent_id,
            "slug": slug,
        },
    )


def _current_revision(engine: sa.Engine) -> str:
    """Return the database's current Alembic revision."""
    with engine.connect() as connection:
        revision = connection.scalar(sa.text("SELECT version_num FROM alembic_version"))
    return str(revision)


def test_agent_scoped_toolkit_migration_preserves_shared_rows_and_guards_downgrade(
    check_docker_availability: None,
) -> None:
    """Verify local slug domains, owner cascade, and the downgrade barrier."""
    del check_docker_availability
    with _migration_database() as (config, engine):
        alembic_command.upgrade(config, _PARENT_REVISION)
        with engine.begin() as connection:
            _seed_workspace_agents_and_toolkit(connection)

        alembic_command.upgrade(config, _OWNERSHIP_REVISION)
        assert _current_revision(engine) == _OWNERSHIP_REVISION

        inspector = sa.inspect(engine)
        columns = {
            column["name"] for column in inspector.get_columns("toolkit_configs")
        }
        indexes = {
            index["name"]: index for index in inspector.get_indexes("toolkit_configs")
        }
        assert "owner_agent_id" in columns
        assert indexes["uq_toolkit_configs_shared_workspace_slug"]["unique"] is True
        assert indexes["uq_toolkit_configs_owner_agent_slug"]["unique"] is True

        with engine.begin() as connection:
            existing_owner = connection.scalar(
                sa.text(
                    """
                    SELECT owner_agent_id
                    FROM toolkit_configs
                    WHERE id = 'toolkit-shared-existing'
                    """
                )
            )
            assert existing_owner is None

            _insert_owned_toolkit(
                connection,
                toolkit_id="toolkit-owned-agent-1",
                agent_id="agent-toolkit-owner-1",
                slug="github",
            )
            _insert_owned_toolkit(
                connection,
                toolkit_id="toolkit-owned-agent-2",
                agent_id="agent-toolkit-owner-2",
                slug="github",
            )
            connection.execute(
                sa.text(
                    """
                    INSERT INTO toolkit_configs (
                        id, workspace_id, toolkit_type, slug, name, config
                    )
                    VALUES (
                        'toolkit-shared-same-slug',
                        'workspace-toolkit-owner',
                        'mcp',
                        'github',
                        'Shared same slug',
                        '{}'::jsonb
                    )
                    """
                )
            )

        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                _insert_owned_toolkit(
                    connection,
                    toolkit_id="toolkit-owned-duplicate",
                    agent_id="agent-toolkit-owner-1",
                    slug="github",
                )

        with engine.begin() as connection:
            connection.execute(
                sa.text("DELETE FROM agents WHERE id = 'agent-toolkit-owner-1'")
            )
            owner_one_count = connection.scalar(
                sa.text(
                    """
                    SELECT count(*)
                    FROM toolkit_configs
                    WHERE owner_agent_id = 'agent-toolkit-owner-1'
                    """
                )
            )
            assert owner_one_count == 0

        with pytest.raises(
            RuntimeError,
            match="downgrade is irreversible while Agent-owned Toolkits exist",
        ):
            alembic_command.downgrade(config, _PARENT_REVISION)
        assert _current_revision(engine) == _OWNERSHIP_REVISION

        with engine.begin() as connection:
            connection.execute(
                sa.text("DELETE FROM agents WHERE id = 'agent-toolkit-owner-2'")
            )
        alembic_command.downgrade(config, _PARENT_REVISION)
        assert _current_revision(engine) == _PARENT_REVISION
        downgraded_columns = {
            column["name"]
            for column in sa.inspect(engine).get_columns("toolkit_configs")
        }
        assert "owner_agent_id" not in downgraded_columns
