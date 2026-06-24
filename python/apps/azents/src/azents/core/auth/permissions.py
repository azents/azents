"""Permission system.

Provides Resource, Action, and Permission classes for type-safe permission
representation.
"""

from dataclasses import dataclass
from enum import StrEnum


class Resource(StrEnum):
    """Resource to which permission applies."""

    WILDCARD = "*"  # All resources
    WORKSPACE = "workspace"
    WORKSPACE_USERS = "workspace_users"
    WORKSPACE_INVITATIONS = "workspace_invitations"
    LLM_INTEGRATIONS = "llm_integrations"
    TOOLKITS = "toolkits"
    WORKSPACE_JOIN_REQUESTS = "workspace_join_requests"


class Action(StrEnum):
    """Action on a resource."""

    WILDCARD = "*"
    READ = "read"
    WRITE = "write"


@dataclass(frozen=True)
class Permission:
    """Type-safe permission representation.

    Usage examples:
    - Permission(Resource.WORKSPACE, Action.READ)      -> "workspace:read"
    - Permission(Resource.WILDCARD, Action.WILDCARD)    -> "*:*" (All permissions)
    - Permission(Resource.WORKSPACE, Action.WILDCARD)   -> "workspace:*"
    """

    resource: Resource
    action: Action

    def __str__(self) -> str:
        """String representation, e.g. "workspace:read"."""
        return f"{self.resource.value}:{self.action.value}"

    @classmethod
    def from_string(cls, value: str) -> "Permission":
        """Create Permission from string.

        :param value: Permission string, e.g. "workspace:read" or "*"
        :raises ValueError: When format is invalid
        :return: Permission object
        """
        if value == "*":
            return cls(Resource.WILDCARD, Action.WILDCARD)

        parts = value.split(":")
        if len(parts) != 2:
            raise ValueError(f"Invalid permission format: {value}")

        resource_str, action_str = parts

        try:
            resource = Resource(resource_str)
        except ValueError:
            raise ValueError(f"Unknown resource: {resource_str}") from None

        try:
            action = Action(action_str)
        except ValueError:
            raise ValueError(f"Unknown action: {action_str}") from None

        return cls(resource, action)

    def matches(self, required: "Permission") -> bool:
        """Check whether this permission satisfies the required permission.

        Examples:
        - Permission(WILDCARD, WILDCARD).matches(WORKSPACE, READ) -> True
        - Permission(WORKSPACE, WILDCARD).matches(WORKSPACE, READ) -> True
        - Permission(WILDCARD, READ).matches(WORKSPACE, READ) -> True
        - Permission(WORKSPACE, READ).matches(WORKSPACE, WRITE) -> False

        :param required: Required permission
        :return: True when permission is satisfied
        """
        # Resource matching
        if self.resource != Resource.WILDCARD and self.resource != required.resource:
            return False

        # Action matching
        if self.action != Action.WILDCARD and self.action != required.action:
            return False

        return True


class Permissions:
    """Predefined Permission constants."""

    # All permissions
    ALL = Permission(Resource.WILDCARD, Action.WILDCARD)

    # Workspace
    WORKSPACE_READ = Permission(Resource.WORKSPACE, Action.READ)
    WORKSPACE_WRITE = Permission(Resource.WORKSPACE, Action.WRITE)

    # Workspace Users
    WORKSPACE_USERS_READ = Permission(Resource.WORKSPACE_USERS, Action.READ)
    WORKSPACE_USERS_WRITE = Permission(Resource.WORKSPACE_USERS, Action.WRITE)

    # Workspace Invitations
    WORKSPACE_INVITATIONS_READ = Permission(Resource.WORKSPACE_INVITATIONS, Action.READ)
    WORKSPACE_INVITATIONS_WRITE = Permission(
        Resource.WORKSPACE_INVITATIONS, Action.WRITE
    )

    # LLM Integrations
    LLM_INTEGRATIONS_READ = Permission(Resource.LLM_INTEGRATIONS, Action.READ)
    LLM_INTEGRATIONS_WRITE = Permission(Resource.LLM_INTEGRATIONS, Action.WRITE)

    # Toolkits
    TOOLKITS_READ = Permission(Resource.TOOLKITS, Action.READ)
    TOOLKITS_WRITE = Permission(Resource.TOOLKITS, Action.WRITE)

    # Workspace Join Requests
    WORKSPACE_JOIN_REQUESTS_READ = Permission(
        Resource.WORKSPACE_JOIN_REQUESTS, Action.READ
    )
    WORKSPACE_JOIN_REQUESTS_WRITE = Permission(
        Resource.WORKSPACE_JOIN_REQUESTS, Action.WRITE
    )


def has_permission(granted: set[Permission], required: Permission) -> bool:
    """Check whether permission is granted.

    :param granted: Granted permission set
    :param required: Required permission
    :return: True when permission exists
    """
    for perm in granted:
        if perm.matches(required):
            return True
    return False
