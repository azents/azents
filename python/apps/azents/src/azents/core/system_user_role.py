"""Pure instance-wide User role mutation errors."""

import dataclasses

from azents.core.enums import SystemUserRole


@dataclasses.dataclass(frozen=True)
class SystemUserNotFound:
    """Target User does not exist."""

    user_id: str


@dataclasses.dataclass(frozen=True)
class SystemRoleAssignmentNotFound:
    """Target role assignment does not exist."""

    user_id: str
    role: SystemUserRole


@dataclasses.dataclass(frozen=True)
class LastSystemAdmin:
    """Operation would remove the final system administrator."""

    user_id: str
