"""System Settings Admin API package."""

from azents.api.admin.system_setting import v1
from azents.utils.fastapi.route import RouteMounter


def mount(mounter: RouteMounter) -> None:
    """Mount System Settings routes."""
    v1.mount(mounter)
