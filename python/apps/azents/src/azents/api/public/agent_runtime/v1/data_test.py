"""Agent Runtime configuration response tests."""

import datetime

import pytest
from pydantic import ValidationError

from azents.api.public.agent_runtime.v1.data import (
    AgentRuntimeConfigurationStatusResponse,
    AgentRuntimeRemovalProgressResponse,
    RemoveAgentRuntimeRequest,
)
from azents.core.enums import (
    AgentRuntimeRemovalStage,
    AgentRuntimeRemovalStatus,
)
from azents.core.runtime_profile import RuntimeConfigurationResolutionStatus
from azents.repos.agent_runtime_removal.data import AgentRuntimeRemovalOperation
from azents.repos.runtime_profile.data import RuntimeConfigurationRevision
from azents.services.agent_runtime.lifecycle_data import (
    AgentRuntimeConfigurationStatus,
    RuntimeContainmentStatus,
)
from azents.services.agent_runtime.service import AgentRuntimeService


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
