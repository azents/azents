"""Workspace Runtime Profile Public API."""

from azents.utils.fastapi.route import RouteMounter

from . import v1


def mount(mounter: RouteMounter) -> None:
    """Mount Workspace Runtime Profile API versions."""
    v1.mount(mounter)
