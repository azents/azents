"""Private resolver-only authority operations; never an issuer trust path."""

import secrets
from typing import Annotated

from azents_llm_contract.authority import (
    ModelListRequest,
    ModelListResponse,
    ResolveRequest,
    TargetBinding,
)
from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.security import APIKeyHeader

from azents.api.llm_authority_route import LLMAuthorityRoute
from azents.core.config import Config
from azents.core.deps import get_config
from azents.services.llm_authority import LLMAuthorityService
from azents.utils.fastapi.route import RouteMounter

resolver_header = APIKeyHeader(name="X-Azents-LLM-Resolver", auto_error=False)


def require_resolver(
    supplied: Annotated[str | None, Depends(resolver_header)],
    config: Annotated[Config, Depends(get_config)],
) -> None:
    expected = config.llm_resolver_service_key
    if (
        expected is None
        or supplied is None
        or len(expected.get_secret_value()) < 32
        or not secrets.compare_digest(
            supplied.encode(), expected.get_secret_value().encode()
        )
    ):
        raise HTTPException(status_code=403, detail="Resolver service access required.")


router = APIRouter(
    route_class=LLMAuthorityRoute, dependencies=[Depends(require_resolver)]
)


@router.post("/models", response_model=ModelListResponse)
async def list_models(
    body: ModelListRequest,
    service: Annotated[LLMAuthorityService, Depends(LLMAuthorityService)],
) -> Response:
    result = await service.list_models(agent_token=body.agent_token.get_secret_value())
    return Response(content=result.protected_json(), media_type="application/json")


@router.post("/resolve", response_model=TargetBinding)
async def resolve(
    body: ResolveRequest,
    service: Annotated[LLMAuthorityService, Depends(LLMAuthorityService)],
) -> Response:
    result = await service.resolve(
        agent_token=body.agent_token.get_secret_value(),
        model=body.model,
        target_id=body.target_id,
    )
    return Response(content=result.protected_json(), media_type="application/json")


def mount(mounter: RouteMounter) -> None:
    mounter(router, prefix="/llm", tag="Internal inference authority")
