"""System bootstrap Admin API package."""

from azents.api.admin.bootstrap import v1
from azents.utils.fastapi.route import RouteMounter


def mount(mounter: RouteMounter) -> None:
    """Mount unauthenticated system bootstrap routes."""
    v1.mount(mounter)
