"""Agent-scoped Runtime Web Toolkit tests."""

import datetime
import json
from unittest.mock import AsyncMock

import pytest
from azcommon.result import Failure, Success

from azents.core.tools import TurnContext
from azents.engine.run.types import FunctionTool, FunctionToolError, FunctionToolResult
from azents.engine.tooling.execution_context import client_tool_execution_context
from azents.engine.tools.runtime_web import RuntimeWebToolkit
from azents.services.runtime_web.data import (
    RuntimeWebCapabilityUnavailable,
    RuntimeWebServicePage,
    RuntimeWebServiceProjection,
)
from azents.services.runtime_web.service import RuntimeWebService

_NOW = datetime.datetime(2026, 9, 15, 0, 0, tzinfo=datetime.UTC)
_SERVICE_ID = "s" * 32


def _projection(
    *,
    url: str | None = "https://service.example.test",
) -> RuntimeWebServiceProjection:
    return RuntimeWebServiceProjection(
        id=_SERVICE_ID,
        port=3000,
        label="Preview",
        url=url,
        configuration_state="configured" if url is not None else "unconfigured",
        on=False,
        selected_duration_seconds=3_600,
        expires_at=None,
        revision=2,
        created_at=_NOW,
        updated_at=_NOW,
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


async def test_runtime_web_toolkit_exposes_exact_agent_service_controls() -> None:
    tools = await _tools(AsyncMock(spec=RuntimeWebService))

    assert set(tools) == {
        "request_web_service",
        "list_web_services",
        "close_web_service",
    }


async def test_request_tool_returns_off_service_and_agent_guidance_metadata() -> None:
    service = AsyncMock(spec=RuntimeWebService)
    service.request_service.return_value = Success(_projection())
    tools = await _tools(service)

    with client_tool_execution_context(call_id="call-1", name="request_web_service"):
        result = await tools["request_web_service"].handler(
            '{"port":3000,"label":"Preview"}'
        )

    assert isinstance(result, FunctionToolResult)
    assert result.metadata == {
        "kind": "runtime_web_service",
        "service_id": _SERVICE_ID,
        "port": 3000,
        "url": "https://service.example.test",
        "revision": 2,
        "expires_at": None,
    }
    assert isinstance(result.output, str)
    payload = json.loads(result.output)
    assert payload["on"] is False
    assert payload["selected_duration_seconds"] == 3_600
    _, kwargs = service.request_service.await_args
    assert kwargs["port"] == 3000
    assert kwargs["actor"].execution_id == "run-1"
    assert kwargs["actor"].call_id == "call-1"


async def test_list_and_close_share_agent_identity_and_exact_service_id() -> None:
    service = AsyncMock(spec=RuntimeWebService)
    projection = _projection()
    service.list_services.return_value = Success(
        RuntimeWebServicePage(items=[projection], total_count=1)
    )
    service.close_service.return_value = Success(projection)
    tools = await _tools(service)

    listed = await tools["list_web_services"].handler("{}")
    assert isinstance(listed, str)
    assert json.loads(listed)["items"][0]["service_id"] == _SERVICE_ID
    _, list_kwargs = service.list_services.await_args
    assert list_kwargs["user_id"] is None
    assert list_kwargs["actor"].actor_id == "agent-1"

    with client_tool_execution_context(call_id="close-call", name="close_web_service"):
        await tools["close_web_service"].handler(
            json.dumps({"service_id": _SERVICE_ID})
        )
    _, close_kwargs = service.close_service.await_args
    assert close_kwargs["service_id"] == _SERVICE_ID
    assert close_kwargs["actor"].execution_id == "run-1"


async def test_mutating_tool_fails_closed_without_managed_runtime() -> None:
    service = AsyncMock(spec=RuntimeWebService)
    service.request_service.return_value = Failure(RuntimeWebCapabilityUnavailable())
    tools = await _tools(service)

    with (
        client_tool_execution_context(call_id="call-1", name="request_web_service"),
        pytest.raises(FunctionToolError, match="managed Runtime"),
    ):
        await tools["request_web_service"].handler('{"port":3000,"label":null}')
