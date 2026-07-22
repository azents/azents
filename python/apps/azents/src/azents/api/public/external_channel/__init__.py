"""External Channel provider callback routes."""

from azents.utils.fastapi.route import RouteMounter

from . import v1


def mount(mounter: RouteMounter) -> None:
    """Mount External Channel callback routes."""
    v1.mount(mounter)
