"""Runtime-independent Runtime Web Toolkit tests."""

import datetime
import json
from unittest.mock import AsyncMock

import pytest
from azcommon.result import Failure, Success

from azents.core.tools import TurnContext
from azents.engine.run.types import FunctionTool, FunctionToolError, FunctionToolResult
from azents.engine.tooling.execution_context import client_tool_execution_context
from azents.engine.tools.runtime_web import RuntimeWebToolkit
from azents.rdb.models.runtime_web import (
    RuntimeWebRequesterKind,
    RuntimeWebRequestState,
)
from azents.repos.runtime_web.data import RuntimeWebEndpoint, RuntimeWebRequest
from azents.services.runtime_web.data import (
    RuntimeWebConfigurationUnavailable,
    RuntimeWebServicePage,
    RuntimeWebServiceProjection,
)
from azents.services.runtime_web.service import RuntimeWebService

_NOW = datetime.datetime(2026, 9, 12, 0, 0, tzinfo=datetime.UTC)


def _projection(
    *, url: str | None = "https://service.example.test"
) -> RuntimeWebServiceProjection:
    endpoint = RuntimeWebEndpoint(
        id="endpoint-1",
        workspace_id="workspace-1",
        agent_id="agent-1",
        agent_session_id="session-1",
        port=3000,
        hostname_key="host-key",
        label="Preview",
        authority_revision=2,
        close_barrier=0,
        current_pending_request_id="request-1",
        current_cycle_id=None,
        created_at=_NOW,
        updated_at=_NOW,
    )
    request = RuntimeWebRequest(
        id="request-1",
        endpoint_id=endpoint.id,
        requester_kind=RuntimeWebRequesterKind.AGENT,
        operation_key="operation",
        state=RuntimeWebRequestState.PENDING,
        revision=1,
        requester_user_id=None,
        requester_agent_id="agent-1",
        requester_execution_id="run-1",
        requester_call_id="call-1",
        label_snapshot="Preview",
        decided_by_user_id=None,
        decided_at=None,
        created_at=_NOW,
        updated_at=_NOW,
    )
    return RuntimeWebServiceProjection(
        endpoint=endpoint,
        url=url,
        configuration_state="configured" if url is not None else "unconfigured",
        current_request=request,
        current_cycle=None,
        active=False,
        duration_seconds=7200,
        duration_configuration_revision=1,
        observed_at=_NOW,
    )


def _toolkit(service: RuntimeWebService) -> RuntimeWebToolkit:
    return RuntimeWebToolkit(
        service=service,
        workspace_id="workspace-1",
        agent_id="agent-1",
        session_id="session-1",
    )


async def _tools(service: RuntimeWebService) -> dict[str, FunctionTool]:
    state = await _toolkit(service).update_context(
        TurnContext(
            workspace_id="workspace-1",
            model="model",
            run_id="run-1",
            session_id="session-1",
            publish_event=AsyncMock(),
        )
    )
    return {tool.spec.name: tool for tool in state.tools}


async def test_runtime_web_toolkit_exposes_runtime_independent_controls() -> None:
    """The Toolkit exposes control tools without a Runtime capability check."""
    tools = await _tools(AsyncMock(spec=RuntimeWebService))

    assert set(tools) == {
        "prepare_web_service",
        "request_web_service",
        "list_web_services",
        "cancel_web_service_request",
        "close_web_service",
    }


async def test_request_tool_returns_pending_result_without_extra_prepare() -> None:
    """The request tool returns its durable request immediately and only once."""
    service = AsyncMock(spec=RuntimeWebService)
    service.request_exposure.return_value = Success(_projection())
    tools = await _tools(service)

    with client_tool_execution_context(call_id="call-1", name="request_web_service"):
        result = await tools["request_web_service"].handler(
            '{"port":3000,"label":"Preview"}'
        )

    assert isinstance(result, FunctionToolResult)
    assert result.metadata == {
        "kind": "runtime_web_service_request",
        "endpoint_id": "endpoint-1",
        "port": 3000,
        "url": "https://service.example.test",
        "endpoint_revision": 2,
        "request_id": "request-1",
        "request_revision": 1,
        "cycle_id": None,
    }
    assert isinstance(result.output, str)
    assert json.loads(result.output)["request"]["state"] == "pending"
    service.prepare_endpoint.assert_not_awaited()
    _, kwargs = service.request_exposure.await_args
    assert kwargs["user_id"] is None
    assert kwargs["actor"].execution_id == "run-1"
    assert kwargs["actor"].call_id == "call-1"


async def test_request_tool_reports_unconfigured_gateway() -> None:
    """Configuration failure is bounded and never claims a usable URL."""
    service = AsyncMock(spec=RuntimeWebService)
    service.request_exposure.return_value = Failure(
        RuntimeWebConfigurationUnavailable()
    )
    tools = await _tools(service)

    with (
        client_tool_execution_context(call_id="call-1", name="request_web_service"),
        pytest.raises(FunctionToolError, match="not configured"),
    ):
        await tools["request_web_service"].handler('{"port":3000,"label":null}')


async def test_list_cancel_and_close_use_exact_session_resources() -> None:
    """List and mutations retain exact request/cycle revisions and Session identity."""
    service = AsyncMock(spec=RuntimeWebService)
    projection = _projection()
    service.list_services.return_value = Success(
        RuntimeWebServicePage(items=[projection], total_count=1)
    )
    service.cancel_request.return_value = Success(projection)
    service.close_cycle.return_value = Success(projection)
    tools = await _tools(service)

    listed = await tools["list_web_services"].handler("{}")
    assert isinstance(listed, str)
    assert json.loads(listed)["total_count"] == 1

    with client_tool_execution_context(call_id="cancel-call", name="cancel"):
        await tools["cancel_web_service_request"].handler(
            '{"request_id":"request-1","expected_revision":3}'
        )
    _, cancel = service.cancel_request.await_args
    assert cancel["session_id"] == "session-1"
    assert cancel["request_id"] == "request-1"
    assert cancel["expected_revision"] == 3

    with client_tool_execution_context(call_id="close-call", name="close"):
        await tools["close_web_service"].handler(
            '{"cycle_id":"cycle-1","expected_endpoint_revision":7}'
        )
    _, close = service.close_cycle.await_args
    assert close["session_id"] == "session-1"
    assert close["cycle_id"] == "cycle-1"
    assert close["expected_endpoint_revision"] == 7
