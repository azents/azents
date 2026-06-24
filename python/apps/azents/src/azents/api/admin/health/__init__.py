"""Health routes (Admin)."""

from azents.utils.fastapi.route import RouteMounter

from . import v1


def mount(mounter: RouteMounter) -> None:
    """Mounts Health routes."""
    v1.mount(mounter)
