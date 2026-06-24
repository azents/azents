"""ChatGPT OAuth public API mounter."""

from azents.utils.fastapi.route import RouteMounter

from . import v1


def mount(mounter: RouteMounter) -> None:
    """Mounts the ChatGPT OAuth public API."""
    v1.mount(mounter)
