"""Fail-closed effective Terminal policy resolution."""

from azents_runtime_control.runner_terminal import RUNNER_TERMINAL_CAPABILITY

from azents.core.enums import AgentRuntimeCapability
from azents.core.runtime_profile import RuntimeProfileLifecycle
from azents.services.terminal_policy.data import (
    TerminalPolicyDeniedScope,
    TerminalPolicyEvidence,
    TerminalPolicyReasonCode,
    TerminalPolicyResolution,
    TerminalPolicySourceVersions,
)


class TerminalPolicyResolver:
    """Resolve current Terminal permission from explicit source evidence."""

    def resolve(self, evidence: TerminalPolicyEvidence) -> TerminalPolicyResolution:
        """Evaluate the fixed fail-closed policy order."""
        sources = TerminalPolicySourceVersions(
            agent_id=evidence.agent_id,
            infrastructure_profile_id=evidence.infrastructure_profile_id,
            infrastructure_profile_version=(evidence.infrastructure_profile_version),
            workspace_profile_id=evidence.workspace_profile_id,
            workspace_profile_version=evidence.workspace_profile_version,
        )

        def denied(
            reason: TerminalPolicyReasonCode,
            scope: TerminalPolicyDeniedScope,
        ) -> TerminalPolicyResolution:
            return TerminalPolicyResolution(
                available=False,
                reason_code=reason,
                denied_scope=scope,
                sources=sources,
                runtime_id=evidence.runtime_id,
                desired_generation=evidence.desired_generation,
                runner_generation=evidence.runner_generation,
            )

        if not evidence.access_allowed:
            return denied(
                TerminalPolicyReasonCode.ACCESS_DENIED,
                TerminalPolicyDeniedScope.ACCESS,
            )
        if not evidence.session_available:
            return denied(
                TerminalPolicyReasonCode.SESSION_UNAVAILABLE,
                TerminalPolicyDeniedScope.SESSION,
            )
        if evidence.runtime_capability is not AgentRuntimeCapability.MANAGED:
            return denied(
                TerminalPolicyReasonCode.RUNTIME_FREE_AGENT,
                TerminalPolicyDeniedScope.RUNTIME,
            )
        if evidence.runtime_id is None or evidence.desired_generation is None:
            return denied(
                TerminalPolicyReasonCode.RUNTIME_UNAVAILABLE,
                TerminalPolicyDeniedScope.RUNTIME,
            )
        if (
            evidence.infrastructure_profile_id is None
            or evidence.infrastructure_profile_version is None
            or evidence.infrastructure_profile_lifecycle
            is not RuntimeProfileLifecycle.ACTIVE
            or not evidence.infrastructure_profile_available
            or evidence.infrastructure_terminal_enabled is None
        ):
            return denied(
                TerminalPolicyReasonCode.INFRASTRUCTURE_PROFILE_UNAVAILABLE,
                TerminalPolicyDeniedScope.PROVIDER_PROFILE,
            )
        if (
            evidence.workspace_profile_id is None
            or evidence.workspace_profile_version is None
            or evidence.workspace_profile_lifecycle
            is not RuntimeProfileLifecycle.ACTIVE
            or not evidence.workspace_profile_available
            or evidence.workspace_terminal_enabled is None
        ):
            return denied(
                TerminalPolicyReasonCode.WORKSPACE_PROFILE_UNAVAILABLE,
                TerminalPolicyDeniedScope.WORKSPACE_PROFILE,
            )
        if not evidence.infrastructure_terminal_enabled:
            return denied(
                TerminalPolicyReasonCode.INFRASTRUCTURE_TERMINAL_DISABLED,
                TerminalPolicyDeniedScope.PROVIDER_PROFILE,
            )
        if not evidence.workspace_terminal_enabled:
            return denied(
                TerminalPolicyReasonCode.WORKSPACE_TERMINAL_DISABLED,
                TerminalPolicyDeniedScope.WORKSPACE_PROFILE,
            )
        if not evidence.agent_terminal_enabled:
            return denied(
                TerminalPolicyReasonCode.AGENT_TERMINAL_DISABLED,
                TerminalPolicyDeniedScope.AGENT,
            )
        if not evidence.runtime_active:
            return denied(
                TerminalPolicyReasonCode.RUNTIME_INACTIVE,
                TerminalPolicyDeniedScope.RUNTIME,
            )
        if not evidence.runner_active or evidence.runner_generation is None:
            return denied(
                TerminalPolicyReasonCode.RUNNER_UNAVAILABLE,
                TerminalPolicyDeniedScope.RUNNER,
            )
        if evidence.runner_generation != evidence.expected_runner_generation:
            return denied(
                TerminalPolicyReasonCode.RUNNER_GENERATION_STALE,
                TerminalPolicyDeniedScope.RUNNER,
            )
        if RUNNER_TERMINAL_CAPABILITY not in evidence.runner_capabilities:
            return denied(
                TerminalPolicyReasonCode.RUNNER_TERMINAL_UNSUPPORTED,
                TerminalPolicyDeniedScope.RUNNER,
            )
        return TerminalPolicyResolution(
            available=True,
            reason_code=None,
            denied_scope=None,
            sources=sources,
            runtime_id=evidence.runtime_id,
            desired_generation=evidence.desired_generation,
            runner_generation=evidence.runner_generation,
        )
