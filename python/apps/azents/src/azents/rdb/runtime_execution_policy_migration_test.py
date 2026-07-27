"""Runtime execution policy migration invariants."""

import io
import runpy
from pathlib import Path
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

_SEED_MIGRATION = (
    PROJECT_ROOT
    / "db-schemas"
    / "rdb"
    / "migrations"
    / "versions"
    / "f18c05d9d547_add_runtime_execution_policy_domain.py"
)
_DEFAULT_EGRESS_MIGRATION = (
    PROJECT_ROOT
    / "db-schemas"
    / "rdb"
    / "migrations"
    / "versions"
    / "19f9c6124382_default_runtime_egress_to_direct.py"
)
_PROFILE_ONLY_MIGRATION = (
    PROJECT_ROOT
    / "db-schemas"
    / "rdb"
    / "migrations"
    / "versions"
    / "8ee8f5ae5a4d_remove_runtime_execution_platform_policy.py"
)


def _migration_values(path: Path) -> dict[str, Any]:
    return runpy.run_path(str(path))


def test_migration_seed_matches_the_previous_standard_policy() -> None:
    """The original seed remains the exact predecessor of the current default."""
    seed_values = _migration_values(_SEED_MIGRATION)
    egress_values = _migration_values(_DEFAULT_EGRESS_MIGRATION)
    policy = RuntimeExecutionPolicyDocument.model_validate(
        seed_values["_STANDARD_POLICY"]
    )

    assert seed_values["_STANDARD_POLICY"] == egress_values["_OLD_STANDARD_POLICY"]
    assert seed_values["_STANDARD_DIGEST"] == digest_runtime_execution_policy(policy)
    assert seed_values["_STANDARD_DIGEST"] == egress_values["_OLD_STANDARD_DIGEST"]
    assert SYSTEM_STANDARD_PROFILE_ID == "system-standard"


def test_default_egress_migration_matches_application_owned_standard_policy() -> None:
    """The migrated Standard is canonical and application-owned."""
    values = _migration_values(_DEFAULT_EGRESS_MIGRATION)
    policy = RuntimeExecutionPolicyDocument.model_validate(
        values["_DIRECT_STANDARD_POLICY"]
    )

    assert policy == standard_runtime_execution_policy()
    assert values["_DIRECT_STANDARD_DIGEST"] == digest_runtime_execution_policy(policy)


def test_migration_backfill_restriction_is_canonical_empty_intent() -> None:
    """Workspace and Agent migration rows do not add lower-layer authority."""
    values = _migration_values(_SEED_MIGRATION)
    restriction = RuntimeExecutionPolicyRestriction.model_validate(
        values["_EMPTY_RESTRICTION"]
    )

    assert values["_EMPTY_RESTRICTION_DIGEST"] == digest_runtime_execution_policy(
        restriction
    )
    assert all(value is None for name, value in restriction if name != "schema_version")


def test_revision_pointer_and_backfills_are_present() -> None:
    """The latest revision is selected and preserves existing Runtime snapshots."""
    revision_file = PROJECT_ROOT / "db-schemas" / "rdb" / "revision"
    seed_source = _SEED_MIGRATION.read_text()
    egress_source = _DEFAULT_EGRESS_MIGRATION.read_text()
    profile_only_source = _PROFILE_ONLY_MIGRATION.read_text()

    assert revision_file.read_text().strip() == "8ee8f5ae5a4d"
    assert "INSERT INTO workspace_runtime_execution_policies" in seed_source
    assert "INSERT INTO workspace_runtime_execution_profile_allowances" in seed_source
    assert "INSERT INTO agent_runtime_execution_settings" in seed_source
    assert "UPDATE runtime_execution_platform_policies" in egress_source
    assert "UPDATE runtime_execution_profiles" in egress_source
    assert "UPDATE agent_runtimes" not in egress_source
    assert 'op.drop_table("runtime_execution_platform_policies")' in profile_only_source
    assert 'op.drop_column("runtime_policy_snapshots"' in profile_only_source


def test_generated_revisions_render_valid_incremental_postgresql_sql() -> None:
    """The execution-policy upgrades render independently from the prior schema."""
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
        "f18c05d9d547:8ee8f5ae5a4d",
        sql=True,
    )

    rendered = output.getvalue()
    assert "UPDATE runtime_execution_platform_policies" in rendered
    assert "UPDATE runtime_execution_profiles" in rendered
    assert '"mode":"direct"' in rendered
    assert "UPDATE agent_runtimes" not in rendered
    assert "DROP TABLE runtime_execution_platform_policies" in rendered
    assert "DROP COLUMN execution_platform_version" in rendered
