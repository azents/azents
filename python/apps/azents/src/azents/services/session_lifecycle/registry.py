"""Application composition for the initial session lifecycle participant registry."""

from azents.core.session_lifecycle import (
    SessionLifecycleOwnershipManifest,
    SessionLifecycleParticipantDefinition,
    SessionLifecyclePurgePolicy,
    SessionLifecycleRegistry,
    SessionLifecycleResource,
    SessionLifecycleResourceClassification,
    SessionLifecycleResourceKind,
    SessionLifecycleTransitionPolicy,
)
from azents.services.session_lifecycle.orchestrator import (
    SessionLifecycleOrchestrator,
)


def _database_resource(
    name: str,
    classification: SessionLifecycleResourceClassification,
    test_node_id: str,
) -> SessionLifecycleResource:
    """Build one PostgreSQL ownership-manifest resource."""
    return SessionLifecycleResource(
        kind=SessionLifecycleResourceKind.DATABASE_TABLE,
        name=name,
        classification=classification,
        test_node_id=test_node_id,
    )


def _external_resource(name: str, test_node_id: str) -> SessionLifecycleResource:
    """Build one externally cleaned lifecycle resource."""
    return SessionLifecycleResource(
        kind=SessionLifecycleResourceKind.EXTERNAL_RESOURCE,
        name=name,
        classification=SessionLifecycleResourceClassification.LIFECYCLE_ROOT,
        test_node_id=test_node_id,
    )


def get_session_lifecycle_registry() -> SessionLifecycleRegistry:
    """Return the deterministic registry for the current SessionAgent root tree."""
    return SessionLifecycleRegistry(
        (
            SessionLifecycleParticipantDefinition(
                key="session.execution",
                policy_version=1,
                dependencies=(),
                owned_resources=(
                    _external_resource(
                        "session-execution-admission",
                        "test_session_lifecycle_execution_participant",
                    ),
                ),
                archive_policy=SessionLifecycleTransitionPolicy.VALIDATE,
                restore_policy=SessionLifecycleTransitionPolicy.PRESERVE,
                purge_policy=SessionLifecyclePurgePolicy.REQUIRED,
            ),
            SessionLifecycleParticipantDefinition(
                key="session.external-channel",
                policy_version=1,
                dependencies=("session.execution",),
                owned_resources=(
                    _database_resource(
                        "external_channel_bindings",
                        SessionLifecycleResourceClassification.LIFECYCLE_ROOT,
                        "test_session_lifecycle_external_channel",
                    ),
                    _database_resource(
                        "external_channel_invocation_batches",
                        SessionLifecycleResourceClassification.LIFECYCLE_ROOT,
                        "test_session_lifecycle_external_channel",
                    ),
                    _database_resource(
                        "external_channel_invocation_batch_items",
                        SessionLifecycleResourceClassification.PURE_DATABASE_CHILD,
                        "test_session_lifecycle_external_channel",
                    ),
                    _database_resource(
                        "external_channel_access_requests",
                        SessionLifecycleResourceClassification.LIFECYCLE_ROOT,
                        "test_session_lifecycle_external_channel",
                    ),
                    _database_resource(
                        "external_channel_access_grants",
                        SessionLifecycleResourceClassification.LIFECYCLE_ROOT,
                        "test_session_lifecycle_external_channel",
                    ),
                    _database_resource(
                        "external_channel_works",
                        SessionLifecycleResourceClassification.LIFECYCLE_ROOT,
                        "test_session_lifecycle_external_channel",
                    ),
                    _database_resource(
                        "external_channel_actions",
                        SessionLifecycleResourceClassification.LIFECYCLE_ROOT,
                        "test_session_lifecycle_external_channel",
                    ),
                    _database_resource(
                        "external_channel_delivery_attempts",
                        SessionLifecycleResourceClassification.LIFECYCLE_ROOT,
                        "test_session_lifecycle_external_channel",
                    ),
                ),
                archive_policy=SessionLifecycleTransitionPolicy.VALIDATE,
                restore_policy=SessionLifecycleTransitionPolicy.PRESERVE,
                purge_policy=SessionLifecyclePurgePolicy.REQUIRED,
            ),
            SessionLifecycleParticipantDefinition(
                key="session.broker-state",
                policy_version=1,
                dependencies=("session.execution",),
                owned_resources=(
                    _external_resource(
                        "session-broker-state",
                        "test_session_lifecycle_broker_state_participant",
                    ),
                ),
                archive_policy=SessionLifecycleTransitionPolicy.PRESERVE,
                restore_policy=SessionLifecycleTransitionPolicy.PRESERVE,
                purge_policy=SessionLifecyclePurgePolicy.REQUIRED,
            ),
            SessionLifecycleParticipantDefinition(
                key="session.model-files",
                policy_version=1,
                dependencies=(),
                owned_resources=(
                    _database_resource(
                        "model_files",
                        SessionLifecycleResourceClassification.LIFECYCLE_ROOT,
                        "test_session_lifecycle_model_files",
                    ),
                    _external_resource(
                        "model-file-blobs",
                        "test_session_lifecycle_model_files",
                    ),
                ),
                archive_policy=SessionLifecycleTransitionPolicy.PRESERVE,
                restore_policy=SessionLifecycleTransitionPolicy.PRESERVE,
                purge_policy=SessionLifecyclePurgePolicy.REQUIRED,
            ),
            SessionLifecycleParticipantDefinition(
                key="session.artifacts",
                policy_version=1,
                dependencies=("session.model-files",),
                owned_resources=(
                    _database_resource(
                        "artifacts",
                        SessionLifecycleResourceClassification.LIFECYCLE_ROOT,
                        "test_session_lifecycle_artifacts",
                    ),
                    _external_resource(
                        "artifact-blobs",
                        "test_session_lifecycle_artifacts",
                    ),
                ),
                archive_policy=SessionLifecycleTransitionPolicy.PRESERVE,
                restore_policy=SessionLifecycleTransitionPolicy.PRESERVE,
                purge_policy=SessionLifecyclePurgePolicy.REQUIRED,
            ),
            SessionLifecycleParticipantDefinition(
                key="session.exchange-files",
                policy_version=1,
                dependencies=("session.artifacts",),
                owned_resources=(
                    _database_resource(
                        "exchange_files",
                        SessionLifecycleResourceClassification.LIFECYCLE_ROOT,
                        "test_session_lifecycle_exchange_files",
                    ),
                    _external_resource(
                        "exchange-file-blobs",
                        "test_session_lifecycle_exchange_files",
                    ),
                ),
                archive_policy=SessionLifecycleTransitionPolicy.PRESERVE,
                restore_policy=SessionLifecycleTransitionPolicy.PRESERVE,
                purge_policy=SessionLifecyclePurgePolicy.REQUIRED,
            ),
            SessionLifecycleParticipantDefinition(
                key="session.git-worktrees",
                policy_version=1,
                dependencies=("session.exchange-files",),
                owned_resources=(
                    _database_resource(
                        "session_agent_context_git_worktrees",
                        SessionLifecycleResourceClassification.LIFECYCLE_ROOT,
                        "test_session_lifecycle_git_worktrees",
                    ),
                    _external_resource(
                        "session-git-worktrees",
                        "test_session_lifecycle_git_worktrees",
                    ),
                ),
                archive_policy=SessionLifecycleTransitionPolicy.PRESERVE,
                restore_policy=SessionLifecycleTransitionPolicy.PRESERVE,
                purge_policy=SessionLifecyclePurgePolicy.REQUIRED,
            ),
            SessionLifecycleParticipantDefinition(
                key="session.context",
                policy_version=1,
                dependencies=("session.git-worktrees",),
                owned_resources=(
                    _database_resource(
                        "session_agents",
                        SessionLifecycleResourceClassification.LIFECYCLE_ROOT,
                        "test_session_lifecycle_context_finalization",
                    ),
                    _database_resource(
                        "session_agent_contexts",
                        SessionLifecycleResourceClassification.LIFECYCLE_ROOT,
                        "test_session_lifecycle_context_finalization",
                    ),
                    _database_resource(
                        "session_agent_context_projects",
                        SessionLifecycleResourceClassification.LIFECYCLE_ROOT,
                        "test_session_lifecycle_context_finalization",
                    ),
                ),
                archive_policy=SessionLifecycleTransitionPolicy.PRESERVE,
                restore_policy=SessionLifecycleTransitionPolicy.PRESERVE,
                purge_policy=SessionLifecyclePurgePolicy.REQUIRED,
            ),
            SessionLifecycleParticipantDefinition(
                key="session.conversation-data",
                policy_version=1,
                dependencies=(),
                owned_resources=(
                    _database_resource(
                        "events",
                        SessionLifecycleResourceClassification.PURE_DATABASE_CHILD,
                        "test_session_lifecycle_conversation_data",
                    ),
                    _database_resource(
                        "agent_runs",
                        SessionLifecycleResourceClassification.PURE_DATABASE_CHILD,
                        "test_session_lifecycle_conversation_data",
                    ),
                    _database_resource(
                        "input_buffers",
                        SessionLifecycleResourceClassification.PURE_DATABASE_CHILD,
                        "test_session_lifecycle_conversation_data",
                    ),
                    _database_resource(
                        "action_executions",
                        SessionLifecycleResourceClassification.PURE_DATABASE_CHILD,
                        "test_session_lifecycle_conversation_data",
                    ),
                ),
                archive_policy=SessionLifecycleTransitionPolicy.PRESERVE,
                restore_policy=SessionLifecycleTransitionPolicy.PRESERVE,
                purge_policy=SessionLifecyclePurgePolicy.DECLARED_CASCADE,
            ),
            SessionLifecycleParticipantDefinition(
                key="session.toolkit-state",
                policy_version=1,
                dependencies=(),
                owned_resources=(
                    _database_resource(
                        "toolkit_states",
                        SessionLifecycleResourceClassification.PURE_DATABASE_CHILD,
                        "test_session_lifecycle_toolkit_state",
                    ),
                ),
                archive_policy=SessionLifecycleTransitionPolicy.PRESERVE,
                restore_policy=SessionLifecycleTransitionPolicy.PRESERVE,
                purge_policy=SessionLifecyclePurgePolicy.DECLARED_CASCADE,
            ),
        )
    )


def get_session_lifecycle_ownership_manifest() -> SessionLifecycleOwnershipManifest:
    """Return catalog coverage for participants and orchestrator-owned root state."""
    registry = get_session_lifecycle_registry()
    return SessionLifecycleOwnershipManifest(
        resources=(
            _database_resource(
                "agent_sessions",
                SessionLifecycleResourceClassification.ORCHESTRATOR_ROOT,
                "test_session_lifecycle_finalization",
            ),
            *(
                resource
                for participant in registry.participants
                for resource in participant.owned_resources
            ),
        )
    )


def get_session_lifecycle_orchestrator() -> SessionLifecycleOrchestrator:
    """Return the application-composed session lifecycle orchestrator."""
    return SessionLifecycleOrchestrator(registry=get_session_lifecycle_registry())
