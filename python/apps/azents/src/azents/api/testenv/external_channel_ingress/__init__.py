"""External Channel ingress devtools routes (Testenv)."""

from azents.utils.fastapi.route import RouteMounter

from . import v1


def mount(mounter: RouteMounter) -> None:
    """Mount External Channel ingress devtools routes."""
    v1.mount(mounter)
