"""Tests for System Admin API response conversion."""

import datetime

from azents.core.enums import SystemUserRole
from azents.services.system_user_role.data import SystemUserRoleAssignmentOutput

from .data import SystemUserRoleAssignmentResponse


def test_convert_service_assignment_to_api_response() -> None:
    granted_at = datetime.datetime(2026, 7, 13, tzinfo=datetime.UTC)
    response = SystemUserRoleAssignmentResponse.convert_output(
        SystemUserRoleAssignmentOutput(
            user_id="user-id",
            role=SystemUserRole.SYSTEM_ADMIN,
            granted_by_user_id=None,
            granted_at=granted_at,
        )
    )

    assert response == SystemUserRoleAssignmentResponse(
        user_id="user-id",
        role=SystemUserRole.SYSTEM_ADMIN,
        granted_by_user_id=None,
        granted_at=granted_at,
    )
