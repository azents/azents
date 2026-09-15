"""Agent-scoped tools for Runtime Web services."""

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
from azents.rdb.models.runtime_web import RuntimeWebActorKind
from azents.services.runtime_web.data import (
    RuntimeWebAccessDenied,
    RuntimeWebActor,
    RuntimeWebCapabilityUnavailable,
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


class RequestWebServiceInput(BaseModel):
    """request_web_service input."""

    model_config = ConfigDict(extra="forbid")

    port: int = Field(ge=1, le=65_535, description="Runtime loopback HTTP port")
    label: str | None = Field(
        max_length=120,
        description="Optional user-facing service label; pass null when absent",
    )


class CloseWebServiceInput(BaseModel):
    """close_web_service input."""

    model_config = ConfigDict(extra="forbid")

    service_id: str = Field(
        min_length=32,
        max_length=32,
        description=(
            "Opaque service ID returned by request_web_service or list_web_services"
        ),
    )


class RuntimeWebToolkit(Toolkit[RuntimeWebToolkitConfig]):
    """Agent-bound Runtime Web service Toolkit."""

    def __init__(
        self,
        *,
        service: RuntimeWebService,
        workspace_id: str,
        agent_id: str,
        session_id: str,
    ) -> None:
        """Create the Agent-bound Toolkit."""
        self.service = service
        self.workspace_id = workspace_id
        self.agent_id = agent_id
        self.session_id = session_id

    async def update_context(self, context: TurnContext) -> ToolkitState:
        """Return the exact Agent service tool set for the current Run."""
        return ToolkitState(
            status=ToolkitStatus.ENABLED,
            tools=[
                self._request_tool(context.run_id),
                self._list_tool(),
                self._close_tool(context.run_id),
            ],
        )

    def _actor(self, execution_id: str, call_id: str | None) -> RuntimeWebActor:
        return RuntimeWebActor(
            kind=RuntimeWebActorKind.AGENT,
            actor_id=self.agent_id,
            execution_id=execution_id,
            call_id=call_id,
        )

    def _request_tool(self, run_id: str) -> FunctionTool:
        async def request_web_service(
            input: RequestWebServiceInput,
        ) -> FunctionToolResult:
            """Create or retrieve an Off service URL for a Runtime port.

            Give the returned URL to the user and ask them to turn the service On.
            Creating the service does not prove that the local application is ready.
            """
            execution = get_client_tool_execution_context()
            projection = _unwrap(
                await self.service.request_service(
                    workspace_id=self.workspace_id,
                    agent_id=self.agent_id,
                    port=input.port,
                    label=input.label,
                    actor=self._actor(run_id, execution.call_id),
                    operation=_operation("request", execution.call_id),
                )
            )
            return _projection_result(projection)

        return make_tool(request_web_service, input_model=RequestWebServiceInput)

    def _list_tool(self) -> FunctionTool:
        async def list_web_services() -> str:
            """List services shared by every Session of this Agent."""
            page = _unwrap(
                await self.service.list_services(
                    workspace_id=self.workspace_id,
                    agent_id=self.agent_id,
                    user_id=None,
                    workspace_user_id=None,
                    role=None,
                    offset=0,
                    limit=100,
                    actor=self._actor(self.session_id, None),
                )
            )
            return json.dumps(_page_payload(page), sort_keys=True)

        return make_tool(list_web_services)

    def _close_tool(self, run_id: str) -> FunctionTool:
        async def close_web_service(input: CloseWebServiceInput) -> FunctionToolResult:
            """Turn one exact service Off without stopping its Runtime process."""
            execution = get_client_tool_execution_context()
            projection = _unwrap(
                await self.service.close_service(
                    workspace_id=self.workspace_id,
                    agent_id=self.agent_id,
                    service_id=input.service_id,
                    actor=self._actor(run_id, execution.call_id),
                    operation=_operation("close", execution.call_id),
                )
            )
            return _projection_result(projection)

        return make_tool(close_web_service, input_model=CloseWebServiceInput)


class RuntimeWebToolkitProvider(ToolkitProvider[RuntimeWebToolkitConfig]):
    """Provider for Agent-scoped Runtime Web service control."""

    slug = "runtime_web"
    name = "Runtime Web"
    description = "Request, list, and close Agent Runtime web services"
    system_prompt = ""
    config_model = RuntimeWebToolkitConfig

    def __init__(self, *, service: RuntimeWebService) -> None:
        """Create the provider."""
        self.service = service

    async def resolve(
        self,
        config: RuntimeWebToolkitConfig,
        context: ResolveContext,
    ) -> Toolkit[RuntimeWebToolkitConfig]:
        """Create one Agent-bound Toolkit."""
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
            message = "Runtime Web service is unavailable for this Agent."
        case RuntimeWebAccessDenied():
            message = "Runtime Web service access is denied for this Agent."
        case RuntimeWebConflict():
            message = "Runtime Web service state changed; inspect it and retry."
        case RuntimeWebQuotaExceeded(scope=scope):
            message = f"Runtime Web service quota is exhausted for {scope}."
        case RuntimeWebConfigurationUnavailable():
            message = "Runtime Web Gateway is not configured."
        case RuntimeWebCapabilityUnavailable():
            message = "This Agent does not have a managed Runtime."
        case _ as unreachable:
            assert_never(unreachable)
    raise FunctionToolError(message)


def _projection_payload(projection: RuntimeWebServiceProjection) -> dict[str, object]:
    return {
        "service_id": projection.id,
        "port": projection.port,
        "label": projection.label,
        "url": projection.url,
        "configuration_state": projection.configuration_state,
        "on": projection.on,
        "selected_duration_seconds": projection.selected_duration_seconds,
        "expires_at": (
            None if projection.expires_at is None else projection.expires_at.isoformat()
        ),
        "revision": projection.revision,
        "observed_at": projection.observed_at.isoformat(),
    }


def _projection_result(projection: RuntimeWebServiceProjection) -> FunctionToolResult:
    payload = _projection_payload(projection)
    if projection.url is None:
        raise FunctionToolError(
            "Runtime Web Gateway is not configured for a usable service URL."
        )
    metadata: JSONObject = {
        "kind": "runtime_web_service",
        "service_id": projection.id,
        "port": projection.port,
        "url": projection.url,
        "revision": projection.revision,
        "expires_at": (
            None if projection.expires_at is None else projection.expires_at.isoformat()
        ),
    }
    return FunctionToolResult(
        output=json.dumps(payload, sort_keys=True),
        metadata=metadata,
    )


def _page_payload(page: RuntimeWebServicePage) -> dict[str, object]:
    return {
        "items": [_projection_payload(item) for item in page.items],
        "total_count": page.total_count,
    }
