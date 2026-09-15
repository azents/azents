"""Runtime Web Gateway transport authority tests."""

from datetime import UTC, datetime

import pytest

from azents.core.enums import (
    RuntimeDesiredState,
    RuntimeProviderObservedState,
    RuntimeRunnerState,
)
from azents.repos.agent_runtime.data import AgentRuntime
from azents.services.runtime_web.gateway_authority import (
    _runtime_ready,
)


def _runtime(**updates: object) -> AgentRuntime:
    now = datetime(2026, 9, 13, tzinfo=UTC)
    runtime = AgentRuntime(
        id="t" * 32,
        workspace_id="w" * 32,
        agent_id="a" * 32,
        terminal_delete_acknowledgement_kind=None,
        desired_state=RuntimeDesiredState.RUNNING,
        desired_generation=552,
        provider_observed_state=RuntimeProviderObservedState.RUNNING,
        provider_observed_generation=552,
        runner_state=RuntimeRunnerState.READY,
        runner_generation=987_654_321,
        created_at=now,
        updated_at=now,
    )
    return runtime.model_copy(update=updates)


def test_runtime_ready_accepts_independent_kubernetes_runner_generation() -> None:
    """Accept a ready Runner whose generation is independent from lifecycle."""
    assert _runtime_ready(_runtime())


@pytest.mark.parametrize(
    "updates",
    [
        {"desired_state": RuntimeDesiredState.STOPPED},
        {"provider_observed_state": RuntimeProviderObservedState.STOPPED},
        {"provider_observed_generation": 551},
        {"runner_state": RuntimeRunnerState.UNKNOWN},
        {"runner_generation": 0},
    ],
)
def test_runtime_ready_rejects_stale_or_missing_runtime_evidence(
    updates: dict[str, object],
) -> None:
    """Reject stale Provider evidence and unavailable Runner connections."""
    assert not _runtime_ready(_runtime(**updates))
