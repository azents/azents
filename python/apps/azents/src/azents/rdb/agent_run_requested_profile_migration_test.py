"""Migration coverage for recoverable AgentRun requested profiles."""

from collections.abc import Generator
from contextlib import contextmanager

import sqlalchemy as sa
from alembic import command as alembic_command
from alembic.config import Config as AlembicConfig
from sqlalchemy.dialects import postgresql
from testcontainers.postgres import PostgresContainer

from azents.consts import PROJECT_ROOT

_PARENT_REVISION = "936373d16d53"
_PROFILE_REVISION = "d0e25b8b7f90"


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


def test_agent_run_requested_profile_migration_restores_profile_contract(
    check_docker_availability: None,
) -> None:
    """Upgrade restores nullable profile columns and their integrity constraint."""
    del check_docker_availability
    with _migration_database() as (config, engine):
        alembic_command.upgrade(config, _PARENT_REVISION)

        parent_columns = {
            column["name"] for column in sa.inspect(engine).get_columns("agent_runs")
        }
        assert "requested_model_target_label" not in parent_columns
        assert "requested_reasoning_effort" not in parent_columns

        alembic_command.upgrade(config, _PROFILE_REVISION)

        columns = {
            column["name"]: column
            for column in sa.inspect(engine).get_columns("agent_runs")
        }
        constraints = {
            constraint["name"]: constraint["sqltext"]
            for constraint in sa.inspect(engine).get_check_constraints("agent_runs")
        }
        requested_label_type = columns["requested_model_target_label"]["type"]
        requested_effort_type = columns["requested_reasoning_effort"]["type"]

        assert isinstance(requested_label_type, sa.String)
        assert requested_label_type.length == 80
        assert isinstance(requested_effort_type, postgresql.ENUM)
        assert requested_effort_type.name == "model_reasoning_effort"
        constraint = constraints["ck_agent_runs_requested_profile"]
        assert "requested_reasoning_effort IS NULL" in constraint
        assert "requested_model_target_label IS NOT NULL" in constraint

        alembic_command.downgrade(config, _PARENT_REVISION)
        downgraded_columns = {
            column["name"] for column in sa.inspect(engine).get_columns("agent_runs")
        }
        assert "requested_model_target_label" not in downgraded_columns
        assert "requested_reasoning_effort" not in downgraded_columns
