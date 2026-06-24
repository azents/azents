"""Workspace model settings Public API."""

from azents.utils.fastapi.route import RouteMounter

from . import v1


def mount(parent: RouteMounter) -> None:
    """Mounts Workspace model settings routes."""
    v1.mount(parent)
