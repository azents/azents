"""Workspace role permission boundary tests."""

from azents.core.auth.permissions import Permissions, has_permission
from azents.core.auth.roles import get_permissions_for_role
from azents.core.enums import WorkspaceUserRole


def test_runtime_profile_delete_permission_is_owner_only() -> None:
    """Managers retain Profile writes without permanent delete authority."""
    owner = get_permissions_for_role(WorkspaceUserRole.OWNER)
    manager = get_permissions_for_role(WorkspaceUserRole.MANAGER)
    member = get_permissions_for_role(WorkspaceUserRole.MEMBER)

    assert has_permission(owner, Permissions.RUNTIME_PROFILES_DELETE)
    assert not has_permission(manager, Permissions.RUNTIME_PROFILES_DELETE)
    assert not has_permission(member, Permissions.RUNTIME_PROFILES_DELETE)
    assert has_permission(manager, Permissions.RUNTIME_PROFILES_WRITE)
