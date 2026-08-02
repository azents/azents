"""Migration coverage for External Channel lifecycle policy v2."""

from collections.abc import Generator
from contextlib import contextmanager

import pytest
import sqlalchemy as sa
from alembic import command as alembic_command
from alembic.config import Config as AlembicConfig
from testcontainers.postgres import PostgresContainer

from azents.consts import PROJECT_ROOT

_PARENT_REVISION = "7e425e8e3b7b"
_LIFECYCLE_REVISION = "b00cf0366fa3"


@contextmanager
def _migration_database() -> Generator[tuple[AlembicConfig, sa.Engine]]:
    """Create one isolated PostgreSQL database for migration verification."""
    with PostgresContainer("postgres:17", driver="psycopg") as postgres:
        url = postgres.get_connection_url()
        config = AlembicConfig(PROJECT_ROOT / "db-schemas" / "rdb" / "alembic.ini")
        config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
        engine = sa.create_engine(url)
        try:
            yield config, engine
        finally:
            engine.dispose()


def _seed_execution(
    connection: sa.Connection,
    *,
    job_id: str,
    status: str,
    policy_version: int,
    phase: str,
    attempt_count: int,
) -> None:
    """Seed one minimal durable participant execution at the prior revision."""
    connection.execute(
        sa.text(
            """
            INSERT INTO archived_session_purge_jobs (
                id, root_session_id, eligible_at, policy_revision, status
            ) VALUES (
                :job_id, :root_session_id, now(), 1, :status
            )
            """
        ),
        {
            "job_id": job_id,
            "root_session_id": f"root-{job_id}",
            "status": status,
        },
    )
    connection.execute(
        sa.text(
            """
            INSERT INTO archived_session_purge_participant_executions (
                purge_job_id, participant_key, policy_version, phase, attempt_count,
                blocked_by_participant_key, last_error_kind, last_error_summary,
                operational_summary, prepared_at, cleanup_completed_at, verified_at,
                last_attempt_at
            ) VALUES (
                :job_id, 'session.external-channel', :policy_version, :phase,
                :attempt_count, 'dependency', 'OldError', 'old error',
                '{"old": true}', now(), now(), now(), now()
            )
            """
        ),
        {
            "job_id": job_id,
            "policy_version": policy_version,
            "phase": phase,
            "attempt_count": attempt_count,
        },
    )


def test_lifecycle_v2_migration_resets_only_incomplete_execution_snapshots(
    check_docker_availability: None,
) -> None:
    """Upgrade advances only incomplete v1 checkpoints and guarded downgrade works."""
    del check_docker_availability
    with _migration_database() as (config, engine):
        alembic_command.upgrade(config, _PARENT_REVISION)
        with engine.begin() as connection:
            _seed_execution(
                connection,
                job_id="job-pending",
                status="pending",
                policy_version=1,
                phase="cleanup_completed",
                attempt_count=3,
            )
            _seed_execution(
                connection,
                job_id="job-completed",
                status="completed",
                policy_version=1,
                phase="verified",
                attempt_count=2,
            )
            _seed_execution(
                connection,
                job_id="job-cancelled",
                status="cancelled",
                policy_version=1,
                phase="prepared",
                attempt_count=1,
            )

        alembic_command.upgrade(config, _LIFECYCLE_REVISION)
        with engine.connect() as connection:
            rows = {
                row.job_id: row
                for row in connection.execute(
                    sa.text(
                        """
                        SELECT job.id AS job_id, execution.policy_version,
                               execution.phase, execution.attempt_count,
                               execution.blocked_by_participant_key,
                               execution.last_error_kind, execution.operational_summary,
                               execution.prepared_at, execution.cleanup_completed_at,
                               execution.verified_at, execution.last_attempt_at
                        FROM archived_session_purge_jobs AS job
                        JOIN archived_session_purge_participant_executions AS execution
                          ON execution.purge_job_id = job.id
                        ORDER BY job.id
                        """
                    )
                ).mappings()
            }
            pending = rows["job-pending"]
            assert pending["policy_version"] == 2
            assert pending["phase"] == "pending"
            assert pending["attempt_count"] == 0
            assert pending["blocked_by_participant_key"] is None
            assert pending["last_error_kind"] is None
            assert pending["operational_summary"] is None
            assert pending["prepared_at"] is None
            assert pending["cleanup_completed_at"] is None
            assert pending["verified_at"] is None
            assert pending["last_attempt_at"] is None
            assert rows["job-completed"]["policy_version"] == 1
            assert rows["job-completed"]["phase"] == "verified"
            assert rows["job-cancelled"]["policy_version"] == 1
            assert rows["job-cancelled"]["phase"] == "prepared"

        with pytest.raises(RuntimeError, match="lifecycle policy v2"):
            alembic_command.downgrade(config, _PARENT_REVISION)

        with engine.begin() as connection:
            connection.execute(
                sa.text(
                    """
                    DELETE FROM archived_session_purge_participant_executions
                    WHERE purge_job_id = 'job-pending'
                    """
                )
            )
        alembic_command.downgrade(config, _PARENT_REVISION)
