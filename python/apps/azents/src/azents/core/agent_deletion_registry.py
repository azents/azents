"""Agent deletion composition and explicit field-scoped ownership catalog."""

from azents.core.agent_deletion import (
    AgentDeletionParticipantDefinition,
    AgentDeletionPolicy,
    AgentDeletionRegistry,
    AgentDeletionRelationship,
)
from azents.core.session_lifecycle_schema import PostgreSQLForeignKeyDeleteAction


def _agent(
    table: str,
    column: str,
    action: PostgreSQLForeignKeyDeleteAction,
    policy: AgentDeletionPolicy,
) -> AgentDeletionRelationship:
    return AgentDeletionRelationship(
        table, (column,), "agents", ("id",), action, policy
    )


def _child(
    table: str,
    column: str,
    parent: str,
    action: PostgreSQLForeignKeyDeleteAction,
    policy: AgentDeletionPolicy,
) -> AgentDeletionRelationship:
    return AgentDeletionRelationship(table, (column,), parent, ("id",), action, policy)


def get_agent_deletion_registry() -> AgentDeletionRegistry:
    """Compose current owners; new schema edges must be deliberately classified."""
    absent = AgentDeletionPolicy.REQUIRE_ABSENT
    cascade = AgentDeletionPolicy.DECLARED_CASCADE
    detached = AgentDeletionPolicy.PRESERVE_DETACHED
    restrict = PostgreSQLForeignKeyDeleteAction.RESTRICT
    cascade_action = PostgreSQLForeignKeyDeleteAction.CASCADE
    set_null = PostgreSQLForeignKeyDeleteAction.SET_NULL
    return AgentDeletionRegistry(
        (
            AgentDeletionParticipantDefinition(
                key="agent.sessions",
                dependencies=(),
                relationships=tuple(
                    _agent(table, column, restrict, absent)
                    for table, column in (
                        ("agent_sessions", "agent_id"),
                        ("artifacts", "agent_id"),
                        ("model_files", "agent_id"),
                        ("session_agent_contexts", "agent_id"),
                        ("scheduled_tasks", "agent_id"),
                        ("toolkit_states", "agent_id"),
                        ("routines", "agent_id"),
                        ("chat_write_requests", "creation_agent_id"),
                        ("external_model_drafts", "agent_id"),
                    )
                ),
                external_resources=("session-retirement-delegation",),
                historical_resources=(),
            ),
            AgentDeletionParticipantDefinition(
                key="agent.runtime",
                dependencies=("agent.sessions",),
                relationships=(
                    _agent(
                        "agent_runtimes",
                        "agent_id",
                        restrict,
                        AgentDeletionPolicy.VERIFY_RUNTIME,
                    ),
                    *(
                        _child(table, column, "agent_runtimes", cascade_action, cascade)
                        for table, column in (
                            ("agent_runtime_add_receipts", "agent_runtime_id"),
                            ("git_worktree_path_claims", "agent_runtime_id"),
                            ("runtime_configuration_states", "runtime_id"),
                            ("runtime_web_session_routes", "runtime_id"),
                        )
                    ),
                    _child(
                        "agent_runtime_removal_operations",
                        "agent_runtime_id",
                        "agent_runtimes",
                        set_null,
                        detached,
                    ),
                    _child(
                        "session_agent_contexts",
                        "agent_runtime_id",
                        "agent_runtimes",
                        set_null,
                        detached,
                    ),
                ),
                external_resources=("runtime-terminal-generation-acknowledgement",),
                historical_resources=("runtime_recreation_operation_items.runtime_id",),
            ),
            AgentDeletionParticipantDefinition(
                key="agent.channels",
                dependencies=("agent.runtime",),
                relationships=(
                    _agent(
                        "external_channel_agent_routes", "agent_id", set_null, absent
                    ),
                    _agent(
                        "external_channel_access_grants", "agent_id", restrict, absent
                    ),
                    _agent("external_channel_blocks", "agent_id", restrict, absent),
                    _agent("external_model_mutations", "agent_id", set_null, detached),
                ),
                external_resources=(
                    "agent-channel-terminal-relationships",
                    "channel-best-effort-presentation",
                ),
                historical_resources=(
                    "external_channel_agent_routes.agent_id_snapshot",
                    "external_model_mutations.agent_id_snapshot",
                ),
            ),
            AgentDeletionParticipantDefinition(
                key="agent.files",
                dependencies=("agent.channels",),
                relationships=(
                    _agent("exchange_files", "agent_id", restrict, absent),
                    _agent("exchange_files", "source_agent_id", restrict, absent),
                ),
                external_resources=("unbound-agent-exchange-blobs",),
                historical_resources=(),
            ),
            AgentDeletionParticipantDefinition(
                key="agent.avatar",
                dependencies=("agent.files",),
                relationships=(
                    _agent("agent_avatar_cleanup_jobs", "agent_id", set_null, detached),
                ),
                external_resources=("current-agent-avatar-keys",),
                historical_resources=(),
            ),
            AgentDeletionParticipantDefinition(
                key="agent.database",
                dependencies=("agent.avatar",),
                relationships=(
                    *(
                        _agent(table, column, cascade_action, cascade)
                        for table, column in (
                            ("agent_admins", "agent_id"),
                            ("agent_automatic_project_settings", "agent_id"),
                            ("agent_memories", "agent_id"),
                            ("agent_project_catalog_entries", "agent_id"),
                            ("agent_project_defaults", "agent_id"),
                            ("agent_project_presets", "agent_id"),
                            ("agent_runtime_add_receipts", "agent_id"),
                            ("agent_runtime_removal_operations", "agent_id"),
                            ("agent_toolkit_namespace_reservations", "agent_id"),
                            ("agent_toolkit_namespace_sequences", "agent_id"),
                            ("agent_toolkits", "agent_id"),
                            ("agent_workspace_environment_selections", "agent_id"),
                            ("github_user_oauth_creations", "agent_id"),
                            ("google_oauth_attempts", "agent_id"),
                            ("memory_units", "agent_id"),
                            ("runtime_web_quota_scopes", "agent_id"),
                            ("runtime_web_services", "agent_id"),
                            ("toolkit_configs", "owner_agent_id"),
                        )
                    ),
                    AgentDeletionRelationship(
                        "personal_toolkit_agents",
                        ("agent_id", "workspace_id"),
                        "agents",
                        ("id", "workspace_id"),
                        cascade_action,
                        cascade,
                    ),
                    *(
                        _child(table, column, parent, cascade_action, cascade)
                        for table, column, parent in (
                            ("agent_toolkits", "toolkit_id", "toolkit_configs"),
                            (
                                "github_user_oauth_attempts",
                                "toolkit_id",
                                "toolkit_configs",
                            ),
                            (
                                "github_user_oauth_connections",
                                "toolkit_id",
                                "toolkit_configs",
                            ),
                            (
                                "google_oauth_attempts",
                                "target_toolkit_id",
                                "toolkit_configs",
                            ),
                            (
                                "google_oauth_connections",
                                "toolkit_id",
                                "toolkit_configs",
                            ),
                            ("mcp_oauth_connections", "toolkit_id", "toolkit_configs"),
                            (
                                "runtime_web_auth_bindings",
                                "service_id",
                                "runtime_web_services",
                            ),
                            (
                                "runtime_web_auth_tickets",
                                "service_id",
                                "runtime_web_services",
                            ),
                            (
                                "runtime_web_operation_receipts",
                                "service_id",
                                "runtime_web_services",
                            ),
                            (
                                "runtime_web_auth_tickets",
                                "binding_id",
                                "runtime_web_auth_bindings",
                            ),
                            ("memory_executions", "unit_id", "memory_units"),
                            ("memory_legacy_jobs", "unit_id", "memory_units"),
                            ("memory_work", "unit_id", "memory_units"),
                        )
                    ),
                    *(
                        AgentDeletionRelationship(
                            table,
                            ("toolkit_id", "owner_user_id", "workspace_id"),
                            "toolkit_configs",
                            ("id", "owner_user_id", "workspace_id"),
                            cascade_action,
                            cascade,
                        )
                        for table in (
                            "github_user_oauth_attempts",
                            "personal_toolkit_agents",
                        )
                    ),
                    _child(
                        "agent_toolkit_namespace_reservations",
                        "toolkit_id",
                        "toolkit_configs",
                        set_null,
                        detached,
                    ),
                    _child(
                        "session_agent_contexts",
                        "working_folder_invalidated_by_removal_id",
                        "agent_runtime_removal_operations",
                        restrict,
                        absent,
                    ),
                    AgentDeletionRelationship(
                        "memory_legacy_model_usage",
                        ("legacy_job_id",),
                        "memory_legacy_jobs",
                        ("legacy_job_id",),
                        cascade_action,
                        cascade,
                    ),
                    AgentDeletionRelationship(
                        "memory_work",
                        ("admitted_session_id",),
                        "memory_executions",
                        ("session_id",),
                        set_null,
                        detached,
                    ),
                    AgentDeletionRelationship(
                        "agent_automatic_project_items",
                        ("agent_id",),
                        "agent_automatic_project_settings",
                        ("agent_id",),
                        cascade_action,
                        cascade,
                    ),
                ),
                external_resources=(),
                historical_resources=("agent_decommission_jobs.agent_id",),
            ),
        )
    )
