"""Effective Terminal policy resolver tests."""

import dataclasses

import pytest

from azents.core.enums import AgentRuntimeCapability
from azents.core.runtime_profile import RuntimeProfileLifecycle
from azents.services.terminal_policy.data import (
    TerminalPolicyDeniedScope,
    TerminalPolicyEvidence,
    TerminalPolicyReasonCode,
)
from azents.services.terminal_policy.service import TerminalPolicyResolver


def _evidence() -> TerminalPolicyEvidence:
    return TerminalPolicyEvidence(
        access_allowed=True,
        session_available=True,
        agent_id="agent-1",
        agent_terminal_enabled=True,
        runtime_capability=AgentRuntimeCapability.MANAGED,
        runtime_id="runtime-1",
        runtime_active=True,
        desired_generation=4,
        infrastructure_profile_id="infrastructure-1",
        infrastructure_profile_version=2,
        infrastructure_profile_lifecycle=RuntimeProfileLifecycle.ACTIVE,
        infrastructure_profile_available=True,
        infrastructure_terminal_enabled=True,
        workspace_profile_id="workspace-profile-1",
        workspace_profile_version=3,
        workspace_profile_lifecycle=RuntimeProfileLifecycle.ACTIVE,
        workspace_profile_available=True,
        workspace_terminal_enabled=True,
        runner_generation=5,
        expected_runner_generation=5,
        runner_active=True,
        runner_capabilities=frozenset({"terminal.v1"}),
    )


def test_resolver_accepts_only_complete_current_authority() -> None:
    resolved = TerminalPolicyResolver().resolve(_evidence())

    assert resolved.available is True
    assert resolved.reason_code is None
    assert resolved.sources.infrastructure_profile_version == 2
    assert resolved.sources.workspace_profile_version == 3
    assert resolved.desired_generation == 4
    assert resolved.runner_generation == 5


@pytest.mark.parametrize(
    ("change", "reason", "scope"),
    [
        (
            {"access_allowed": False},
            TerminalPolicyReasonCode.ACCESS_DENIED,
            TerminalPolicyDeniedScope.ACCESS,
        ),
        (
            {"runtime_capability": AgentRuntimeCapability.NONE},
            TerminalPolicyReasonCode.RUNTIME_FREE_AGENT,
            TerminalPolicyDeniedScope.RUNTIME,
        ),
        (
            {"infrastructure_terminal_enabled": False},
            TerminalPolicyReasonCode.INFRASTRUCTURE_TERMINAL_DISABLED,
            TerminalPolicyDeniedScope.PROVIDER_PROFILE,
        ),
        (
            {"workspace_terminal_enabled": False},
            TerminalPolicyReasonCode.WORKSPACE_TERMINAL_DISABLED,
            TerminalPolicyDeniedScope.WORKSPACE_PROFILE,
        ),
        (
            {"agent_terminal_enabled": False},
            TerminalPolicyReasonCode.AGENT_TERMINAL_DISABLED,
            TerminalPolicyDeniedScope.AGENT,
        ),
        (
            {"runtime_active": False},
            TerminalPolicyReasonCode.RUNTIME_INACTIVE,
            TerminalPolicyDeniedScope.RUNTIME,
        ),
        (
            {"runner_generation": 6},
            TerminalPolicyReasonCode.RUNNER_GENERATION_STALE,
            TerminalPolicyDeniedScope.RUNNER,
        ),
        (
            {"runner_capabilities": frozenset()},
            TerminalPolicyReasonCode.RUNNER_TERMINAL_UNSUPPORTED,
            TerminalPolicyDeniedScope.RUNNER,
        ),
    ],
)
def test_resolver_fails_closed_in_fixed_order(
    change: dict[str, object],
    reason: TerminalPolicyReasonCode,
    scope: TerminalPolicyDeniedScope,
) -> None:
    resolved = TerminalPolicyResolver().resolve(
        dataclasses.replace(_evidence(), **change)
    )

    assert resolved.available is False
    assert resolved.reason_code is reason
    assert resolved.denied_scope is scope


def test_missing_profile_chain_precedes_raw_flags() -> None:
    resolved = TerminalPolicyResolver().resolve(
        dataclasses.replace(
            _evidence(),
            infrastructure_profile_id=None,
            infrastructure_terminal_enabled=False,
        )
    )

    assert (
        resolved.reason_code
        is TerminalPolicyReasonCode.INFRASTRUCTURE_PROFILE_UNAVAILABLE
    )
