"""Detached result of one atomic system-role grant."""

import dataclasses

from azents.repos.system_user_role.data import SystemUserRoleAssignment


@dataclasses.dataclass(frozen=True)
class SystemUserRoleGrantOutcome:
    """Assignment and creation fact observed in the same transaction."""

    assignment: SystemUserRoleAssignment
    created: bool
