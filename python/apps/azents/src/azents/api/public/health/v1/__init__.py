"""Health v1 API."""

from fastapi import APIRouter

from azents.utils.fastapi.route import RouteMounter

from .data import HealthStatus

router = APIRouter()


@router.get("/readiness")
def readiness() -> HealthStatus:
    """Return the server readiness status.

    This is the endpoint for the Kubernetes readiness probe.
    """
    return HealthStatus(status="ok")


@router.get("/liveness")
def liveness() -> HealthStatus:
    """Return the server liveness status.

    This is the endpoint for the Kubernetes liveness probe.
    """
    return HealthStatus(status="ok")


def mount(mounter: RouteMounter) -> None:
    """Mount the Health v1 routes."""
    mounter(
        router,
        prefix="/health/v1",
        tag="Health v1",
        description="Server status API",
    )
