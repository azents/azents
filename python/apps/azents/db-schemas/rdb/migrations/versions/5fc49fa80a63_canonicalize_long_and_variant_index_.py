"""Canonicalize long and variant index names without changing definitions."""

from typing import NamedTuple, Sequence

from alembic import op

revision: str = "5fc49fa80a63"
down_revision: str | Sequence[str] | None = "a332f5e0f329"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


class IndexRename(NamedTuple):
    """Explicit source and destination identifiers for a name-only operation."""

    old: str
    new: str


_INDEX_RENAMES = (
    IndexRename(
        "uq_agent_runs_session_pending",
        "ix_agent_runs_session_id_unique_pafdf7e0366e76506",
    ),
    IndexRename(
        "ix_agent_runtimes_lifecycle_dispatch",
        "ix_agent_runtimes_desired_generation_last_life_bb2bd3e4f43c8f7a",
    ),
    IndexRename(
        "ix_agent_sessions_model_file_gc_cursor",
        "ix_agent_sessions_model_file_gc_cursor_event_i_75efbf56f215debd",
    ),
    IndexRename(
        "uq_agent_sessions_agent_active_team_primary",
        "ix_agent_sessions_agent_id_unique_p7b932c5c10d734da",
    ),
    IndexRename(
        "uq_archived_session_retention_applications_active",
        "ix_archived_session_retention_applications_exp_733c28f24767a30d",
    ),
    IndexRename(
        "ix_archived_purge_part_exec_job_phase",
        "ix_archived_session_purge_participant_executio_5ea0028eac0baeb3",
    ),
    IndexRename(
        "uq_chat_write_requests_creation_agent_requester_client",
        "ix_chat_write_requests_creation_agent_id_reque_b51989afdaf21d2f",
    ),
    IndexRename(
        "ix_exchange_upload_operations_due_cleanup",
        "ix_exchange_upload_operations_cleanup_after_cl_183b909f7be93a36",
    ),
    IndexRename(
        "uq_external_account_links_active_external_identity",
        "ix_external_account_links_provider_identity_sc_13d48b547d72dd7a",
    ),
    IndexRename(
        "uq_external_channel_connections_installation_identity",
        "ix_external_channel_connections_provider_provi_0a15e241b656e145",
    ),
    IndexRename(
        "uq_external_channel_conversation_positions_parent",
        "ix_external_channel_conversation_positions_con_1d1df5ccdc27993c",
    ),
    IndexRename(
        "uq_external_channel_conversation_positions_thread",
        "ix_external_channel_conversation_positions_con_fced1c72c65a3bca",
    ),
    IndexRename(
        "uq_external_channel_agent_routes_single_connection",
        "ix_external_channel_agent_routes_connection_id_e76c6f5501491d09",
    ),
    IndexRename(
        "uq_external_channel_channel_defaults_active_connection_channel",
        "ix_external_channel_channel_defaults_connectio_3ed2f72938e718df",
    ),
    IndexRename(
        "uq_external_channel_participation_active_channel",
        "ix_external_channel_participation_settings_con_eff7d8df5d637efe",
    ),
    IndexRename(
        "uq_external_channel_setup_claims_nonterminal_connection_channel",
        "ix_external_channel_setup_claims_connection_id_14a8330f61c7560b",
    ),
    IndexRename(
        "ix_external_channel_ingress_owners_recovery",
        "ix_external_channel_ingress_owners_preparation_401dc98916b2a085",
    ),
    IndexRename(
        "ix_external_channel_ingress_items_owner_due_queue",
        "ix_external_channel_ingress_items_owner_id_sta_805bf271f468bc7a",
    ),
    IndexRename(
        "ix_external_channel_ingress_items_position",
        "ix_external_channel_ingress_items_conversation_e956b183b9e748f3",
    ),
    IndexRename(
        "uq_github_user_installations_user_app_installation",
        "ix_github_user_installations_user_id_platform__04fa208ede6106a8",
    ),
    IndexRename(
        "uq_historical_consolidation_units_user",
        "ix_historical_consolidation_units_workspace_id_bea7c9654d4d7b7d",
    ),
    IndexRename(
        "ix_historical_consolidation_work_pending",
        "ix_historical_consolidation_work_workspace_id__76da5073a287ecef",
    ),
    IndexRename(
        "ix_historical_consolidation_revision_dependencies_source",
        "ix_historical_consolidation_revision_dependenc_6679cd501af214fe",
    ),
    IndexRename(
        "ix_image_generation_catalog_entries_catalog_rank",
        "ix_image_generation_catalog_entries_catalog_id_09d1052ed90fd2e8",
    ),
    IndexRename(
        "ix_runtime_provider_auth_binding_audit_events_binding_created",
        "ix_runtime_provider_auth_binding_audit_events__eb3dbab7484ad7a9",
    ),
    IndexRename(
        "ix_runtime_provider_connections_authentication",
        "ix_runtime_provider_connections_binding_id_aut_43f2baf6a989b7a6",
    ),
    IndexRename(
        "ix_runtime_web_session_routes_generation",
        "ix_runtime_web_session_routes_desired_generati_45b803111f49cb65",
    ),
    IndexRename(
        "ix_session_agent_context_git_worktrees_context_id_status",
        "ix_session_agent_context_git_worktrees_session_eed7843d46102e3f",
    ),
    IndexRename(
        "ix_session_agent_context_git_worktrees_context_project_id",
        "ix_session_agent_context_git_worktrees_session_ff1a8aeb4dda50f3",
    ),
    IndexRename(
        "ix_agent_automatic_project_items_agent_position",
        "ix_agent_automatic_project_items_agent_id_position",
    ),
    IndexRename(
        "ix_agent_project_catalog_entries_agent_updated",
        "ix_agent_project_catalog_entries_agent_id_updated_at",
    ),
    IndexRename(
        "ix_agent_project_defaults_agent_position",
        "ix_agent_project_defaults_agent_id_position",
    ),
    IndexRename(
        "ix_agent_runs_session_status",
        "ix_agent_runs_session_id_status",
    ),
    IndexRename(
        "ix_agent_run_input_events_event_run",
        "ix_agent_run_input_events_event_id_agent_run_id",
    ),
    IndexRename(
        "ix_agent_run_input_events_run_input_order",
        "ix_agent_run_input_events_agent_run_id_input_order",
    ),
    IndexRename(
        "ix_agent_runtimes_desired_observed",
        "ix_agent_runtimes_desired_state_provider_observed_state",
    ),
    IndexRename(
        "ix_agent_sessions_agent_active_last_user_input",
        "ix_agent_sessions_agent_id_primary_kind_last_user_input_at",
    ),
    IndexRename(
        "ix_agent_sessions_pending_command",
        "ix_agent_sessions_pending_command_created_at",
    ),
    IndexRename(
        "ix_agent_sessions_run_state_running",
        "ix_agent_sessions_run_heartbeat_at",
    ),
    IndexRename(
        "ix_agent_sessions_archived_purge_after",
        "ix_agent_sessions_purge_after",
    ),
    IndexRename(
        "ix_agent_sessions_active_auto_archive",
        "ix_agent_sessions_last_activity_at_agent_id",
    ),
    IndexRename(
        "ix_agent_sessions_agent_associated_user_status",
        "ix_agent_sessions_agent_id_associated_user_id_status",
    ),
    IndexRename(
        "ix_events_session_created",
        "ix_events_session_id_id",
    ),
    IndexRename(
        "uq_events_session_external",
        "ix_events_session_id_external_id",
    ),
    IndexRename(
        "ix_exchange_files_retention_root_status",
        "ix_exchange_files_retention_root_session_id_status_id",
    ),
    IndexRename(
        "ix_external_account_oauth_attempts_user_session",
        "ix_external_account_oauth_attempts_user_id_auth_session_id",
    ),
    IndexRename(
        "uq_historical_consolidation_units_team",
        "ix_historical_consolidation_units_workspace_id_agent_id",
    ),
    IndexRename(
        "ix_mailbox_items_session_order",
        "ix_mailbox_items_session_id_order_group_order_sequence_id",
    ),
    IndexRename(
        "uq_mailbox_items_session_kind_idempotency",
        "ix_mailbox_items_session_id_kind_idempotency_key",
    ),
    IndexRename(
        "uq_owner_lifecycle_jobs_membership_archive",
        "ix_owner_lifecycle_jobs_workspace_id_user_id",
    ),
    IndexRename(
        "uq_owner_lifecycle_jobs_account_purge",
        "ix_owner_lifecycle_jobs_user_id",
    ),
    IndexRename(
        "ix_runtime_providers_lifecycle_enabled",
        "ix_runtime_providers_lifecycle_state_enabled",
    ),
    IndexRename(
        "uq_runtime_provider_auth_bindings_method_subject_active",
        "ix_runtime_provider_auth_bindings_auth_method_subject",
    ),
    IndexRename(
        "uq_runtime_provider_auth_bindings_bootstrap_declaration_active",
        "ix_runtime_provider_auth_bindings_bootstrap_declaration_id",
    ),
    IndexRename(
        "ix_runtime_provider_auth_bindings_provider_state",
        "ix_runtime_provider_auth_bindings_provider_id_state",
    ),
    IndexRename(
        "ix_runtime_provider_auth_bindings_method_subject_state",
        "ix_runtime_provider_auth_bindings_auth_method_subject_state",
    ),
    IndexRename(
        "ix_runtime_provider_audit_events_provider_created",
        "ix_runtime_provider_audit_events_provider_id_created_at",
    ),
    IndexRename(
        "ix_runtime_provider_enrollment_grants_provider_state",
        "ix_runtime_provider_enrollment_grants_provider_id_state",
    ),
    IndexRename(
        "ix_runtime_provider_credentials_provider_state",
        "ix_runtime_provider_credentials_provider_id_state",
    ),
    IndexRename(
        "ix_runtime_provider_connections_provider_status",
        "ix_runtime_provider_connections_provider_id_status",
    ),
    IndexRename(
        "ix_runtime_provider_connections_credential_status",
        "ix_runtime_provider_connections_credential_id_status",
    ),
    IndexRename(
        "ix_runtime_provider_connections_binding_status",
        "ix_runtime_provider_connections_binding_id_status",
    ),
    IndexRename(
        "ix_runtime_provider_contract_revisions_provider_created",
        "ix_runtime_provider_contract_revisions_provider_id_created_at",
    ),
    IndexRename(
        "ix_runtime_provider_config_revisions_provider_state",
        "ix_runtime_provider_config_revisions_provider_id_state",
    ),
    IndexRename(
        "ix_runtime_provider_config_revisions_validation_request",
        "ix_runtime_provider_config_revisions_validation_request_id",
    ),
    IndexRename(
        "ix_runtime_web_services_agent",
        "ix_runtime_web_services_agent_id_created_at",
    ),
    IndexRename(
        "ix_runtime_web_services_deadline",
        "ix_runtime_web_services_exposure_deadline_at",
    ),
    IndexRename(
        "ix_runtime_web_operation_receipts_service",
        "ix_runtime_web_operation_receipts_service_id_created_at",
    ),
    IndexRename(
        "ix_runtime_web_gateway_identities_auth_session",
        "ix_runtime_web_gateway_identities_auth_session_id_expires_at",
    ),
    IndexRename(
        "ix_runtime_web_gateway_identities_expiry",
        "ix_runtime_web_gateway_identities_expires_at",
    ),
    IndexRename(
        "ix_runtime_web_auth_bindings_expiry",
        "ix_runtime_web_auth_bindings_expires_at",
    ),
    IndexRename(
        "ix_runtime_web_auth_tickets_expiry",
        "ix_runtime_web_auth_tickets_expires_at",
    ),
    IndexRename(
        "ix_runtime_web_session_routes_owner_lease",
        "ix_runtime_web_session_routes_owner_boot_id_lease_expires_at",
    ),
)


def upgrade() -> None:
    """Rename existing indexes while preserving their physical definitions."""
    for rename in _INDEX_RENAMES:
        op.execute(f'ALTER INDEX "{rename.old}" RENAME TO "{rename.new}"')


def downgrade() -> None:
    """Restore the prior explicit identifiers without rebuilding indexes."""
    for rename in reversed(_INDEX_RENAMES):
        op.execute(f'ALTER INDEX "{rename.new}" RENAME TO "{rename.old}"')
