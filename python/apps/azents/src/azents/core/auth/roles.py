"""Role system.

Defines Permission mappings by WorkspaceUserRole.
"""

from azents.core.auth.permissions import Permission, Permissions
from azents.core.enums import WorkspaceUserRole

ROLE_PERMISSIONS: dict[WorkspaceUserRole, set[Permission]] = {
    WorkspaceUserRole.OWNER: {
        Permissions.ALL,
    },
    WorkspaceUserRole.MANAGER: {
        Permissions.WORKSPACE_READ,
        Permissions.WORKSPACE_USERS_READ,
        Permissions.WORKSPACE_USERS_WRITE,
        Permissions.WORKSPACE_INVITATIONS_READ,
        Permissions.WORKSPACE_INVITATIONS_WRITE,
        Permissions.WORKSPACE_JOIN_REQUESTS_READ,
        Permissions.WORKSPACE_JOIN_REQUESTS_WRITE,
        Permissions.LLM_INTEGRATIONS_READ,
        Permissions.TOOLKITS_READ,
        Permissions.TOOLKITS_WRITE,
    },
    WorkspaceUserRole.MEMBER: {
        Permissions.WORKSPACE_READ,
        Permissions.WORKSPACE_USERS_READ,
        Permissions.WORKSPACE_INVITATIONS_READ,
        Permissions.LLM_INTEGRATIONS_READ,
        Permissions.TOOLKITS_READ,
    },
}


def get_permissions_for_role(role: WorkspaceUserRole) -> set[Permission]:
    """Compute the Permission set for a Role.

    :param role: Workspace user role
    :return: All Permissions granted to the Role
    """
    return ROLE_PERMISSIONS.get(role, set()).copy()
