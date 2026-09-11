"""Subagent mailbox and capacity E2E tests."""

from .test_subagents import (
    SubagentCapacityScenarios,
    barrier_subagent_setup,
    shared_subagent_setup,
)

E2E_PLANNER_FALLBACK_WEIGHT = 20.0

__all__ = [
    "barrier_subagent_setup",
    "shared_subagent_setup",
]


class TestSubagentCapacity(SubagentCapacityScenarios):
    """Collect the reusable Subagent mailbox and capacity scenarios."""
