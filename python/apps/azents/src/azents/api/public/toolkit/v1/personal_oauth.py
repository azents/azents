"""Owner-bound personal MCP authorization endpoints using existing Provider flows."""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Annotated

from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel, ConfigDict, Field

from azents.core.auth.deps import CurrentUser, get_current_user
from azents.core.personal_toolkit import PersonalToolkitManager
from azents.services.toolkit_oauth.data import (
    ToolkitConnectionTestInput,
    ToolkitOAuthError,
)
from azents.services.toolkit_oauth.personal import PersonalToolkitOAuthService

from .oauth import (
    OAuthAuthorizeResponse,
    TestConnectionRequest,
    TestConnectionResponse,
    _raise_toolkit_oauth_error,
)
from .personal import _errors
from .toolkit_validation import ToolkitSensitiveInputRoute

router = APIRouter(route_class=ToolkitSensitiveInputRoute)
Account = Annotated[CurrentUser, Depends(get_current_user)]
Service = Annotated[PersonalToolkitOAuthService, Depends(PersonalToolkitOAuthService)]


class PersonalConnectionTestRequest(TestConnectionRequest):
    """Common test fields with saved IDs restricted to the current owner."""

    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


@router.post("/personal-toolkit-configs/test-connection")
async def test_personal_connection(
    account: Account,
    service: Service,
    body: PersonalConnectionTestRequest,
) -> TestConnectionResponse:
    """Test common unsaved fields or an exact-owner saved credential merge."""
    with _oauth_errors():
        result = await service.test_unsaved(
            PersonalToolkitManager(account.user_id, account.session_id),
            ToolkitConnectionTestInput(
                toolkit_type=body.toolkit_type,
                config=body.config,
                credentials=body.credentials,
                toolkit_config_id=body.toolkit_config_id,
            ),
        )
    return TestConnectionResponse.model_validate(result, from_attributes=True)


@router.post("/personal-toolkit-configs/{toolkit_id}/test-connection")
async def test_saved_personal_connection(
    account: Account,
    service: Service,
    toolkit_id: str,
) -> TestConnectionResponse:
    """Test this account's saved connection through its normal Provider."""
    with _oauth_errors():
        result = await service.test_saved(
            PersonalToolkitManager(account.user_id, account.session_id),
            toolkit_id,
        )
    return TestConnectionResponse.model_validate(result, from_attributes=True)


class PersonalOAuthExchangeRequest(BaseModel):
    """Transient callback receipt with owner/target derived from trusted context."""

    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    code: str = Field(min_length=1, max_length=4096, repr=False)
    state: str = Field(min_length=1, max_length=8192, repr=False)


@contextmanager
def _oauth_errors() -> Iterator[None]:
    with _errors():
        try:
            yield
        except ToolkitOAuthError as error:
            _raise_toolkit_oauth_error(error)


@router.post("/personal-toolkit-configs/{toolkit_id}/oauth/connect")
async def connect_personal_oauth(
    account: Account, service: Service, toolkit_id: str
) -> OAuthAuthorizeResponse:
    """Connect the exact active owner's canonical MCP-backed connection."""
    with _oauth_errors():
        url = await service.connect(
            PersonalToolkitManager(account.user_id, account.session_id), toolkit_id
        )
    return OAuthAuthorizeResponse(authorization_url=url)


@router.post(
    "/personal-toolkit-configs/{toolkit_id}/oauth/exchange",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def exchange_personal_oauth(
    account: Account,
    service: Service,
    toolkit_id: str,
    request_body: PersonalOAuthExchangeRequest,
) -> Response:
    """Publish only after owner/Auth Session/source callback binding is verified."""
    with _oauth_errors():
        await service.exchange(
            PersonalToolkitManager(account.user_id, account.session_id),
            toolkit_id,
            code=request_body.code,
            state=request_body.state,
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete(
    "/personal-toolkit-configs/{toolkit_id}/oauth",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def disconnect_personal_oauth(
    account: Account, service: Service, toolkit_id: str
) -> Response:
    """Delete only the current owner's local MCP credentials and pending admission."""
    with _oauth_errors():
        await service.disconnect(
            PersonalToolkitManager(account.user_id, account.session_id), toolkit_id
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
