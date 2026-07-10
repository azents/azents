"""xAI OAuth Public API routes."""

from azents.utils.fastapi.route import RouteMounter

from . import v1


def mount(mounter: RouteMounter) -> None:
    """Mount xAI OAuth routes."""
    v1.mount(mounter)
