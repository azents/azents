"""Public Runtime Web service control API."""

from azents.utils.fastapi.route import RouteMounter

from . import v1


def mount(mounter: RouteMounter) -> None:
    """Mount Public Runtime Web API versions."""
    v1.mount(mounter)
