"""Chat Public API."""

from azents.utils.fastapi.route import RouteMounter

from . import v1


def mount(mounter: RouteMounter) -> None:
    """Mounts Chat routes."""
    v1.mount(mounter)
