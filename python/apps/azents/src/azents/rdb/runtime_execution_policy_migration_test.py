"""Runtime execution policy migration invariants."""

import io
import runpy
from typing import Any

from alembic import command as alembic_command
from alembic.config import Config as AlembicConfig

from azents.consts import PROJECT_ROOT
from azents.core.runtime_execution_policy import (
    SYSTEM_STANDARD_PROFILE_ID,
    RuntimeExecutionPolicyDocument,
    RuntimeExecutionPolicyRestriction,
    digest_runtime_execution_policy,
    standard_runtime_execution_policy,
)

_MIGRATION = (
    PROJECT_ROOT
    / "db-schemas"
    / "rdb"
    / "migrations"
    / "versions"
    / "f18c05d9d547_add_runtime_execution_policy_domain.py"
)


def _migration_values() -> dict[str, Any]:
    return runpy.run_path(str(_MIGRATION))


def test_migration_seed_matches_application_owned_standard_policy() -> None:
    """Seeded Standard is canonical, non-expanding, and application-owned."""
    values = _migration_values()
    policy = RuntimeExecutionPolicyDocument.model_validate(values["_STANDARD_POLICY"])

    assert policy == standard_runtime_execution_policy()
    assert values["_STANDARD_DIGEST"] == digest_runtime_execution_policy(policy)
    assert SYSTEM_STANDARD_PROFILE_ID == "system-standard"


def test_migration_backfill_restriction_is_canonical_empty_intent() -> None:
    """Workspace and Agent migration rows do not add lower-layer authority."""
    values = _migration_values()
    restriction = RuntimeExecutionPolicyRestriction.model_validate(
        values["_EMPTY_RESTRICTION"]
    )

    assert values["_EMPTY_RESTRICTION_DIGEST"] == digest_runtime_execution_policy(
        restriction
    )
    assert all(value is None for name, value in restriction if name != "schema_version")


def test_revision_pointer_and_backfills_are_present() -> None:
    """The generated revision is selected and explicitly backfills every scope."""
    revision_file = PROJECT_ROOT / "db-schemas" / "rdb" / "revision"
    source = _MIGRATION.read_text()

    assert revision_file.read_text().strip() == "f18c05d9d547"
    assert "INSERT INTO workspace_runtime_execution_policies" in source
    assert "INSERT INTO workspace_runtime_execution_profile_allowances" in source
    assert "INSERT INTO agent_runtime_execution_settings" in source
    assert "UPDATE agent_runtimes" not in source


def test_generated_revision_renders_valid_incremental_postgresql_sql() -> None:
    """The additive upgrade renders independently from the prior schema head."""
    output = io.StringIO()
    config = AlembicConfig(
        PROJECT_ROOT / "db-schemas" / "rdb" / "alembic.ini",
        output_buffer=output,
    )
    config.set_main_option(
        "sqlalchemy.url",
        "postgresql+psycopg://user:password@localhost/database",
    )

    alembic_command.upgrade(
        config,
        "3dd5802b8a10:f18c05d9d547",
        sql=True,
    )

    rendered = output.getvalue()
    assert "CREATE TYPE runtime_execution_profile_lifecycle" in rendered
    assert "INSERT INTO runtime_execution_platform_policies" in rendered
    assert '"enabled":false' in rendered
    assert '"enabled"NULL' not in rendered
