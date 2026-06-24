"""Agent Runtime Public API package."""

from azents.utils.fastapi.route import RouteMounter

from . import v1


def mount(mounter: RouteMounter) -> None:
    """Mounts the Agent Runtime Public API."""
    v1.mount(mounter)
