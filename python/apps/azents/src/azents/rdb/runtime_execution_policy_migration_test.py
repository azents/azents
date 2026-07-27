"""Runtime execution policy migration invariants."""

import hashlib
import io
import json
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
_EXTERNAL_CHANNEL_HEALTH_CODE_MIGRATION = (
    PROJECT_ROOT
    / "db-schemas"
    / "rdb"
    / "migrations"
    / "versions"
    / "e0615474dc27_add_external_channel_health_code.py"
)
_RESOURCE_V2_MIGRATION = (
    PROJECT_ROOT
    / "db-schemas"
    / "rdb"
    / "migrations"
    / "versions"
    / "142ffe7ca6e9_upgrade_runtime_resource_policy.py"
)
_JSON_TEXT_MIGRATION = (
    PROJECT_ROOT
    / "db-schemas"
    / "rdb"
    / "migrations"
    / "versions"
    / "7b4c1d2e9f60_store_runtime_policy_as_json_text.py"
)


def _migration_values(path: Path) -> dict[str, Any]:
    return runpy.run_path(str(path))


def _raw_digest(document: object) -> str:
    encoded = json.dumps(
        document,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def test_migration_seed_matches_the_previous_standard_policy() -> None:
    """The original seed remains the exact predecessor of the current default."""
    seed_values = _migration_values(_SEED_MIGRATION)
    egress_values = _migration_values(_DEFAULT_EGRESS_MIGRATION)
    assert seed_values["_STANDARD_POLICY"] == egress_values["_OLD_STANDARD_POLICY"]
    assert seed_values["_STANDARD_DIGEST"] == _raw_digest(
        seed_values["_STANDARD_POLICY"]
    )
    assert seed_values["_STANDARD_DIGEST"] == egress_values["_OLD_STANDARD_DIGEST"]
    assert SYSTEM_STANDARD_PROFILE_ID == "system-standard"


def test_default_egress_migration_matches_application_owned_standard_policy() -> None:
    """The migrated Standard is canonical and application-owned."""
    values = _migration_values(_DEFAULT_EGRESS_MIGRATION)
    resource_values = _migration_values(_RESOURCE_V2_MIGRATION)
    json_text_values = _migration_values(_JSON_TEXT_MIGRATION)
    policy = RuntimeExecutionPolicyDocument.model_validate(
        json_text_values["_set_resource_module_version"](
            resource_values["_transform_document"](
                values["_DIRECT_STANDARD_POLICY"],
                resource_values["_upgrade_resources"],
            ),
            version=1,
        )
    )

    assert policy == standard_runtime_execution_policy()
    assert values["_DIRECT_STANDARD_DIGEST"] == _raw_digest(
        values["_DIRECT_STANDARD_POLICY"]
    )
    assert resource_values["_digest"](policy.model_dump(mode="json")) == (
        digest_runtime_execution_policy(policy)
    )


def test_migration_backfill_restriction_is_canonical_empty_intent() -> None:
    """Workspace and Agent migration rows do not add lower-layer authority."""
    values = _migration_values(_SEED_MIGRATION)
    resource_values = _migration_values(_RESOURCE_V2_MIGRATION)
    json_text_values = _migration_values(_JSON_TEXT_MIGRATION)
    restriction = RuntimeExecutionPolicyRestriction.model_validate(
        json_text_values["_set_resource_module_version"](
            resource_values["_transform_document"](
                values["_EMPTY_RESTRICTION"],
                resource_values["_upgrade_resources"],
            ),
            version=1,
        )
    )

    assert values["_EMPTY_RESTRICTION_DIGEST"] == _raw_digest(
        values["_EMPTY_RESTRICTION"]
    )
    assert resource_values["_digest"](restriction.model_dump(mode="json")) == (
        digest_runtime_execution_policy(restriction)
    )
    assert all(value is None for name, value in restriction if name != "schema_version")


def test_resource_migration_preserves_json_null_runtime_snapshots() -> None:
    """Unresolved snapshots store JSON null and are not policy documents."""
    resource_values = _migration_values(_RESOURCE_V2_MIGRATION)

    assert (
        resource_values["_transform_optional_document"](
            None,
            resource_values["_upgrade_resources"],
        )
        is None
    )
    assert (
        "jsonb_typeof(resolved_execution_policy) = 'object'"
        in _RESOURCE_V2_MIGRATION.read_text()
    )


def test_json_text_migration_canonicalizes_existing_policy_documents() -> None:
    """Existing JSONB objects become deterministic JSON strings."""
    values = _migration_values(_JSON_TEXT_MIGRATION)

    assert values["down_revision"] == "142ffe7ca6e9"
    assert values["_canonical_json"]({"z": 1, "a": [2, 3]}) == ('{"a":[2,3],"z":1}')
    assert values["_set_resource_module_version"](
        {"resources": {"module_id": "container.resources", "version": 2}},
        version=1,
    ) == {"resources": {"module_id": "container.resources", "version": 1}}


def test_revision_pointer_and_backfills_are_present() -> None:
    """The latest revision is selected and preserves existing Runtime snapshots."""
    revision_file = PROJECT_ROOT / "db-schemas" / "rdb" / "revision"
    seed_source = _SEED_MIGRATION.read_text()
    egress_source = _DEFAULT_EGRESS_MIGRATION.read_text()
    profile_only_source = _PROFILE_ONLY_MIGRATION.read_text()
    health_code_source = _EXTERNAL_CHANNEL_HEALTH_CODE_MIGRATION.read_text()
    resource_v2_source = _RESOURCE_V2_MIGRATION.read_text()
    json_text_source = _JSON_TEXT_MIGRATION.read_text()
    resource_values = _migration_values(_RESOURCE_V2_MIGRATION)

    assert revision_file.read_text().strip() == "7b4c1d2e9f60"
    assert resource_values["down_revision"] == "e0615474dc27"
    assert "INSERT INTO workspace_runtime_execution_policies" in seed_source
    assert "INSERT INTO workspace_runtime_execution_profile_allowances" in seed_source
    assert "INSERT INTO agent_runtime_execution_settings" in seed_source
    assert "UPDATE runtime_execution_platform_policies" in egress_source
    assert "UPDATE runtime_execution_profiles" in egress_source
    assert "UPDATE agent_runtimes" not in egress_source
    assert 'op.drop_table("runtime_execution_platform_policies")' in profile_only_source
    assert 'op.drop_column("runtime_policy_snapshots"' in profile_only_source
    assert '"last_health_code", sa.String(length=64)' in health_code_source
    assert '"version" = 2' not in resource_v2_source
    assert 'upgraded["version"] = 2' in resource_v2_source
    assert "application_state = 'pending'" in resource_v2_source
    assert 'new_column_name="resolved_execution_policy_json"' in json_text_source
    assert "jsonb_typeof(resolved_execution_policy) = 'object'" in json_text_source
    assert "_rewrite_policy_documents(version=1)" in json_text_source
    assert "_rewrite_policy_documents(version=2)" not in json_text_source
    assert "stale.accepted_at IS NULL" in json_text_source
    assert (
        '"uq_runtime_provider_contract_revisions_provider_digest"' in json_text_source
    )


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


def test_external_channel_health_code_migration_is_additive() -> None:
    """The Discord failure reason storage extends the current schema head."""
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
        "8ee8f5ae5a4d:e0615474dc27",
        sql=True,
    )

    rendered = output.getvalue()
    assert "ADD COLUMN last_health_code VARCHAR(64)" in rendered
