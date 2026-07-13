"""Unauthenticated one-time system bootstrap Admin API."""

from textwrap import dedent
from typing import Annotated, assert_never

from azcommon.result import Failure, Success
from fastapi import APIRouter, Depends, Header, HTTPException, Request, status

from azents.services.system_bootstrap.data import (
    BootstrapUnavailable,
    InvalidSetupToken,
    SystemBootstrapInput,
    WeakBootstrapPassword,
)
from azents.services.system_bootstrap.service import SystemBootstrapService
from azents.utils.fastapi.route import RouteMounter

from .data import (
    SystemBootstrapFirstAdminRequest,
    SystemBootstrapFirstAdminResponse,
    SystemBootstrapStatusResponse,
)

router = APIRouter()


@router.get("/bootstrap/status")
async def get_system_bootstrap_status(
    service: Annotated[SystemBootstrapService, Depends()],
) -> SystemBootstrapStatusResponse:
    """Return whether initial system bootstrap is available."""
    output = await service.get_status()
    return SystemBootstrapStatusResponse.model_validate(output)


@router.post(
    "/bootstrap/first-admin",
    status_code=status.HTTP_201_CREATED,
)
async def bootstrap_first_system_admin(
    service: Annotated[SystemBootstrapService, Depends()],
    request: Request,
    request_body: SystemBootstrapFirstAdminRequest,
    setup_token: Annotated[str, Header(alias="X-Azents-Setup-Token")],
) -> SystemBootstrapFirstAdminResponse:
    """Create the first User and system administrator session."""
    result = await service.bootstrap(
        SystemBootstrapInput(
            setup_token=setup_token,
            email=request_body.email,
            password=request_body.password,
            user_agent=request.headers.get("User-Agent"),
            ip_address=request.client.host if request.client is not None else None,
        )
    )
    match result:
        case Success(value):
            return SystemBootstrapFirstAdminResponse.model_validate(value)
        case Failure(error):
            match error:
                case BootstrapUnavailable() | InvalidSetupToken():
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail=(
                            "System bootstrap is unavailable or the setup token "
                            "is invalid."
                        ),
                    )
                case WeakBootstrapPassword(message):
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=message,
                    )
                case _:
                    assert_never(error)
        case _:
            assert_never(result)


def mount(mounter: RouteMounter) -> None:
    """Mount unauthenticated one-time bootstrap routes."""
    mounter(
        router,
        prefix="/system/v1",
        tag="System Bootstrap v1",
        description=dedent(
            """
            System Bootstrap API (Admin)

            One-time initialization for a zero-user Azents instance.
            """
        ),
    )
