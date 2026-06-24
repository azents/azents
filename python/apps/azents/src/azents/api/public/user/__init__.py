"""User routes (Public)."""

from azents.utils.fastapi.route import RouteMounter

from . import v1


def mount(mounter: RouteMounter) -> None:
    """Mounts User routes."""
    v1.mount(mounter)
