"""Concrete Routine persistence collaborators for database integration fixtures."""

from azents.repos.routine.authority import RoutineExecutionAuthorityRepository
from azents.repos.routine.execution import RoutineExecutionRepository
from azents.repos.routine.lifecycle import RoutineLifecycleRepository
from azents.repos.routine.state import RoutineStateRepository
from azents.repos.toolkit_state import ToolkitStateRepository


def make_test_routine_authority() -> RoutineExecutionAuthorityRepository:
    """Use real Toolkit State decoding without external services or callbacks."""
    return RoutineExecutionAuthorityRepository(
        states=RoutineStateRepository(toolkit_states=ToolkitStateRepository())
    )


def make_test_routine_lifecycle() -> RoutineLifecycleRepository:
    """Compose the exact production lifecycle repository and current-input proof."""
    authority = make_test_routine_authority()
    return RoutineLifecycleRepository(states=authority.states, authority=authority)


def make_test_routine_execution() -> RoutineExecutionRepository:
    """Bind actual per-occurrence state to existing ordinary Run transitions."""
    return RoutineExecutionRepository(states=make_test_routine_authority().states)
