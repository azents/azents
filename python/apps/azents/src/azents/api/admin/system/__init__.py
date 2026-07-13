"""System Admin API package."""

from azents.api.admin.system import v1
from azents.utils.fastapi.route import RouteMounter


def mount(mounter: RouteMounter) -> None:
    """Mount system administration routes."""
    v1.mount(mounter)
