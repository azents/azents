"""Tests for system User role service data conversion."""

import datetime

from azents.core.enums import SystemUserRole
from azents.repos.system_user_role.data import SystemUserRoleAssignment

from .data import SystemUserRoleAssignmentOutput


def test_convert_repository_assignment_to_service_output() -> None:
    granted_at = datetime.datetime(2026, 7, 13, tzinfo=datetime.UTC)
    output = SystemUserRoleAssignmentOutput.convert_from(
        SystemUserRoleAssignment(
            user_id="user-id",
            role=SystemUserRole.SYSTEM_ADMIN,
            granted_by_user_id=None,
            granted_at=granted_at,
        )
    )

    assert output == SystemUserRoleAssignmentOutput(
        user_id="user-id",
        role=SystemUserRole.SYSTEM_ADMIN,
        granted_by_user_id=None,
        granted_at=granted_at,
    )
