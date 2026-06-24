"""Security routes (Public)."""

from azents.utils.fastapi.route import RouteMounter

from . import v1


def mount(mounter: RouteMounter) -> None:
    """Mounts Security routes."""
    v1.mount(mounter)
