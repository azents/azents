"""External Channel v1 provider callbacks."""

from textwrap import dedent

from azents.utils.fastapi.route import RouteMounter

from .route import router


def mount(mounter: RouteMounter) -> None:
    """Mount External Channel v1 callback routes."""
    mounter(
        router,
        prefix="/external-channel/v1",
        tag="External Channel v1",
        description=dedent(
            """
            External Channel provider callbacks.

            Provider callbacks are intentionally excluded from the generated
            authenticated public-client contract.
            """
        ),
    )
