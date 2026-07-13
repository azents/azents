"""Admin API routes.

Global operational APIs protected by authenticated system-administrator authority.
Health probes remain unauthenticated infrastructure endpoints.
"""

from collections.abc import Sequence

from fastapi import APIRouter, Depends, params

from azents.core.auth.deps import get_system_admin
from azents.utils.fastapi.route import RouteMounter

from . import (
    auth,
    bootstrap,
    debug,
    health,
    invitation,
    model_catalog,
    system,
    user,
    user_email,
    workspace,
    workspace_user,
)

protected_modules = [
    auth,
    debug,
    invitation,
    model_catalog,
    system,
    user,
    user_email,
    workspace,
    workspace_user,
]


def mount(mounter: RouteMounter) -> None:
    """Mount Admin API routes with secure defaults."""

    def protected_mounter(
        router: APIRouter,
        *,
        prefix: str,
        tag: str,
        description: str | None = None,
        dependencies: Sequence[params.Depends] | None = None,
    ) -> None:
        mounter(
            router,
            prefix=prefix,
            tag=tag,
            description=description,
            dependencies=[Depends(get_system_admin), *(dependencies or ())],
        )

    health.mount(mounter)
    bootstrap.mount(mounter)
    for module in protected_modules:
        module.mount(protected_mounter)
