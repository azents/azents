"""Privileged development supply management, protected by system-admin auth."""

from typing import Annotated

from azents_llm_contract.authority import (
    IssuedToken,
    TokenIssueRequest,
    TokenRotateRequest,
)
from fastapi import APIRouter, Depends, Response

from azents.api.llm_authority_route import LLMAuthorityRoute
from azents.core.auth.deps import SystemAdmin, get_system_admin
from azents.core.llm_access import SupplyState
from azents.services.llm_access import LLMAccessService
from azents.utils.fastapi.route import RouteMounter

router = APIRouter(route_class=LLMAuthorityRoute)


@router.post("/supplies", response_model=IssuedToken, status_code=201)
async def issue(
    body: TokenIssueRequest,
    admin: Annotated[SystemAdmin, Depends(get_system_admin)],
    service: Annotated[LLMAccessService, Depends(LLMAccessService)],
) -> Response:
    result = await service.issue(
        agent_id=body.agent_id,
        subject=body.supply_subject,
        issuer=f"system-admin:{admin.user_id}",
    )
    return Response(
        content=result.protected_json(), status_code=201, media_type="application/json"
    )


@router.post("/rotate", response_model=IssuedToken)
async def rotate(
    body: TokenRotateRequest,
    service: Annotated[LLMAccessService, Depends(LLMAccessService)],
) -> Response:
    result = await service.rotate(
        supply_id=body.supply_id, expected_token_id=body.expected_token_id
    )
    return Response(content=result.protected_json(), media_type="application/json")


@router.get("/supplies/{supply_id}")
async def inspect_supply(
    supply_id: str,
    service: Annotated[LLMAccessService, Depends(LLMAccessService)],
) -> SupplyState:
    return await service.inspect(supply_id=supply_id)


@router.get("/agents/{agent_id}/supply")
async def inspect_subject(
    agent_id: str,
    subject: str,
    service: Annotated[LLMAccessService, Depends(LLMAccessService)],
) -> SupplyState:
    """Inspect an existing supply after an uncertain issuance response."""
    return await service.inspect_subject(agent_id=agent_id, subject=subject)


@router.delete("/supplies/{supply_id}", status_code=204)
async def revoke_supply(
    supply_id: str,
    service: Annotated[LLMAccessService, Depends(LLMAccessService)],
) -> None:
    await service.revoke(supply_id=supply_id, token_id=None)


@router.delete("/supplies/{supply_id}/tokens/{token_id}", status_code=204)
async def revoke_token(
    supply_id: str,
    token_id: str,
    service: Annotated[LLMAccessService, Depends(LLMAccessService)],
) -> None:
    await service.revoke(supply_id=supply_id, token_id=token_id)


def mount(mounter: RouteMounter) -> None:
    mounter(router, prefix="/llm-access/v1", tag="Inference access v1")
