"""External Channel v1 provider callbacks."""

from textwrap import dedent

from fastapi import APIRouter

from azents.utils.fastapi.route import RouteMounter

from .management_route import router as management_router
from .route import router as callback_router

router = APIRouter()
router.include_router(callback_router)
router.include_router(management_router)


def mount(mounter: RouteMounter) -> None:
    """Mount External Channel v1 callback and management routes."""
    mounter(
        router,
        prefix="/external-channel/v1",
        tag="External Channel v1",
        description=dedent(
            """
            External Channel provider callbacks and authenticated management APIs.

            Raw provider callbacks remain excluded from the generated public-client
            contract.
            """
        ),
    )
