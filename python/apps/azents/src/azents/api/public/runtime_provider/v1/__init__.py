"""Runtime Provider discovery v1 Public API."""

from textwrap import dedent
from typing import Annotated

from fastapi import APIRouter, Depends

from azents.core.auth.deps import WorkspaceMember, get_workspace_member
from azents.services.runtime_provider_public.service import RuntimeProviderPublicService
from azents.utils.fastapi.route import RouteMounter

from .data import RuntimeProviderOptionListResponse, RuntimeProviderOptionResponse

router = APIRouter()


@router.get("/workspaces/{handle}/providers")
async def list_workspace_runtime_providers(
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    service: Annotated[RuntimeProviderPublicService, Depends()],
) -> RuntimeProviderOptionListResponse:
    """List eligible Runtime Providers for a Workspace."""
    providers = await service.list_for_workspace(member.workspace_id)
    return RuntimeProviderOptionListResponse(
        items=[
            RuntimeProviderOptionResponse.convert_from(provider)
            for provider in providers
        ]
    )


def mount(mounter: RouteMounter) -> None:
    """Mount Runtime Provider discovery routes."""
    mounter(
        router,
        prefix="/runtime-provider/v1",
        tag="Runtime Provider v1",
        description=dedent(
            """
            Runtime Provider API (Public)

            Workspace-scoped eligible Provider discovery for Agent preference surfaces.
            """
        ),
    )
