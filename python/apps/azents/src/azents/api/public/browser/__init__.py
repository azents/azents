"""Public Session Browser API versions."""

from azents.api.public.browser import v1
from azents.utils.fastapi.route import RouteMounter


def mount(mounter: RouteMounter) -> None:
    v1.mount(mounter)
