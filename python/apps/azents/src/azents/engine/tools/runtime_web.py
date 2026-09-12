"""Runtime-independent tools for temporary Runtime Web services."""

import hashlib
import json
from typing import NoReturn, TypeVar, assert_never

from azcommon.result import Failure, Result, Success
from azcommon.types import JSONObject
from pydantic import BaseModel, ConfigDict, Field

from azents.core.tools import (
    ResolveContext,
    Toolkit,
    ToolkitProvider,
    ToolkitState,
    ToolkitStatus,
    TurnContext,
)
from azents.engine.run.types import FunctionTool, FunctionToolError, FunctionToolResult
from azents.engine.tooling.execution_context import get_client_tool_execution_context
from azents.engine.tooling.make_tool import make_tool
from azents.rdb.models.runtime_web import RuntimeWebRequesterKind
from azents.services.runtime_web.data import (
    RuntimeWebAccessDenied,
    RuntimeWebActor,
    RuntimeWebConfigurationUnavailable,
    RuntimeWebConflict,
    RuntimeWebError,
    RuntimeWebNotFound,
    RuntimeWebOperation,
    RuntimeWebQuotaExceeded,
    RuntimeWebServicePage,
    RuntimeWebServiceProjection,
)
from azents.services.runtime_web.service import RuntimeWebService

T = TypeVar("T")


class RuntimeWebToolkitConfig(BaseModel):
    """Runtime Web Toolkit settings model."""


class PrepareWebServiceInput(BaseModel):
    """prepare_web_service input."""

    model_config = ConfigDict(extra="forbid")

    port: int = Field(ge=1, le=65_535, description="Runtime loopback HTTP port")
    label: str | None = Field(
        max_length=120,
        description="Optional user-facing service label; pass null when absent",
    )


class RequestWebServiceInput(BaseModel):
    """request_web_service input."""

    model_config = ConfigDict(extra="forbid")

    port: int = Field(ge=1, le=65_535, description="Runtime loopback HTTP port")
    label: str | None = Field(
        max_length=120,
        description="Optional user-facing service label; pass null when absent",
    )


class CancelWebServiceRequestInput(BaseModel):
    """cancel_web_service_request input."""

    model_config = ConfigDict(extra="forbid")

    request_id: str = Field(min_length=1, max_length=32)
    expected_revision: int = Field(ge=1)


class CloseWebServiceInput(BaseModel):
    """close_web_service input."""

    model_config = ConfigDict(extra="forbid")

    cycle_id: str = Field(min_length=1, max_length=32)
    expected_endpoint_revision: int = Field(ge=0)


class RuntimeWebToolkit(Toolkit[RuntimeWebToolkitConfig]):
    """Always-on Session-bound Runtime Web control Toolkit."""

    def __init__(
        self,
        *,
        service: RuntimeWebService,
        workspace_id: str,
        agent_id: str,
        session_id: str,
    ) -> None:
        """Create the Session-bound Toolkit."""
        self.service = service
        self.workspace_id = workspace_id
        self.agent_id = agent_id
        self.session_id = session_id

    async def update_context(self, context: TurnContext) -> ToolkitState:
        """Return Runtime-independent service tools for the current Run."""
        if not self.session_id:
            return ToolkitState(status=ToolkitStatus.ENABLED, tools=[])
        return ToolkitState(
            status=ToolkitStatus.ENABLED,
            tools=[
                self._prepare_tool(context.run_id),
                self._request_tool(context.run_id),
                self._list_tool(),
                self._cancel_tool(context.run_id),
                self._close_tool(context.run_id),
            ],
        )

    def _actor(self, run_id: str, call_id: str) -> RuntimeWebActor:
        return RuntimeWebActor(
            kind=RuntimeWebRequesterKind.AGENT,
            actor_id=self.agent_id,
            execution_id=run_id,
            call_id=call_id,
        )

    def _prepare_tool(self, run_id: str) -> FunctionTool:
        async def prepare_web_service(
            input: PrepareWebServiceInput,
        ) -> FunctionToolResult:
            """Get a stable Session-port URL without starting or exposing it."""
            execution = get_client_tool_execution_context()
            result = await self.service.prepare_endpoint(
                workspace_id=self.workspace_id,
                agent_id=self.agent_id,
                session_id=self.session_id,
                user_id=None,
                port=input.port,
                label=input.label,
                actor=self._actor(run_id, execution.call_id),
                operation=_operation("prepare", execution.call_id),
            )
            projection = _unwrap(result)
            return _projection_result(
                projection,
                metadata_kind="runtime_web_service_endpoint",
            )

        return make_tool(
            prepare_web_service,
            input_model=PrepareWebServiceInput,
        )

    def _request_tool(self, run_id: str) -> FunctionTool:
        async def request_web_service(
            input: RequestWebServiceInput,
        ) -> FunctionToolResult:
            """Request human approval for one Session port and continue immediately."""
            execution = get_client_tool_execution_context()
            actor = self._actor(run_id, execution.call_id)
            projection = _unwrap(
                await self.service.request_exposure(
                    workspace_id=self.workspace_id,
                    agent_id=self.agent_id,
                    session_id=self.session_id,
                    user_id=None,
                    port=input.port,
                    label=input.label,
                    actor=actor,
                    operation=_operation("request", execution.call_id),
                )
            )
            return _projection_result(
                projection,
                metadata_kind="runtime_web_service_request",
            )

        return make_tool(
            request_web_service,
            input_model=RequestWebServiceInput,
        )

    def _list_tool(self) -> FunctionTool:
        async def list_web_services() -> str:
            """List stable endpoints, pending approvals, and active exposures."""
            page = _unwrap(
                await self.service.list_services(
                    workspace_id=self.workspace_id,
                    agent_id=self.agent_id,
                    session_id=self.session_id,
                    user_id=None,
                    offset=0,
                    limit=100,
                    actor=RuntimeWebActor(
                        kind=RuntimeWebRequesterKind.AGENT,
                        actor_id=self.agent_id,
                        execution_id=self.session_id,
                        call_id=None,
                    ),
                )
            )
            return json.dumps(
                _page_payload(page),
                sort_keys=True,
            )

        return make_tool(list_web_services)

    def _cancel_tool(self, run_id: str) -> FunctionTool:
        async def cancel_web_service_request(
            input: CancelWebServiceRequestInput,
        ) -> FunctionToolResult:
            """Cancel one exact pending request without closing an active exposure."""
            execution = get_client_tool_execution_context()
            projection = _unwrap(
                await self.service.cancel_request(
                    workspace_id=self.workspace_id,
                    agent_id=self.agent_id,
                    session_id=self.session_id,
                    user_id=None,
                    request_id=input.request_id,
                    expected_revision=input.expected_revision,
                    actor=self._actor(run_id, execution.call_id),
                    operation=_operation("cancel", execution.call_id),
                )
            )
            return _projection_result(
                projection,
                metadata_kind="runtime_web_service_request",
            )

        return make_tool(
            cancel_web_service_request,
            input_model=CancelWebServiceRequestInput,
        )

    def _close_tool(self, run_id: str) -> FunctionTool:
        async def close_web_service(input: CloseWebServiceInput) -> FunctionToolResult:
            """Close one exact current exposure without stopping its Runtime process."""
            execution = get_client_tool_execution_context()
            projection = _unwrap(
                await self.service.close_cycle(
                    workspace_id=self.workspace_id,
                    agent_id=self.agent_id,
                    session_id=self.session_id,
                    user_id=None,
                    cycle_id=input.cycle_id,
                    expected_endpoint_revision=input.expected_endpoint_revision,
                    actor=self._actor(run_id, execution.call_id),
                    operation=_operation("close", execution.call_id),
                )
            )
            return _projection_result(
                projection,
                metadata_kind="runtime_web_service_cycle",
            )

        return make_tool(close_web_service, input_model=CloseWebServiceInput)


class RuntimeWebToolkitProvider(ToolkitProvider[RuntimeWebToolkitConfig]):
    """Always-resolved provider for Runtime Web service control."""

    slug = "runtime_web"
    name = "Runtime Web"
    description = "Prepare and control temporary Session web services"
    system_prompt = ""
    config_model = RuntimeWebToolkitConfig

    def __init__(
        self,
        *,
        service: RuntimeWebService,
    ) -> None:
        """Create the provider."""
        self.service = service

    async def resolve(
        self,
        config: RuntimeWebToolkitConfig,
        context: ResolveContext,
    ) -> Toolkit[RuntimeWebToolkitConfig]:
        """Create one Runtime-independent Session-bound Toolkit."""
        del config
        return RuntimeWebToolkit(
            service=self.service,
            workspace_id=context.workspace_id,
            agent_id=context.agent_id,
            session_id=context.session_id,
        )


def _operation(kind: str, call_id: str) -> RuntimeWebOperation:
    digest = hashlib.sha256(f"{kind}:{call_id}".encode()).hexdigest()
    return RuntimeWebOperation(operation_key=digest)


def _unwrap(result: Result[T, RuntimeWebError]) -> T:
    match result:
        case Success(value):
            return value
        case Failure(error):
            _raise_tool_error(error)
        case _ as unreachable:
            assert_never(unreachable)


def _raise_tool_error(error: RuntimeWebError) -> NoReturn:
    match error:
        case RuntimeWebNotFound():
            message = "Runtime Web service is unavailable in this Session."
        case RuntimeWebAccessDenied():
            message = "Runtime Web service access is denied for this Session."
        case RuntimeWebConflict():
            message = "Runtime Web service state changed; inspect it and retry."
        case RuntimeWebQuotaExceeded(scope=scope):
            message = f"Runtime Web service quota is exhausted for {scope}."
        case RuntimeWebConfigurationUnavailable():
            message = "Runtime Web Gateway is not configured."
        case _ as unreachable:
            assert_never(unreachable)
    raise FunctionToolError(message)


def _projection_payload(
    projection: RuntimeWebServiceProjection,
) -> dict[str, object]:
    endpoint = projection.endpoint
    request = projection.current_request
    cycle = projection.current_cycle
    return {
        "endpoint_id": endpoint.id,
        "port": endpoint.port,
        "label": endpoint.label,
        "url": projection.url,
        "configuration_state": projection.configuration_state,
        "endpoint_revision": endpoint.authority_revision,
        "close_barrier": endpoint.close_barrier,
        "request": (
            None
            if request is None
            else {
                "id": request.id,
                "state": request.state.value,
                "revision": request.revision,
            }
        ),
        "cycle": (
            None
            if cycle is None
            else {
                "id": cycle.id,
                "expires_at": cycle.expires_at.isoformat(),
                "ended_at": (
                    None if cycle.ended_at is None else cycle.ended_at.isoformat()
                ),
                "end_reason": (
                    None if cycle.end_reason is None else cycle.end_reason.value
                ),
            }
        ),
        "active": projection.active,
        "duration_seconds": projection.duration_seconds,
        "duration_configuration_revision": (projection.duration_configuration_revision),
        "observed_at": projection.observed_at.isoformat(),
    }


def _projection_result(
    projection: RuntimeWebServiceProjection,
    metadata_kind: str,
) -> FunctionToolResult:
    payload = _projection_payload(projection)
    url = projection.url
    if url is None:
        raise FunctionToolError(
            "Runtime Web Gateway is not configured for a usable service URL."
        )
    request = projection.current_request
    cycle = projection.current_cycle
    metadata: JSONObject = {
        "kind": metadata_kind,
        "endpoint_id": projection.endpoint.id,
        "port": projection.endpoint.port,
        "url": url,
        "endpoint_revision": projection.endpoint.authority_revision,
        "request_id": None if request is None else request.id,
        "request_revision": None if request is None else request.revision,
        "cycle_id": None if cycle is None else cycle.id,
    }
    return FunctionToolResult(
        output=json.dumps(payload, sort_keys=True),
        metadata=metadata,
    )


def _page_payload(
    page: RuntimeWebServicePage,
) -> dict[str, object]:
    return {
        "items": [_projection_payload(item) for item in page.items],
        "total_count": page.total_count,
    }
