"""Session-scoped Goal domain models."""

from typing import Literal, Self

from azents.core.toolkit_state import ToolkitStateModel

GOAL_TOOLKIT_NAMESPACE = "goal"
GOAL_TOOLKIT_STATE_NAME = "goal"
GOAL_STATE_SCHEMA_VERSION = 1
GoalStatus = Literal["active", "paused", "blocked", "complete"]
GoalUpdateStatus = Literal["complete", "blocked"]


class GoalState(ToolkitStateModel):
    """Session-scoped Goal Toolkit State payload."""

    schema_version: int = GOAL_STATE_SCHEMA_VERSION
    objective: str | None = None
    status: GoalStatus | None = None
    created_at: str | None = None
    updated_at: str | None = None


class GoalStateSnapshot(ToolkitStateModel):
    """Goal state exposed to Chat live snapshot."""

    schema_version: int = GOAL_STATE_SCHEMA_VERSION
    objective: str | None = None
    status: GoalStatus | None = None
    created_at: str | None = None
    updated_at: str | None = None

    @classmethod
    def from_state(cls, state: GoalState) -> Self:
        """Create snapshot from stored state."""
        return cls(
            objective=state.objective,
            status=state.status,
            created_at=state.created_at,
            updated_at=state.updated_at,
        )
