"""Testenv API routes.

Provides testenv-only devtools endpoints. This does not start in production and
is served from a separate port (:8012).
"""

from azents.utils.fastapi.route import RouteMounter

from . import broker, external_channel_ingress


def mount(mounter: RouteMounter) -> None:
    """Mounts Testenv API routes."""
    broker.mount(mounter)
    external_channel_ingress.mount(mounter)
