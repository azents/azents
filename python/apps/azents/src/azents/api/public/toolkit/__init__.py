"""Toolkit Public API."""

from azents.utils.fastapi.route import RouteMounter

from .v1.routes import mount as mount_v1


def mount(mounter: RouteMounter) -> None:
    """Mount Toolkit routes."""
    mount_v1(mounter)
