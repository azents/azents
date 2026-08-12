"""Migration coverage for Agent-managed worktree removal path claims."""

from collections.abc import Generator
from contextlib import contextmanager

import sqlalchemy as sa
from alembic import command as alembic_command
from alembic.config import Config as AlembicConfig
from testcontainers.postgres import PostgresContainer

from azents.consts import PROJECT_ROOT

_PARENT_REVISION = "0a534149c228"
_REMOVAL_CLAIM_REVISION = "cf821b7c4df8"
_CLAIM_ID = "1" * 32
_RUNTIME_ID = "2" * 32


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


def _owner_kind_values(connection: sa.Connection) -> list[str]:
    """Return the persisted worktree claim owner-kind labels."""
    return list(
        connection.scalars(
            sa.text(
                """
                SELECT enumlabel
                FROM pg_enum
                JOIN pg_type ON pg_type.oid = pg_enum.enumtypid
                WHERE pg_type.typname = 'git_worktree_path_claim_owner_kind'
                ORDER BY enumsortorder
                """
            )
        )
    )


def _current_revision(engine: sa.Engine) -> str:
    """Return the database's current Alembic revision."""
    with engine.connect() as connection:
        revision = connection.scalar(sa.text("SELECT version_num FROM alembic_version"))
    return str(revision)


def test_agent_action_claim_kind_survives_downgrade_and_reupgrade(
    check_docker_availability: None,
) -> None:
    """Upgrade enables Agent claims and downgrade preserves their enum data."""
    del check_docker_availability
    with _migration_database() as (config, engine):
        alembic_command.upgrade(config, _PARENT_REVISION)
        with engine.connect() as connection:
            assert "agent_action" not in _owner_kind_values(connection)

        alembic_command.upgrade(config, _REMOVAL_CLAIM_REVISION)
        assert _current_revision(engine) == _REMOVAL_CLAIM_REVISION
        with engine.begin() as connection:
            assert "agent_action" in _owner_kind_values(connection)
            connection.execute(sa.text("SET session_replication_role = replica"))
            connection.execute(
                sa.text(
                    """
                    INSERT INTO git_worktree_path_claims (
                        id,
                        agent_runtime_id,
                        worktree_path,
                        owner_kind,
                        action_execution_id,
                        root_session_id,
                        owner_generation,
                        discovery_fingerprint,
                        state,
                        reason_code,
                        summary,
                        lease_until
                    )
                    VALUES (
                        :id,
                        :runtime_id,
                        '/workspace/agent/worktree',
                        'agent_action',
                        NULL,
                        NULL,
                        1,
                        NULL,
                        'claimed',
                        NULL,
                        NULL,
                        now() + interval '6 minutes'
                    )
                    """
                ),
                {"id": _CLAIM_ID, "runtime_id": _RUNTIME_ID},
            )
            connection.execute(sa.text("SET session_replication_role = origin"))

        alembic_command.downgrade(config, _PARENT_REVISION)
        assert _current_revision(engine) == _PARENT_REVISION
        with engine.connect() as connection:
            assert "agent_action" in _owner_kind_values(connection)
            owner_kind = connection.scalar(
                sa.text(
                    """
                    SELECT owner_kind::text
                    FROM git_worktree_path_claims
                    WHERE id = :id
                    """
                ),
                {"id": _CLAIM_ID},
            )
            assert owner_kind == "agent_action"

        alembic_command.upgrade(config, _REMOVAL_CLAIM_REVISION)
        assert _current_revision(engine) == _REMOVAL_CLAIM_REVISION
        with engine.connect() as connection:
            assert _owner_kind_values(connection).count("agent_action") == 1
