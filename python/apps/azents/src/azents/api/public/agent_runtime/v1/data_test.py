"""Agent Runtime configuration response tests."""

import datetime

from azents.api.public.agent_runtime.v1.data import (
    AgentRuntimeConfigurationStatusResponse,
)
from azents.core.runtime_profile import RuntimeConfigurationResolutionStatus
from azents.repos.runtime_profile.data import RuntimeConfigurationRevision
from azents.services.agent_runtime.lifecycle_data import (
    AgentRuntimeConfigurationStatus,
    RuntimeContainmentStatus,
)


def _revision() -> RuntimeConfigurationRevision:
    return RuntimeConfigurationRevision(
        id="revision-1",
        runtime_id="runtime-1",
        provider_id="provider-1",
        provider_capability_revision_id="capability-1",
        infrastructure_profile_id="infrastructure-1",
        infrastructure_profile_version=2,
        workspace_runtime_profile_id="profile-1",
        workspace_runtime_profile_version=3,
        agent_selection_version=4,
        resolution_status=RuntimeConfigurationResolutionStatus.READY,
        reason_code=None,
        required_capabilities=("runtime.resources",),
        missing_capabilities=(),
        resolved_configuration={"secret_provider_detail": "not-public"},
        source_trace={"internal_version": 1},
        digest="a" * 64,
        target_desired_generation=5,
        provider_reported_digest=None,
        runner_reported_digest=None,
        provider_acknowledged_at=None,
        runtime_observed_at=None,
        created_at=datetime.datetime(2026, 7, 30, tzinfo=datetime.UTC),
    )


def _all_keys(value: object) -> set[str]:
    if isinstance(value, dict):
        return {key for key in value if isinstance(key, str)} | {
            key for child in value.values() for key in _all_keys(child)
        }
    if isinstance(value, list):
        return {key for child in value for key in _all_keys(child)}
    return set()


def test_configuration_status_exposes_only_safe_revision_evidence() -> None:
    """Runtime status omits resolved infrastructure details and source traces."""
    revision = _revision()
    payload = AgentRuntimeConfigurationStatusResponse.convert_from(
        AgentRuntimeConfigurationStatus(
            status="applied",
            desired=revision,
            applied=revision,
            containment=RuntimeContainmentStatus(
                enabled=True,
                applied=True,
                recreation_required=False,
                nested_docker_available=False,
                runtime_available=True,
                availability_reason_code=None,
            ),
        )
    ).model_dump(mode="json")

    assert payload["status"] == "applied"
    assert payload["desired"]["workspace_runtime_profile_id"] == "profile-1"
    keys = _all_keys(payload)
    assert keys.isdisjoint(
        {
            "resolved_configuration",
            "source_trace",
            "encrypted_secrets",
            "secret_metadata",
            "provider_config",
        }
    )
