"""Internal API routes."""

from typing import Protocol

from azents.utils.fastapi.route import RouteMounter


class _RouteModule(Protocol):
    def mount(self, mounter: RouteMounter) -> None: ...


modules: list[_RouteModule] = []


def mount(mounter: RouteMounter) -> None:
    """Mounts Internal API routes."""
    for module in modules:
        module.mount(mounter)
