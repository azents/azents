"""Installed PostgreSQL lifecycle graph reader and validator tests."""

from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.session_lifecycle import (
    SessionLifecycleOwnershipManifest,
    SessionLifecycleResource,
    SessionLifecycleResourceClassification,
    SessionLifecycleResourceKind,
)
from azents.services.session_lifecycle.registry import (
    get_session_lifecycle_ownership_manifest,
)
from azents.services.session_lifecycle.schema import (
    PostgreSQLForeignKey,
    PostgreSQLForeignKeyDeleteAction,
    PostgreSQLSessionLifecycleGraphReader,
    SessionLifecycleSchemaValidator,
)


def _foreign_key(
    constraint_name: str,
    *,
    source_table: str,
    target_table: str,
    delete_action: PostgreSQLForeignKeyDeleteAction,
) -> PostgreSQLForeignKey:
    """Build a concise installed-graph test edge."""
    return PostgreSQLForeignKey(
        constraint_name=constraint_name,
        source_table=source_table,
        target_table=target_table,
        delete_action=delete_action,
        triggers=(),
    )


def test_validator_reports_complete_paths_for_lifecycle_root_and_multipath() -> None:
    """Unsafe fixture paths retain constraint names for actionable diagnostics."""
    manifest = SessionLifecycleOwnershipManifest(
        resources=(
            SessionLifecycleResource(
                kind=SessionLifecycleResourceKind.DATABASE_TABLE,
                name="agent_sessions",
                classification=SessionLifecycleResourceClassification.ORCHESTRATOR_ROOT,
                test_node_id="test_finalizer",
            ),
            SessionLifecycleResource(
                kind=SessionLifecycleResourceKind.DATABASE_TABLE,
                name="worktrees",
                classification=SessionLifecycleResourceClassification.LIFECYCLE_ROOT,
                test_node_id="test_worktree_finalizer",
            ),
        )
    )
    result = SessionLifecycleSchemaValidator().validate(
        foreign_keys=(
            _foreign_key(
                "fk_worktrees_session",
                source_table="public.worktrees",
                target_table="public.agent_sessions",
                delete_action=PostgreSQLForeignKeyDeleteAction.CASCADE,
            ),
            _foreign_key(
                "fk_context_session",
                source_table="public.contexts",
                target_table="public.agent_sessions",
                delete_action=PostgreSQLForeignKeyDeleteAction.CASCADE,
            ),
            _foreign_key(
                "fk_worktrees_context",
                source_table="public.worktrees",
                target_table="public.contexts",
                delete_action=PostgreSQLForeignKeyDeleteAction.SET_NULL,
            ),
        ),
        manifest=manifest,
        root_table="public.agent_sessions",
    )

    worktree_violations = [
        violation
        for violation in result.violations
        if violation.table_name == "public.worktrees"
    ]
    assert {violation.code for violation in worktree_violations} == {
        "lifecycle_root_mutated_by_parent_delete",
        "multiple_mutating_paths",
    }
    assert "fk_worktrees_session" in worktree_violations[0].message
    assert "fk_worktrees_context" in worktree_violations[0].message


async def test_installed_catalog_reader_exposes_current_worktree_risk(
    rdb_session: AsyncSession,
) -> None:
    """Fresh migrated PostgreSQL exposes trigger-backed unsafe worktree paths."""
    foreign_keys = await PostgreSQLSessionLifecycleGraphReader().read_foreign_keys(
        rdb_session
    )
    worktree_foreign_keys = [
        foreign_key
        for foreign_key in foreign_keys
        if foreign_key.source_table == "public.session_agent_context_git_worktrees"
    ]

    assert worktree_foreign_keys
    assert all(foreign_key.triggers for foreign_key in worktree_foreign_keys)

    result = SessionLifecycleSchemaValidator().validate(
        foreign_keys=foreign_keys,
        manifest=get_session_lifecycle_ownership_manifest(),
        root_table="public.agent_sessions",
    )
    worktree_violations = [
        violation
        for violation in result.violations
        if violation.table_name == "public.session_agent_context_git_worktrees"
    ]
    assert any(
        violation.code == "lifecycle_root_mutated_by_parent_delete"
        for violation in worktree_violations
    )
    assert any(
        violation.code == "multiple_mutating_paths" for violation in worktree_violations
    )


async def test_installed_catalog_restricts_agent_decommission_lifecycle_roots(
    rdb_session: AsyncSession,
) -> None:
    """Fresh migrated PostgreSQL protects Agent and Workspace lifecycle roots."""
    foreign_keys = await PostgreSQLSessionLifecycleGraphReader().read_foreign_keys(
        rdb_session
    )
    expected_constraints = {
        "agents_workspace_id_fkey",
        "agent_sessions_workspace_id_fkey",
        "agent_sessions_agent_id_fkey",
        "agent_runtimes_workspace_id_fkey",
        "agent_runtimes_agent_id_fkey",
        "artifacts_agent_id_fkey",
        "exchange_files_agent_id_fkey",
        "model_files_agent_id_fkey",
        "session_agent_contexts_agent_id_fkey",
        "toolkit_states_agent_id_fkey",
    }
    lifecycle_root_foreign_keys = {
        foreign_key.constraint_name: foreign_key
        for foreign_key in foreign_keys
        if foreign_key.constraint_name in expected_constraints
    }

    assert lifecycle_root_foreign_keys.keys() == expected_constraints
    assert all(
        foreign_key.delete_action is PostgreSQLForeignKeyDeleteAction.RESTRICT
        for foreign_key in lifecycle_root_foreign_keys.values()
    )
    assert all(
        foreign_key.triggers for foreign_key in lifecycle_root_foreign_keys.values()
    )
