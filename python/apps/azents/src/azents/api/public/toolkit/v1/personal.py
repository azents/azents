"""Current-account personal Toolkit configuration and permission endpoints."""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Annotated, Self, assert_never

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, model_validator

from azents.core.auth.deps import WorkspaceMember, get_workspace_member
from azents.core.personal_toolkit import (
    PersonalToolkitAccessConflict,
    PersonalToolkitAccessMutation,
    PersonalToolkitAgentIneligible,
    PersonalToolkitAuthorityDenied,
    PersonalToolkitConfigurationConflict,
    PersonalToolkitManager,
    PersonalToolkitNotFound,
    PersonalToolkitProviderAuthorityDenied,
)
from azents.core.toolkit_ownership import (
    PersonalToolkitAccess,
    PersonalToolkitAccessMode,
    UserToolkitOwner,
)
from azents.services.toolkit.data import (
    InvalidConfig,
    InvalidCredentials,
    InvalidIdentifier,
    InvalidToolkitType,
    PersonalToolkitOutput,
    ToolkitConfigurationInput,
    ToolkitReadiness,
)
from azents.services.toolkit.personal import PersonalToolkitService

from .data import ToolkitConfigUpdateRequest, ToolkitConfigurationResponse
from .github_user import _management_errors as github_user_management_errors
from .google import _errors as google_management_errors
from .toolkit_validation import ToolkitSensitiveInputRoute

router = APIRouter(
    prefix="/workspaces/{handle}", route_class=ToolkitSensitiveInputRoute
)
Account = Annotated[WorkspaceMember, Depends(get_workspace_member)]
Service = Annotated[PersonalToolkitService, Depends(PersonalToolkitService)]


class PersonalToolkitResponse(ToolkitConfigurationResponse):
    """Allowlisted personal configuration without credentials or owning Workspace."""

    owner: UserToolkitOwner
    access_mode: PersonalToolkitAccessMode
    selected_agent_ids: tuple[str, ...]
    readiness: ToolkitReadiness


class PersonalToolkitListResponse(BaseModel):
    """Personal connections available to this exact account's management UI."""

    items: list[PersonalToolkitResponse]


class PersonalToolkitCreateRequest(ToolkitConfigurationInput):
    """Common Provider options with owner identity derived only from authentication."""

    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class PersonalToolkitAccessRequest(BaseModel):
    """Explicit expected mode and membership deltas, independent of search filters."""

    model_config = ConfigDict(extra="forbid")
    expected_mode: PersonalToolkitAccessMode
    mode: PersonalToolkitAccessMode | None
    allow_agent_ids: frozenset[str]
    restrict_agent_ids: frozenset[str]

    @model_validator(mode="after")
    def validate_intent(self) -> Self:
        """Reject ambiguous permission intents before entering persistence."""
        if self.allow_agent_ids & self.restrict_agent_ids:
            raise ValueError("An Agent cannot be both allowed and restricted")
        if self.mode is PersonalToolkitAccessMode.ALL and (
            self.allow_agent_ids or self.restrict_agent_ids
        ):
            raise ValueError("Allow all cannot be combined with membership deltas")
        return self


class PersonalToolkitBatchEntry(PersonalToolkitAccessRequest):
    """One exact connection in an atomic multi-connection save."""

    toolkit_id: str


class PersonalToolkitBatchRequest(BaseModel):
    """An explicit set of connection intents, not a complete selection baseline."""

    model_config = ConfigDict(extra="forbid")
    mutations: list[PersonalToolkitBatchEntry]

    @model_validator(mode="after")
    def distinct_targets(self) -> Self:
        """Each parent receives one unambiguous intent per atomic save."""
        if len({entry.toolkit_id for entry in self.mutations}) != len(self.mutations):
            raise ValueError("Duplicate Toolkit mutation")
        return self


class PersonalToolkitAgentBatchRequest(PersonalToolkitBatchRequest):
    """Agent editor can update only the exact Agent and cannot reset global policy."""

    @model_validator(mode="after")
    def no_global_mode(self) -> Self:
        if any(entry.mode is not None for entry in self.mutations):
            raise ValueError("Agent editor cannot replace connection-wide mode")
        return self


class PersonalToolkitAccessResponse(BaseModel):
    """Committed policy snapshot from the single personal connection authority."""

    toolkit_id: str
    mode: PersonalToolkitAccessMode
    selected_agent_ids: tuple[str, ...]


class PersonalToolkitBatchResponse(BaseModel):
    """Acknowledged complete atomic save, excluding credential and owner material."""

    items: list[PersonalToolkitAccessResponse]


class PersonalToolkitEligibleAgentResponse(BaseModel):
    """Full current ordinary-access Agent identity for Workspace-grouped selection."""

    agent_id: str
    agent_name: str
    workspace_id: str
    workspace_name: str
    workspace_handle: str


class PersonalToolkitEligibleAgentListResponse(BaseModel):
    """All current eligible Agents before any UI search or pagination."""

    items: list[PersonalToolkitEligibleAgentResponse]


def _subject(account: WorkspaceMember) -> PersonalToolkitManager:
    return PersonalToolkitManager(
        user_id=account.user_id,
        session_id=account.session_id,
        workspace_id=account.workspace_id,
    )


def _response(value: PersonalToolkitOutput) -> PersonalToolkitResponse:
    return PersonalToolkitResponse.model_validate(value, from_attributes=True)


def _access(value: PersonalToolkitAccess) -> PersonalToolkitAccessResponse:
    return PersonalToolkitAccessResponse.model_validate(value, from_attributes=True)


@contextmanager
def _errors() -> Iterator[None]:
    """Map expected authority/conflict errors while preserving internal failures."""
    with google_management_errors():
        try:
            yield
        except PersonalToolkitAuthorityDenied:
            raise HTTPException(
                401, "Personal Toolkit account authorization required"
            ) from None
        except PersonalToolkitNotFound, PersonalToolkitAgentIneligible:
            raise HTTPException(
                404, "Personal Toolkit or accessible Agent not found"
            ) from None
        except PersonalToolkitAccessConflict, PersonalToolkitConfigurationConflict:
            raise HTTPException(
                409, "Personal Toolkit changed; reload before saving"
            ) from None
        except PersonalToolkitProviderAuthorityDenied:
            raise HTTPException(403, "Current Provider authority is required") from None


def _validation_error(
    error: InvalidConfig | InvalidCredentials | InvalidIdentifier | InvalidToolkitType,
) -> HTTPException:
    """Return credential-safe validation categories with the existing HTTP semantics."""
    match error:
        case InvalidToolkitType():
            return HTTPException(400, "Unknown toolkit type")
        case InvalidConfig():
            return HTTPException(422, "Invalid tool config or credential shape")
        case InvalidCredentials():
            return HTTPException(422, error.detail)
        case InvalidIdentifier():
            return HTTPException(
                422,
                [
                    {
                        "type": "value_error",
                        "loc": ["body", error.field],
                        "msg": error.detail,
                        "input": None,
                    }
                ],
            )
        case _:
            assert_never(error)


@router.get("/personal-toolkit-configs")
async def list_personal_toolkits(
    account: Account, service: Service
) -> PersonalToolkitListResponse:
    """List only the authenticated active account's personal connections."""
    with _errors():
        return PersonalToolkitListResponse(
            items=[_response(value) for value in await service.list(_subject(account))]
        )


@router.post("/personal-toolkit-configs", status_code=status.HTTP_201_CREATED)
async def create_personal_toolkit(
    account: Account, service: Service, request_body: PersonalToolkitCreateRequest
) -> PersonalToolkitResponse:
    """Create with common Provider validation and default dynamic All access."""
    with _errors():
        result = await service.create(_subject(account), request_body)
        if result.success:
            return _response(result.value)
        raise _validation_error(result.error)


@router.get("/personal-toolkit-configs/{toolkit_id}")
async def get_personal_toolkit(
    account: Account, service: Service, toolkit_id: str
) -> PersonalToolkitResponse:
    """Read exact-owner configuration and redacted Provider state."""
    with _errors():
        return _response(await service.get(_subject(account), toolkit_id))


@router.patch("/personal-toolkit-configs/{toolkit_id}")
async def update_personal_toolkit(
    account: Account,
    service: Service,
    toolkit_id: str,
    request_body: ToolkitConfigUpdateRequest,
) -> PersonalToolkitResponse:
    """Update common settings without replacing the connection's saved access policy."""
    with _errors(), github_user_management_errors():
        result = await service.update(_subject(account), toolkit_id, request_body)
        if result.success:
            return _response(result.value)
        raise _validation_error(result.error)


@router.delete(
    "/personal-toolkit-configs/{toolkit_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_personal_toolkit(
    account: Account, service: Service, toolkit_id: str
) -> Response:
    """Delete the owned canonical connection before ordinary Provider cleanup."""
    with _errors():
        await service.delete(_subject(account), toolkit_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/personal-toolkit-agents")
async def list_personal_toolkit_agents(
    account: Account, service: Service
) -> PersonalToolkitEligibleAgentListResponse:
    """Return all ordinarily accessible Agents, not a filtered replacement baseline."""
    with _errors():
        return PersonalToolkitEligibleAgentListResponse(
            items=[
                PersonalToolkitEligibleAgentResponse.model_validate(
                    value, from_attributes=True
                )
                for value in await service.eligible_agents(_subject(account))
            ]
        )


@router.patch("/personal-toolkit-configs/{toolkit_id}/agent-access")
async def save_personal_toolkit_access(
    account: Account,
    service: Service,
    toolkit_id: str,
    request_body: PersonalToolkitAccessRequest,
) -> PersonalToolkitAccessResponse:
    """Apply one connection-wide mode/delta intent with expected-mode protection."""
    with _errors():
        result = await service.mutate_access(
            _subject(account),
            [
                PersonalToolkitAccessMutation(
                    toolkit_id=toolkit_id, **request_body.model_dump()
                )
            ],
            agent_id=None,
        )
        return _access(result[0])


@router.get("/agents/{agent_id}/personal-toolkit-access")
async def get_agent_personal_toolkit_access(
    account: Account, service: Service, agent_id: str
) -> PersonalToolkitListResponse:
    """Read the account's personal choices after exact ordinary Agent access checks."""
    with _errors():
        return PersonalToolkitListResponse(
            items=[
                _response(value)
                for value in await service.agent_connections(
                    _subject(account), agent_id
                )
            ]
        )


@router.patch("/agents/{agent_id}/personal-toolkit-access")
async def save_agent_personal_toolkit_access(
    account: Account,
    service: Service,
    agent_id: str,
    request_body: PersonalToolkitAgentBatchRequest,
) -> PersonalToolkitBatchResponse:
    """Commit every exact-Agent intent or none without requiring AgentAdmin."""
    with _errors():
        result = await service.mutate_access(
            _subject(account),
            [
                PersonalToolkitAccessMutation(**entry.model_dump())
                for entry in request_body.mutations
            ],
            agent_id=agent_id,
        )
        return PersonalToolkitBatchResponse(items=[_access(value) for value in result])
