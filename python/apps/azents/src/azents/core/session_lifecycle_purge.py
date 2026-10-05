"""Pure Session lifecycle policy and neutral purge failure contracts."""

import dataclasses

from azents.core.enums import ArchivedSessionPurgeParticipantPhase
from azents.core.session_lifecycle import (
    SessionLifecycleParticipantDefinition,
    SessionLifecycleRegistry,
    SessionLifecycleTransitionContext,
)
from azents.repos.archived_session_retention.data import (
    ArchivedSessionPurgeParticipantExecution,
)


class SessionLifecyclePurgeParticipantFailure(RuntimeError):
    """A participant operation failed after durable failure attribution."""

    def __init__(
        self,
        *,
        participant_key: str,
        phase: ArchivedSessionPurgeParticipantPhase,
        error: Exception,
    ) -> None:
        """Initialize a failure with its responsible participant checkpoint."""
        self.participant_key = participant_key
        self.phase = phase
        self.error_kind = type(error).__name__
        self.error_summary = str(error) or self.error_kind
        super().__init__(self.error_summary)


class SessionLifecyclePurgeSnapshotValidationFailure(RuntimeError):
    """A participant snapshot failed validation before lifecycle side effects."""

    def __init__(
        self,
        *,
        participant_key: str | None,
        error: Exception,
    ) -> None:
        """Initialize a structured snapshot validation failure."""
        self.participant_key = participant_key
        self.phase = ArchivedSessionPurgeParticipantPhase.PENDING
        self.error_kind = type(error).__name__
        self.error_summary = str(error) or self.error_kind
        super().__init__(self.error_summary)


@dataclasses.dataclass(frozen=True)
class SessionLifecyclePurgePolicy:
    """Validate immutable participant snapshots without database handles."""

    registry: SessionLifecycleRegistry

    def _snapshot_validation_failure(
        self,
        *,
        participant_key: str | None,
        message: str,
        error: Exception | None = None,
    ) -> SessionLifecyclePurgeSnapshotValidationFailure:
        """Build one structured immutable snapshot validation failure."""
        return SessionLifecyclePurgeSnapshotValidationFailure(
            participant_key=participant_key,
            error=error or RuntimeError(message),
        )

    def _require_purge_snapshot_participants(
        self,
        executions: list[ArchivedSessionPurgeParticipantExecution],
    ) -> tuple[SessionLifecycleParticipantDefinition, ...]:
        """Resolve one complete, supported immutable participant snapshot."""
        executions_by_key = {
            execution.participant_key: execution for execution in executions
        }
        if not executions or len(executions_by_key) != len(executions):
            raise self._snapshot_validation_failure(
                participant_key=None,
                message="Purge participant snapshot is incomplete.",
            )

        snapshot_participant_keys = set(executions_by_key)
        for execution in executions:
            try:
                self.registry.require_policy_version(
                    key=execution.participant_key,
                    policy_version=execution.policy_version,
                )
            except ValueError as error:
                raise self._snapshot_validation_failure(
                    participant_key=execution.participant_key,
                    message=str(error),
                    error=error,
                ) from error
        snapshot_participants = tuple(
            participant
            for participant in self.registry.participants
            if participant.key in snapshot_participant_keys
        )
        for participant in snapshot_participants:
            missing_dependencies = tuple(
                dependency
                for dependency in participant.dependencies
                if dependency not in executions_by_key
            )
            if missing_dependencies:
                raise self._snapshot_validation_failure(
                    participant_key=participant.key,
                    message=(
                        "Purge participant snapshot is missing dependencies for "
                        f"{participant.key}: {', '.join(missing_dependencies)}."
                    ),
                )
        return snapshot_participants

    def _require_transition_context(
        self,
        context: SessionLifecycleTransitionContext,
    ) -> None:
        """Validate a locked transition context before mutating its root tree."""
        if not context.root_session_id:
            raise ValueError("Session lifecycle transition requires a root session.")
        if not context.subtree_session_ids:
            raise ValueError("Session lifecycle transition requires a nonempty tree.")
        if context.root_session_id not in context.subtree_session_ids:
            raise ValueError(
                "Session lifecycle transition root must belong to its subtree."
            )
