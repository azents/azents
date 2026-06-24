"""Admin API routes.

CRUD API endpoints with offset/limit pagination for admin tools (e.g., Retool).
"""

from azents.utils.fastapi.route import RouteMounter

from . import (
    auth,
    debug,
    health,
    invitation,
    user,
    user_email,
    workspace,
    workspace_user,
)

modules = [
    auth,
    debug,
    health,
    invitation,
    user,
    user_email,
    workspace,
    workspace_user,
]


def mount(mounter: RouteMounter) -> None:
    """Mounts Admin API routes."""
    for module in modules:
        module.mount(mounter)
