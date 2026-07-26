"""Runtime Execution v1 Admin API tests."""

import datetime

from fastapi.routing import APIRoute

from azents.api.admin.runtime_execution.v1.data import (
    RuntimeExecutionPolicyAuditEventResponse,
)
from azents.app import create_dummy_admin_app
from azents.core.auth.deps import get_system_admin
from azents.core.runtime_execution_policy import (
    RuntimeExecutionAuditEventType,
    RuntimeExecutionChangeDirection,
    RuntimeExecutionManagementLayer,
)
from azents.repos.runtime_execution_policy.data import (
    RuntimeExecutionPolicyAuditEvent,
)


def test_admin_routes_are_mounted_under_system_admin_authority() -> None:
    """Every Runtime Execution Admin route requires a System Admin."""
    app = create_dummy_admin_app()
    routes = [
        route
        for route in app.routes
        if isinstance(route, APIRoute)
        and route.path.startswith("/runtime-execution/v1")
    ]

    assert len(routes) == 8
    assert {route.path for route in routes} >= {
        "/runtime-execution/v1/platform-policy",
        "/runtime-execution/v1/profiles",
        "/runtime-execution/v1/profiles/{profile_id}",
        "/runtime-execution/v1/profiles/{profile_id}/retire",
        "/runtime-execution/v1/audit-events",
    }
    for route in routes:
        assert any(
            dependency.call is get_system_admin
            for dependency in route.dependant.dependencies
        )


def test_audit_response_does_not_serialize_metadata_payload() -> None:
    """Even unexpected stored metadata is absent from the Admin response."""
    event = RuntimeExecutionPolicyAuditEvent(
        id="event-1",
        event_type=RuntimeExecutionAuditEventType.PROFILE_REPLACED,
        management_layer=RuntimeExecutionManagementLayer.PROFILE,
        target_id="profile-1",
        correlation_id="correlation-1",
        classification=RuntimeExecutionChangeDirection.RESTRICTIVE,
        changed_paths=("container_run.enabled",),
        impact_counts={"agents": 1},
        reason_code="operator_replace",
        outcome_code="applied",
        metadata={"credential": "must-not-leak"},
        workspace_id=None,
        agent_id=None,
        runtime_id=None,
        actor_user_id="user-1",
        actor_workspace_user_id=None,
        system_authority=False,
        before_digest="a" * 64,
        after_digest="b" * 64,
        created_at=datetime.datetime(2026, 7, 26, tzinfo=datetime.UTC),
    )

    payload = RuntimeExecutionPolicyAuditEventResponse.convert_from(event).model_dump(
        mode="json"
    )

    assert "metadata" not in payload
    assert "must-not-leak" not in str(payload)
