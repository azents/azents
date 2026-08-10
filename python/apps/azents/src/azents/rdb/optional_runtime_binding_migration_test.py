"""PostgreSQL migration tests for the optional Runtime downgrade barrier."""

from collections.abc import Generator
from contextlib import contextmanager

import pytest
import sqlalchemy as sa
from alembic import command as alembic_command
from alembic.config import Config as AlembicConfig
from testcontainers.postgres import PostgresContainer

from azents.consts import PROJECT_ROOT

_PARENT_REVISION = "4c64a691eddc"
_BARRIER_REVISION = "8b9f418cf037"


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


def _seed_agent(connection: sa.Connection, *, suffix: str) -> tuple[str, str]:
    """Seed one Agent with the migration defaults."""
    workspace_id = f"ws-barrier-{suffix}"
    agent_id = f"agent-barrier-{suffix}"
    connection.execute(
        sa.text(
            """
            INSERT INTO workspaces (id, name, handle)
            VALUES (:id, :name, :handle)
            """
        ),
        {
            "id": workspace_id,
            "name": f"Runtime barrier {suffix}",
            "handle": f"runtime-barrier-{suffix}",
        },
    )
    connection.execute(
        sa.text(
            """
            INSERT INTO agents (
                id, workspace_id, name, model_selection, lightweight_model_selection,
                selectable_model_options, main_model_label, lightweight_model_label
            )
            VALUES (
                :id,
                :workspace_id,
                :name,
                '{}'::jsonb,
                '{}'::jsonb,
                '[{"label":"default","model_selection":{}}]'::jsonb,
                'default',
                'default'
            )
            """
        ),
        {
            "id": agent_id,
            "workspace_id": workspace_id,
            "name": f"Runtime barrier Agent {suffix}",
        },
    )
    return workspace_id, agent_id


def _current_revision(engine: sa.Engine) -> str:
    """Return the database's current Alembic revision."""
    with engine.connect() as connection:
        revision = connection.scalar(sa.text("SELECT version_num FROM alembic_version"))
    return str(revision)


@pytest.mark.parametrize("unsupported_state", ["runtime_free", "binding_none"])
def test_downgrade_barrier_allows_legacy_state_and_rejects_optional_state(
    check_docker_availability: None,
    unsupported_state: str,
) -> None:
    """Permit a clean rollback but reject state the parent schema cannot represent."""
    del check_docker_availability
    with _migration_database() as (config, engine):
        alembic_command.upgrade(config, _BARRIER_REVISION)
        assert _current_revision(engine) == _BARRIER_REVISION

        alembic_command.downgrade(config, _PARENT_REVISION)
        assert _current_revision(engine) == _PARENT_REVISION

        alembic_command.upgrade(config, _BARRIER_REVISION)
        with engine.begin() as connection:
            workspace_id, agent_id = _seed_agent(
                connection,
                suffix=unsupported_state,
            )
            if unsupported_state == "runtime_free":
                connection.execute(
                    sa.text(
                        """
                        UPDATE agents
                        SET runtime_capability = 'none',
                            runtime_capability_version = 2
                        WHERE id = :agent_id
                        """
                    ),
                    {"agent_id": agent_id},
                )
            else:
                connection.execute(
                    sa.text(
                        """
                        INSERT INTO session_agent_contexts (
                            id,
                            agent_id,
                            workspace_id,
                            working_folder_cleanup_status,
                            working_folder_binding_state
                        )
                        VALUES (
                            :id,
                            :agent_id,
                            :workspace_id,
                            'not_attempted',
                            'none'
                        )
                        """
                    ),
                    {
                        "id": "context-runtime-barrier-binding",
                        "agent_id": agent_id,
                        "workspace_id": workspace_id,
                    },
                )

        with pytest.raises(
            RuntimeError,
            match="irreversible after optional Runtime or Session binding state",
        ):
            alembic_command.downgrade(config, _PARENT_REVISION)
        assert _current_revision(engine) == _BARRIER_REVISION
