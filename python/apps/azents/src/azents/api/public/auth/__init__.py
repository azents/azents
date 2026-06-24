"""Auth routes (Public)."""

from azents.utils.fastapi.route import RouteMounter

from . import v1


def mount(mounter: RouteMounter) -> None:
    """Mounts Auth routes."""
    v1.mount(mounter)
