"""Agent Runtime configuration response tests."""

import datetime

import pytest
from pydantic import ValidationError

from azents.api.public.agent_runtime.v1.data import (
    AgentRuntimeConfigurationStatusResponse,
    AgentRuntimeRawStateResponse,
    AgentRuntimeRemovalProgressResponse,
    RemoveAgentRuntimeRequest,
)
from azents.core.enums import (
    AgentRuntimeRemovalStage,
    AgentRuntimeRemovalStatus,
)
from azents.core.runtime_profile import (
    RuntimeConfigurationDocument,
    RuntimeConfigurationStateStatus,
)
from azents.repos.agent_runtime_removal.data import AgentRuntimeRemovalOperation
from azents.repos.runtime_profile.data import (
    RuntimeConfigurationAppliedSlot,
    RuntimeConfigurationSlot,
)
from azents.services.agent_runtime.lifecycle_data import AgentRuntimeConfigurationStatus
from azents.services.agent_runtime.service import AgentRuntimeService


def _document() -> RuntimeConfigurationDocument:
    return RuntimeConfigurationDocument(
        schema_version=1,
        source_trace={"internal_version": 1},
        provider_id="provider-1",
        provider_capability_revision_id="capability-1",
        infrastructure_profile_id="infrastructure-1",
        infrastructure_profile_version=2,
        workspace_runtime_profile_id="profile-1",
        workspace_runtime_profile_version=3,
        agent_selection_version=4,
        required_capabilities=("runtime.resources",),
        missing_capabilities=(),
        resolved_configuration={
            "effective_profile": {
                "profile_kind": "kubernetes_pod",
                "contract_family": "kubernetes.pod-profile",
                "schema_version": 3,
                "runner_resources": {
                    "cpu_request_millicores": None,
                    "cpu_limit_millicores": None,
                    "memory_request_bytes": None,
                    "memory_limit_bytes": None,
                },
                "workspace_volume": {
                    "storage_class_name": "standard",
                    "storage_request_bytes": 1,
                },
                "network_access": {
                    "mode": "proxy_required",
                    "allowed_cidrs": ["10.0.0.0/8"],
                    "denied_cidrs": ["10.1.0.0/16"],
                    "domain_policy": {
                        "mode": "allowlist",
                        "allowed_domains": ["*.example.com"],
                        "denied_domains": ["blocked.example.com"],
                    },
                },
                "service_account_name": None,
                "scheduling": {
                    "node_selector": {},
                    "tolerations": [],
                },
                "dind": None,
            },
            "secret_provider_detail": "not-public",
            "network_enforcement": {
                "runtime_network_policy_name": "private-policy-name",
                "proxy_service_cluster_ip": "10.96.0.10",
                "ca_private_key": "private-key",
            },
        },
    )


def _all_keys(value: object) -> set[str]:
    if isinstance(value, dict):
        return {key for key in value if isinstance(key, str)} | {
            key for child in value.values() for key in _all_keys(child)
        }
    if isinstance(value, list):
        return {key for child in value for key in _all_keys(child)}
    return set()


def test_configuration_status_exposes_only_bounded_current_state() -> None:
    """Runtime status omits resolved infrastructure details and source traces."""
    document = _document()
    desired = RuntimeConfigurationSlot(
        sequence=6,
        status=RuntimeConfigurationStateStatus.READY,
        target_generation=5,
        digest="a" * 64,
        document=document,
        reason_code=None,
        provider_reported_digest="a" * 64,
        runner_reported_digest="a" * 64,
        provider_acknowledged_at=datetime.datetime(2026, 7, 30, tzinfo=datetime.UTC),
        runner_observed_at=datetime.datetime(2026, 7, 30, tzinfo=datetime.UTC),
    )
    applied = RuntimeConfigurationAppliedSlot(
        sequence=6,
        target_generation=5,
        digest="a" * 64,
        document=document,
        applied_at=datetime.datetime(2026, 7, 30, tzinfo=datetime.UTC),
    )
    payload = AgentRuntimeConfigurationStatusResponse.convert_from(
        AgentRuntimeConfigurationStatus(
            status="applied",
            desired=desired,
            applied=applied,
        )
    ).model_dump(mode="json")

    assert payload["status"] == "applied"
    assert payload["desired"]["sequence"] == 6
    assert payload["desired"]["status"] == "ready"
    assert payload["desired"]["target_generation"] == 5
    assert payload["desired"]["workspace_runtime_profile_id"] == "profile-1"
    assert payload["desired"]["network"] == {
        "mode": "proxy_required",
        "domain_mode": "allowlist",
        "protocol_summary": "http_https_websocket",
        "https_inspection": True,
        "enforcement_status": "applied",
    }
    assert payload["applied"]["network"] == payload["desired"]["network"]
    assert payload["applied"]["applied_at"] is not None
    keys = _all_keys(payload)
    assert keys.isdisjoint(
        {
            "resolved_configuration",
            "source_trace",
            "encrypted_secrets",
            "secret_metadata",
            "provider_config",
            "network_enforcement",
            "runtime_network_policy_name",
            "proxy_service_cluster_ip",
            "ca_private_key",
        }
    )


def test_unconfigured_state_omits_source_scalars_and_digest() -> None:
    """An unconfigured desired slot has no source or resolved target evidence."""
    payload = AgentRuntimeConfigurationStatusResponse.convert_from(
        AgentRuntimeConfigurationStatus(
            status="profile_required",
            desired=RuntimeConfigurationSlot(
                sequence=7,
                status=RuntimeConfigurationStateStatus.UNCONFIGURED,
                target_generation=6,
                digest=None,
                document=None,
                reason_code="runtime_profile_required",
                provider_reported_digest=None,
                runner_reported_digest=None,
                provider_acknowledged_at=None,
                runner_observed_at=None,
            ),
            applied=None,
        )
    ).model_dump(mode="json")

    desired = payload["desired"]
    assert desired["status"] == "unconfigured"
    assert desired["digest"] is None
    assert desired["provider_id"] is None
    assert desired["required_capabilities"] is None
    assert desired["reason_code"] == "runtime_profile_required"
    assert desired["network"] is None


def test_raw_state_replaces_direct_configuration_pointers() -> None:
    """Raw Runtime state exposes only the Runtime-owned sequence high-water mark."""
    fields = set(AgentRuntimeRawStateResponse.model_fields)

    assert "configuration_sequence" in fields
    assert fields.isdisjoint(
        {
            "infrastructure_profile_id",
            "workspace_runtime_profile_id",
            "desired_runtime_configuration_revision_id",
            "applied_runtime_configuration_revision_id",
        }
    )


def test_remove_request_requires_true_without_boolean_enum_schema() -> None:
    """Removal confirmation stays strict without breaking generated clients."""
    request = RemoveAgentRuntimeRequest(
        expected_capability_version=1,
        expected_runtime_profile_selection_version=1,
        idempotency_key="remove-request",
        confirmed=True,
    )

    assert request.confirmed is True
    with pytest.raises(ValidationError, match="explicitly confirmed"):
        RemoveAgentRuntimeRequest(
            expected_capability_version=1,
            expected_runtime_profile_selection_version=1,
            idempotency_key="remove-request",
            confirmed=False,
        )

    confirmed_schema = RemoveAgentRuntimeRequest.model_json_schema()["properties"][
        "confirmed"
    ]
    assert confirmed_schema["type"] == "boolean"
    assert "enum" not in confirmed_schema


def test_removal_progress_omits_private_and_internal_authority_fields() -> None:
    """Public removal progress excludes actor, request, lease, and cursor data."""
    now = datetime.datetime(2026, 8, 10, tzinfo=datetime.UTC)
    operation = AgentRuntimeRemovalOperation(
        id="operation-1",
        agent_id="agent-1",
        workspace_id="workspace-1",
        requested_by_workspace_user_id="private-actor",
        idempotency_key="private-idempotency-key",
        expected_capability_version=1,
        committed_capability_version=2,
        agent_runtime_id="runtime-1",
        status=AgentRuntimeRemovalStatus.RUNNING,
        stage=AgentRuntimeRemovalStage.CLEANING_PRODUCT_STATE,
        confirmed_at=now,
        destructive_scope_version=1,
        active_root_session_count=2,
        active_subagent_count=3,
        active_run_count=1,
        queued_runtime_action_count=4,
        cleanup_cursor_context_id="private-session-context",
        cleanup_scanned_context_count=5,
        cleanup_invalidated_context_count=4,
        product_cleanup_completed_at=None,
        physical_deletion_required=None,
        target_terminal_delete_generation=None,
        physical_delete_requested_at=None,
        physical_delete_acknowledgement_kind=None,
        physical_delete_acknowledged_at=None,
        attempt_count=2,
        lease_owner="private-worker",
        lease_until=now,
        next_attempt_at=now,
        last_error_kind=None,
        last_error_summary=None,
        started_at=now,
        completed_at=None,
        created_at=now,
        updated_at=now,
    )

    progress = AgentRuntimeService._removal_progress_from_operation(operation)
    payload = AgentRuntimeRemovalProgressResponse.convert_from(progress).model_dump(
        mode="json"
    )

    assert set(payload).isdisjoint(
        {
            "agent_id",
            "workspace_id",
            "requested_by_workspace_user_id",
            "idempotency_key",
            "expected_capability_version",
            "committed_capability_version",
            "agent_runtime_id",
            "destructive_scope_version",
            "cleanup_cursor_context_id",
            "lease_owner",
            "lease_until",
        }
    )
