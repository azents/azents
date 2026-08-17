"""Scheduled Task Public API."""

from azents.utils.fastapi.route import RouteMounter

from . import v1


def mount(mounter: RouteMounter) -> None:
    """Mount Scheduled Task Public API routes."""
    v1.mount(mounter)
