"""Model catalog Admin API package."""

from azents.api.admin.model_catalog import v1
from azents.utils.fastapi.route import RouteMounter


def mount(mounter: RouteMounter) -> None:
    """Mount Model Catalog routes."""
    v1.mount(mounter)
