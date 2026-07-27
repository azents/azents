"""Agent Runtime execution-policy response tests."""

from azents.api.public.agent_runtime.v1.data import (
    AgentRuntimeExecutionPolicyStatusResponse,
)
from azents.core.runtime_execution_policy import (
    RuntimeExecutionModuleId,
    RuntimeExecutionNetworkMode,
    RuntimeExecutionPolicyLayer,
    RuntimeExecutionPolicyStatus,
    RuntimeExecutionRequiredAction,
    RuntimeExecutionStorageMode,
)
from azents.services.runtime_execution_policy.application_service import (
    RuntimeExecutionCapabilitySummary,
    RuntimeExecutionConfiguredSummary,
    RuntimeExecutionPolicyStatusProjection,
    RuntimeExecutionSnapshotSummary,
)


def _projection() -> RuntimeExecutionPolicyStatusProjection:
    capabilities = (
        RuntimeExecutionCapabilitySummary(
            module_id=RuntimeExecutionModuleId.IMAGE_BUILD,
            version=1,
            enabled=False,
        ),
        RuntimeExecutionCapabilitySummary(
            module_id=RuntimeExecutionModuleId.CONTAINER_RUN,
            version=1,
            enabled=False,
        ),
        RuntimeExecutionCapabilitySummary(
            module_id=RuntimeExecutionModuleId.COMPOSE,
            version=1,
            enabled=False,
        ),
    )
    configured = RuntimeExecutionConfiguredSummary(
        profile_id="system-standard",
        digest="a" * 64,
        capabilities=capabilities,
        storage_mode=RuntimeExecutionStorageMode.NONE,
        storage_capacity_bytes=None,
        network_mode=RuntimeExecutionNetworkMode.NONE,
    )
    applied = RuntimeExecutionSnapshotSummary(
        profile_id="system-standard",
        digest="a" * 64,
        desired_generation=3,
        capabilities=capabilities,
        storage_mode=RuntimeExecutionStorageMode.NONE,
        storage_capacity_bytes=None,
        network_mode=RuntimeExecutionNetworkMode.NONE,
    )
    return RuntimeExecutionPolicyStatusProjection(
        status=RuntimeExecutionPolicyStatus.APPLIED,
        configured=configured,
        target=applied,
        applied=applied,
        desired_generation=3,
        governing_layers={
            "image_build.enabled": RuntimeExecutionPolicyLayer.PROFILE,
        },
        reason_codes=(),
        required_action=RuntimeExecutionRequiredAction.NONE,
    )


def _all_keys(value: object) -> set[str]:
    if isinstance(value, dict):
        return set(value) | {
            key for child in value.values() for key in _all_keys(child)
        }
    if isinstance(value, list):
        return {key for child in value for key in _all_keys(child)}
    return set()


def test_execution_policy_status_exposes_only_safe_summary_fields() -> None:
    """Runtime status omits Provider topology, credentials, and raw policy data."""
    payload = AgentRuntimeExecutionPolicyStatusResponse.convert_from(
        _projection()
    ).model_dump(mode="json")

    assert payload["status"] == "applied"
    assert payload["configured"]["profile_id"] == "system-standard"
    keys = _all_keys(payload)
    assert keys.isdisjoint(
        {
            "provider_id",
            "contract_revision_id",
            "config_revision_id",
            "snapshot_id",
            "resolved_config",
            "resolved_execution_policy",
            "encrypted_secrets",
            "secret_metadata",
            "source_trace",
            "socket_path",
            "kubernetes_name",
        }
    )
