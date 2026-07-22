"""Runtime Provider enrollment Public API package."""

from azents.utils.fastapi.route import RouteMounter

from . import v1


def mount(mounter: RouteMounter) -> None:
    """Mount Runtime Provider enrollment Public API routes."""
    v1.mount(mounter)
