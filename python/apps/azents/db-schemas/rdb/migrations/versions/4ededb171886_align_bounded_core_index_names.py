"""Align namespace-unique PostgreSQL-bounded core index names."""

from typing import NamedTuple, Sequence

from alembic import op

revision: str = "4ededb171886"
down_revision: str | Sequence[str] | None = "66aa52336fc8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


class IndexRename(NamedTuple):
    """An explicit index identifier rename without changing its definition."""

    old: str
    new: str


_INDEX_RENAMES = (
    IndexRename(
        "ix_agent_avatar_cleanup_jobs_next_attempt_lease_until",
        "ix_agent_avatar_cleanup_jobs_next_attempt_at_lease_until",
    ),
    IndexRename(
        "ix_agent_project_presets_agent_updated",
        "ix_agent_project_presets_agent_id_updated_at",
    ),
    IndexRename(
        "uq_agent_runtime_add_receipts_agent_idempotency",
        "ix_agent_runtime_add_receipts_agent_id_idempotency_key",
    ),
    IndexRename(
        "ix_agent_runtime_add_receipts_agent_created_at",
        "ix_agent_runtime_add_receipts_agent_id_created_at",
    ),
    IndexRename(
        "uq_agent_runtime_removal_operations_active_agent",
        "ix_agent_runtime_removal_operations_agent_id",
    ),
    IndexRename(
        "uq_agent_runtime_removal_operations_agent_idempotency",
        "ix_agent_runtime_removal_operations_agent_id_idempotency_key",
    ),
    IndexRename(
        "ix_agent_runtime_removal_operations_agent_created_at",
        "ix_agent_runtime_removal_operations_agent_id_created_at",
    ),
    IndexRename("ix_artifacts_session_status", "ix_artifacts_session_id_status"),
    IndexRename(
        "uq_external_channel_connections_http_callback_selector_hash",
        "ix_external_channel_connections_http_callback_selector_hash",
    ),
    IndexRename(
        "uq_external_channel_bindings_connected_resource",
        "ix_external_channel_bindings_resource_id",
    ),
    IndexRename(
        "uq_external_channel_access_grants_active_agent",
        "ix_external_channel_access_grants_agent_id_principal_id",
    ),
    IndexRename(
        "uq_external_channel_access_grants_active_session",
        "ix_external_channel_access_grants_agent_session_id_principal_id",
    ),
    IndexRename("uq_agent_memories_agent_scope", "ix_agent_memories_agent_id_name"),
    IndexRename(
        "uq_agent_memories_user_scope", "ix_agent_memories_agent_id_user_id_name"
    ),
    IndexRename("ix_agent_memories_agent_user", "ix_agent_memories_agent_id_user_id"),
    IndexRename("ix_model_files_session_status", "ix_model_files_session_id_status"),
    IndexRename(
        "ix_runtime_infrastructure_profiles_provider_lifecycle",
        "ix_runtime_infrastructure_profiles_provider_id_lifecycle",
    ),
    IndexRename(
        "ix_runtime_infrastructure_profiles_kind",
        "ix_runtime_infrastructure_profiles_profile_kind",
    ),
    IndexRename(
        "ix_workspace_runtime_profiles_workspace_lifecycle",
        "ix_workspace_runtime_profiles_workspace_id_lifecycle",
    ),
    IndexRename(
        "ix_runtime_configuration_reconcile_tasks_status_available",
        "ix_runtime_configuration_reconcile_tasks_status_available_at",
    ),
    IndexRename(
        "ix_runtime_configuration_reconcile_tasks_source",
        "ix_runtime_configuration_reconcile_tasks_source_type_source_id",
    ),
    IndexRename(
        "ix_runtime_recreation_operations_target",
        "ix_runtime_recreation_operations_target_kind_target_id",
    ),
    IndexRename(
        "ix_runtime_recreation_operation_items_operation_status",
        "ix_runtime_recreation_operation_items_operation_id_status",
    ),
    IndexRename(
        "ix_session_agent_context_projects_context_id",
        "ix_session_agent_context_projects_session_agent_context_id",
    ),
    IndexRename(
        "ix_session_agent_context_git_worktrees_context_id",
        "ix_session_agent_context_git_worktrees_session_agent_context_id",
    ),
)


def upgrade() -> None:
    """Rename indexes while preserving uniqueness, predicates and column order."""
    for rename in _INDEX_RENAMES:
        op.execute(f'ALTER INDEX "{rename.old}" RENAME TO "{rename.new}"')


def downgrade() -> None:
    """Restore the original explicit identifiers in reverse order."""
    for rename in reversed(_INDEX_RENAMES):
        op.execute(f'ALTER INDEX "{rename.new}" RENAME TO "{rename.old}"')
