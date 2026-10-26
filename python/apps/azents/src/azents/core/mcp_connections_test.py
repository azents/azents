"""Deterministic integration of retained connections with the pinned MCP SDK."""

import asyncio
import json
from collections import Counter
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager
from functools import partial
from unittest.mock import AsyncMock

import httpx2 as httpx
import pytest
from mcp import MCPError
from mcp.client.session import ClientSession, MessageHandlerFnT
from mcp.types import (
    CallToolResult,
    ListToolsResult,
    TextContent,
    ToolListChangedNotification,
)
from pydantic import BaseModel, ConfigDict

from azents.core import mcp_connections, mcp_transport
from azents.core.mcp_connections import McpConnections
from azents.core.mcp_transport import McpToolListResult


class _Params(BaseModel):
    model_config = ConfigDict(extra="ignore")
    cursor: str | None = None
    arguments: dict[str, str] | None = None


class _Wire(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: int | str | None = None
    method: str
    params: _Params | None = None


class _Server:
    def __init__(self) -> None:
        self.counts: Counter[str] = Counter()
        self.slow_started = asyncio.Event()
        self.slow_release = asyncio.Event()
        self.fail = False
        self.slow_cancelled = False
        self.headers: list[str] = []
        self.listing_started = asyncio.Event()
        self.listing_release: asyncio.Event | None = None

    async def respond(self, request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(405)
        if request.method == "DELETE":
            self.counts["DELETE"] += 1
            return httpx.Response(204)
        message = _Wire.model_validate_json(request.content)
        self.counts[message.method] += 1
        self.headers.append(request.headers.get("authorization", "none"))
        if message.method == "initialize":
            return httpx.Response(
                200,
                headers={"mcp-session-id": "fixture-session"},
                json={
                    "jsonrpc": "2.0",
                    "id": message.id,
                    "result": {
                        "protocolVersion": "2025-11-25",
                        "capabilities": {"tools": {}},
                        "serverInfo": {"name": "fixture", "version": "1"},
                    },
                },
            )
        if message.id is None:
            if message.method == "notifications/cancelled":
                self.slow_cancelled = True
                self.slow_release.set()
            return httpx.Response(202)
        result: dict[str, object]
        if message.method == "tools/list":
            page_two = message.params is not None and message.params.cursor is not None
            if page_two and self.listing_release is not None:
                self.listing_started.set()
                await self.listing_release.wait()
            result = {
                "tools": [
                    {
                        "name": "other" if page_two else "echo",
                        "inputSchema": {"type": "object"},
                    }
                ]
            }
            if not page_two:
                result["nextCursor"] = "page-two"
        elif message.method == "tools/call":
            assert message.params is not None
            assert message.params.arguments is not None
            value = message.params.arguments["value"]
            if self.fail:
                self.fail = False
                return httpx.Response(
                    200,
                    json={
                        "jsonrpc": "2.0",
                        "id": message.id,
                        "error": {"code": -32600, "message": "Session terminated"},
                    },
                )
            if value == "slow":
                self.slow_started.set()
                await self.slow_release.wait()
                if self.slow_cancelled:
                    return httpx.Response(202)
            result = {"content": [{"type": "text", "text": value}]}
        else:
            raise AssertionError(message.method)
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": message.id,
                "result": result,
            },
        )


@pytest.fixture
def server(monkeypatch: pytest.MonkeyPatch) -> _Server:
    server = _Server()
    client = httpx.AsyncClient
    monkeypatch.setattr(
        mcp_transport.httpx,
        "AsyncClient",
        partial(client, transport=httpx.MockTransport(server.respond)),
    )
    monkeypatch.setattr(
        mcp_connections,
        "_GuardedClient",
        partial(
            mcp_connections._GuardedClient,
            transport=httpx.MockTransport(server.respond),
        ),
    )
    return server


async def _call(
    connections: McpConnections,
    value: str,
    *,
    token: str = "first",
    auth: httpx.Auth | None = None,
) -> CallToolResult:
    return await connections.call_tool(
        "https://fixture.test/mcp",
        {"Authorization": f"Bearer {token}"},
        5,
        "echo",
        {"value": value},
        use_streamable_http=True,
        proxy_url=None,
        auth=auth,
        auth_identity="observer" if auth is not None else None,
        before_send=None,
    )


async def _list(connections: McpConnections) -> McpToolListResult:
    return await connections.list_tools(
        "https://fixture.test/mcp",
        {"Authorization": "Bearer first"},
        5,
        proxy_url=None,
        auth=None,
        auth_identity=None,
        before_send=None,
    )


async def test_parallel_and_sequential_calls_share_complete_preparation(
    server: _Server,
) -> None:
    connections = McpConnections()
    try:
        results = await asyncio.gather(*(_call(connections, str(i)) for i in range(20)))
        assert [result.content[0] for result in results] == [
            TextContent(type="text", text=str(i)) for i in range(20)
        ]
        await _call(connections, "later")
        listing = await _list(connections)
        assert [tool.name for tool in listing.tools] == ["echo", "other"]
        assert server.counts["initialize"] == 1
        assert (
            server.counts["tools/list"] == 2
        )  # Exactly one complete, paginated listing.
        assert server.counts["tools/call"] == 21
    finally:
        await connections.close()
    assert server.counts["DELETE"] == 1


async def test_credential_rotation_and_binding_isolation(server: _Server) -> None:
    first, second = McpConnections(), McpConnections()
    try:
        await _call(first, "one")
        await _call(first, "two", token="replacement")
        await _call(second, "three", token="replacement")
        assert server.counts["initialize"] == 3
        assert "Bearer replacement" in server.headers
    finally:
        await asyncio.gather(first.close(), second.close())
    assert server.counts["DELETE"] == 3


class _Observer(httpx.Auth):
    def __init__(self) -> None:
        self.seen: list[int] = []

    async def async_auth_flow(
        self,
        request: httpx.Request,
    ) -> AsyncGenerator[httpx.Request, httpx.Response]:
        response = yield request
        self.seen.append(response.status_code)


async def test_request_local_auth_observers_are_not_shared(server: _Server) -> None:
    connections = McpConnections()
    initial, one, two = _Observer(), _Observer(), _Observer()
    try:
        await _call(connections, "prepare", auth=initial)
        await asyncio.gather(
            _call(connections, "one", auth=one), _call(connections, "two", auth=two)
        )
        assert one.seen == [200]
        assert two.seen == [200]
        assert server.counts["initialize"] == 1
    finally:
        await connections.close()


async def test_cancellation_does_not_close_shared_session(server: _Server) -> None:
    connections = McpConnections()
    try:
        slow = asyncio.create_task(_call(connections, "slow"))
        await server.slow_started.wait()
        slow.cancel()
        with pytest.raises(asyncio.CancelledError):
            await slow
        await server.slow_release.wait()
        assert (await _call(connections, "survivor")).content[0] == TextContent(
            type="text", text="survivor"
        )
        assert server.counts["initialize"] == 1
    finally:
        await connections.close()


async def test_failure_is_not_replayed_and_later_call_reconnects(
    server: _Server,
) -> None:
    connections = McpConnections()
    try:
        await _call(connections, "prepare")
        server.fail = True
        with pytest.raises(MCPError, match="Session terminated"):
            await _call(connections, "write-once")
        assert server.counts["tools/call"] == 2
        await _call(connections, "later")
        assert server.counts["initialize"] == 2
        assert server.counts["tools/call"] == 3
    finally:
        await connections.close()


async def test_sse_negotiation_is_retained(monkeypatch: pytest.MonkeyPatch) -> None:
    opened: list[bool] = []
    session = AsyncMock(spec=ClientSession)
    session.list_tools.return_value = ListToolsResult(tools=[])

    @asynccontextmanager
    async def open_session(
        url: str,
        headers: dict[str, str],
        timeout: float,
        *,
        use_streamable_http: bool,
        proxy_url: str | None,
        auth: httpx.Auth,
        message_handler: object,
        http_client_type: object,
    ) -> AsyncGenerator[ClientSession]:
        opened.append(use_streamable_http)
        if use_streamable_http:
            request = httpx.Request("POST", url)
            response = httpx.Response(405, request=request)
            raise httpx.HTTPStatusError(
                "unsupported", request=request, response=response
            )
        yield session

    monkeypatch.setattr(mcp_connections, "_mcp_session", open_session)
    connections = McpConnections()
    try:
        assert (await _list(connections)).use_streamable_http is False
        assert (await _list(connections)).use_streamable_http is False
        assert opened == [True, False]
    finally:
        await connections.close()


async def test_close_waits_for_cancelled_operation_before_context_exit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started, unwound = asyncio.Event(), asyncio.Event()
    session = AsyncMock(spec=ClientSession)
    session.list_tools.return_value = ListToolsResult(tools=[])

    async def call(*args: object, **kwargs: object) -> CallToolResult:
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            unwound.set()
        raise AssertionError("unreachable")

    session.call_tool.side_effect = call

    @asynccontextmanager
    async def open_session(
        *args: object, **kwargs: object
    ) -> AsyncGenerator[ClientSession]:
        try:
            yield session
        finally:
            assert unwound.is_set()

    monkeypatch.setattr(mcp_connections, "_mcp_session", open_session)
    connections = McpConnections()
    caller = asyncio.create_task(_call(connections, "wait"))
    await started.wait()
    await connections.close()
    with pytest.raises(asyncio.CancelledError):
        await caller
    assert unwound.is_set()


async def test_authority_is_rechecked_after_preparation_wait(server: _Server) -> None:
    server.listing_release = asyncio.Event()
    permitted = True

    async def validate() -> None:
        if not permitted:
            raise PermissionError("Authority was revoked")

    connections = McpConnections()
    caller = asyncio.create_task(
        connections.call_tool(
            "https://fixture.test/mcp",
            {},
            5,
            "echo",
            {"value": "denied"},
            use_streamable_http=True,
            proxy_url=None,
            auth=None,
            auth_identity=None,
            before_send=validate,
        )
    )
    try:
        await server.listing_started.wait()
        permitted = False
        server.listing_release.set()
        with pytest.raises(PermissionError, match="revoked"):
            await caller
        assert server.counts["tools/call"] == 0
    finally:
        await connections.close()


async def test_fresh_listing_skips_io_and_expiry_refreshes_without_reinitializing(
    server: _Server,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connections = McpConnections()
    try:
        await _list(connections)
        await _list(connections)
        assert server.counts["tools/list"] == 2
        monkeypatch.setattr(mcp_connections, "FRESHNESS_SECONDS", -1.0)
        await _list(connections)
        assert server.counts["initialize"] == 1
        assert server.counts["tools/list"] == 4
    finally:
        await connections.close()


async def test_cancelled_preparation_waiter_does_not_cancel_other_waiters(
    server: _Server,
) -> None:
    connections = McpConnections()
    server.listing_release = asyncio.Event()
    first = asyncio.create_task(_call(connections, "first"))
    await server.listing_started.wait()
    second = asyncio.create_task(_call(connections, "second"))
    first.cancel()
    try:
        with pytest.raises(asyncio.CancelledError):
            await first
        server.listing_release.set()
        assert (await second).content[0] == TextContent(type="text", text="second")
        assert server.counts["initialize"] == 1
    finally:
        await connections.close()


async def test_preparation_timeout_does_not_enter_sdk_task_group(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The timeout crosses the SDK context only during cleanup."""
    session = AsyncMock(spec=ClientSession)
    session.list_tools = AsyncMock(side_effect=TimeoutError("preparation"))

    @asynccontextmanager
    async def open_session(
        *args: object, **kwargs: object
    ) -> AsyncGenerator[ClientSession]:
        try:
            yield session
        except TimeoutError as exc:
            raise ExceptionGroup("sdk cleanup", [exc]) from exc

    monkeypatch.setattr(mcp_connections, "_mcp_session", open_session)
    connections = McpConnections()
    try:
        with pytest.raises(TimeoutError, match="preparation"):
            await _list(connections)
    finally:
        await connections.close()


@pytest.mark.parametrize(
    "error",
    [
        ExceptionGroup("sdk", [TimeoutError("preparation")]),
        ExceptionGroup(
            "outer", [ExceptionGroup("inner", [TimeoutError("preparation")])]
        ),
    ],
)
async def test_preparation_timeout_wrapped_during_sdk_enter_is_preserved(
    monkeypatch: pytest.MonkeyPatch, error: ExceptionGroup
) -> None:
    @asynccontextmanager
    async def open_session(
        *args: object, **kwargs: object
    ) -> AsyncGenerator[ClientSession]:
        raise error
        yield

    monkeypatch.setattr(mcp_connections, "_mcp_session", open_session)
    connections = McpConnections()
    try:
        with pytest.raises(TimeoutError, match="preparation"):
            await _list(connections)
    finally:
        await connections.close()


async def test_preparation_timeout_and_cleanup_error_are_both_retained(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    timeout = TimeoutError("preparation")
    cleanup = ValueError("cleanup failed")
    session = AsyncMock(spec=ClientSession)
    session.list_tools = AsyncMock(side_effect=timeout)

    @asynccontextmanager
    async def open_session(
        *args: object, **kwargs: object
    ) -> AsyncGenerator[ClientSession]:
        try:
            yield session
        finally:
            raise cleanup

    monkeypatch.setattr(mcp_connections, "_mcp_session", open_session)
    connections = McpConnections()
    try:
        with pytest.raises(ExceptionGroup) as caught:
            await _list(connections)
        assert caught.value.exceptions == (timeout, cleanup)
    finally:
        await connections.close()


async def test_mixed_sdk_enter_errors_are_not_discarded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    error = ExceptionGroup(
        "mixed", [TimeoutError("preparation"), ValueError("cleanup failed")]
    )

    @asynccontextmanager
    async def open_session(
        *args: object, **kwargs: object
    ) -> AsyncGenerator[ClientSession]:
        raise error
        yield

    monkeypatch.setattr(mcp_connections, "_mcp_session", open_session)
    connections = McpConnections()
    try:
        with pytest.raises(ExceptionGroup) as caught:
            await _list(connections)
        assert caught.value is error
    finally:
        await connections.close()


async def test_readiness_and_cleanup_are_bounded(server: _Server) -> None:
    connections = McpConnections()
    server.listing_release = asyncio.Event()
    try:
        with pytest.raises(TimeoutError):
            await connections.call_tool(
                "https://fixture.test/mcp",
                {},
                0.02,
                "echo",
                {},
                use_streamable_http=True,
                proxy_url=None,
                auth=None,
                auth_identity=None,
                before_send=None,
            )
        assert server.counts["tools/call"] == 0
    finally:
        server.listing_release.set()
        await connections.close()


async def test_list_change_notification_invalidates_fresh_listing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    handlers: list[MessageHandlerFnT] = []
    session = AsyncMock(spec=ClientSession)
    session.list_tools.return_value = ListToolsResult(tools=[])

    @asynccontextmanager
    async def open_session(
        *args: object,
        message_handler: MessageHandlerFnT,
        **kwargs: object,
    ) -> AsyncGenerator[ClientSession]:
        handlers.append(message_handler)
        yield session

    monkeypatch.setattr(mcp_connections, "_mcp_session", open_session)
    connections = McpConnections()
    try:
        await _list(connections)
        await _list(connections)
        assert session.list_tools.await_count == 1
        await handlers[0](
            ToolListChangedNotification(method="notifications/tools/list_changed")
        )
        assert connections.stale
        await _list(connections)
        assert session.list_tools.await_count == 2
        assert len(handlers) == 1
    finally:
        await connections.close()


async def test_cleanup_deadline_does_not_wait_for_resistant_owner(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    session = AsyncMock(spec=ClientSession)
    session.list_tools.return_value = ListToolsResult(tools=[])
    release, finished = asyncio.Event(), asyncio.Event()

    @asynccontextmanager
    async def open_session(
        *args: object,
        **kwargs: object,
    ) -> AsyncGenerator[ClientSession]:
        try:
            yield session
        finally:
            try:
                await release.wait()
            except asyncio.CancelledError:
                await release.wait()
            finished.set()

    monkeypatch.setattr(mcp_connections, "_mcp_session", open_session)
    monkeypatch.setattr(mcp_connections, "_CLEANUP_SECONDS", 0.02)
    connections = McpConnections()
    await _list(connections)
    try:
        async with asyncio.timeout(1):
            await connections.close()
        assert "cleanup exceeded its deadline" in caplog.text
        assert not finished.is_set()
    finally:
        release.set()
        await finished.wait()


async def test_wire_admission_denial_does_not_abort_sibling(server: _Server) -> None:
    connections = McpConnections()
    checks = 0

    async def reject_only_at_wire() -> None:
        nonlocal checks
        checks += 1
        if checks == 2:
            raise PermissionError("Dispatch authority was revoked")

    try:
        await _call(connections, "prepare")
        survivor = asyncio.create_task(_call(connections, "slow"))
        await server.slow_started.wait()
        with pytest.raises(PermissionError, match="revoked"):
            await connections.call_tool(
                "https://fixture.test/mcp",
                {"Authorization": "Bearer first"},
                5,
                "echo",
                {"value": "denied"},
                use_streamable_http=True,
                proxy_url=None,
                auth=None,
                auth_identity=None,
                before_send=reject_only_at_wire,
            )
        assert server.counts["tools/call"] == 2
        server.slow_release.set()
        assert (await survivor).content[0] == TextContent(type="text", text="slow")
        await _call(connections, "after-denial")
        assert server.counts["initialize"] == 1
    finally:
        await connections.close()


async def test_initial_notification_denial_is_local_and_next_call_can_connect(
    server: _Server,
) -> None:
    connections = McpConnections()
    checks = 0

    async def deny_initialized_notification() -> None:
        nonlocal checks
        checks += 1
        if checks >= 2:
            raise PermissionError("Initialization authority changed")

    try:
        with pytest.raises(PermissionError, match="authority changed"):
            await connections.call_tool(
                "https://fixture.test/mcp",
                {},
                5,
                "echo",
                {"value": "denied"},
                use_streamable_http=True,
                proxy_url=None,
                auth=None,
                auth_identity=None,
                before_send=deny_initialized_notification,
            )
        assert server.counts["tools/call"] == 0
        assert server.counts["notifications/initialized"] == 0
        await _call(connections, "allowed")
        assert server.counts["tools/call"] == 1
    finally:
        await connections.close()


class _SseStream(httpx.AsyncByteStream):
    def __init__(self) -> None:
        self.events: asyncio.Queue[bytes] = asyncio.Queue()

    async def __aiter__(self) -> AsyncGenerator[bytes]:
        yield b"event: endpoint\ndata: /messages\n\n"
        while True:
            yield await self.events.get()

    async def reply(
        self, request_id: int | str | None, result: dict[str, object]
    ) -> None:
        payload = json.dumps({"jsonrpc": "2.0", "id": request_id, "result": result})
        await self.events.put(f"event: message\ndata: {payload}\n\n".encode())


@pytest.mark.parametrize("during_initialization", [False, True])
async def test_real_sse_wire_denial_preserves_writer_and_sibling(
    monkeypatch: pytest.MonkeyPatch,
    during_initialization: bool,
) -> None:
    stream = _SseStream()
    counts: Counter[str] = Counter()
    slow_started = asyncio.Event()
    slow_id: int | str | None = None

    async def respond(request: httpx.Request) -> httpx.Response:
        nonlocal slow_id
        if request.method == "GET":
            return httpx.Response(
                200,
                headers={"Content-Type": "text/event-stream"},
                stream=stream,
            )
        if request.url.path == "/sse":
            return httpx.Response(405)
        message = _Wire.model_validate_json(request.content)
        counts[message.method] += 1
        if message.id is None:
            return httpx.Response(202)
        result: dict[str, object]
        if message.method == "initialize":
            result = {
                "protocolVersion": "2025-11-25",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "legacy-fixture", "version": "1"},
            }
        elif message.method == "tools/list":
            result = {"tools": [{"name": "echo", "inputSchema": {"type": "object"}}]}
        else:
            assert message.params is not None
            assert message.params.arguments is not None
            value = message.params.arguments["value"]
            if value == "slow":
                slow_id = message.id
                slow_started.set()
                return httpx.Response(202)
            result = {"content": [{"type": "text", "text": value}]}
        await stream.reply(message.id, result)
        return httpx.Response(202)

    monkeypatch.setattr(
        mcp_connections,
        "_GuardedClient",
        partial(mcp_connections._GuardedClient, transport=httpx.MockTransport(respond)),
    )
    connections = McpConnections()
    checks = 0

    async def deny_at_wire() -> None:
        nonlocal checks
        checks += 1
        if checks >= 2:
            raise PermissionError("Legacy dispatch authority denied")

    async def call(
        value: str,
        validate: Callable[[], Awaitable[None]] | None = None,
    ) -> CallToolResult:
        return await connections.call_tool(
            "https://fixture.test/sse",
            {},
            5,
            "echo",
            {"value": value},
            use_streamable_http=False,
            proxy_url=None,
            auth=None,
            auth_identity=None,
            before_send=validate,
        )

    try:
        if during_initialization:
            with pytest.raises(PermissionError, match="Legacy dispatch"):
                await call("initial-denied", deny_at_wire)
            assert counts["tools/call"] == 0
            assert counts["notifications/initialized"] == 0
            assert (await call("new-connection")).content[0] == TextContent(
                type="text", text="new-connection"
            )
            return
        await call("prepare")
        survivor = asyncio.create_task(call("slow"))
        await slow_started.wait()
        with pytest.raises(PermissionError, match="Legacy dispatch"):
            await call("denied", deny_at_wire)
        await stream.reply(slow_id, {"content": [{"type": "text", "text": "survived"}]})
        assert (await survivor).content[0] == TextContent(type="text", text="survived")
        assert (await call("after")).content[0] == TextContent(
            type="text", text="after"
        )
        assert counts["initialize"] == 1
        assert counts["tools/call"] == 3
    finally:
        await connections.close()


@pytest.mark.parametrize(
    "failure",
    [
        MCPError(-32602, "Invalid request arguments"),
        ValueError("Result validation failed"),
        PermissionError("Call-local admission failed"),
        TimeoutError("Call-local deadline expired"),
    ],
)
async def test_local_failure_does_not_poison_queued_sibling(
    monkeypatch: pytest.MonkeyPatch,
    failure: Exception,
) -> None:
    occupied, queued = asyncio.Event(), asyncio.Event()
    reject, release = asyncio.Event(), asyncio.Event()
    entered = 0

    class Capacity(asyncio.Semaphore):
        async def __aenter__(self) -> None:
            nonlocal entered
            entered += 1
            if entered == 17:
                queued.set()
            await super().__aenter__()

    calls = 0
    session = AsyncMock(spec=ClientSession)
    session.list_tools.return_value = ListToolsResult(tools=[])

    async def call(
        name: str,
        *,
        arguments: dict[str, object],
    ) -> CallToolResult:
        nonlocal calls
        calls += 1
        if calls == 16:
            occupied.set()
        value = arguments["value"]
        if value == "reject":
            await reject.wait()
            raise failure
        if value != "queued":
            await release.wait()
        return CallToolResult(content=[TextContent(type="text", text=str(value))])

    session.call_tool.side_effect = call

    @asynccontextmanager
    async def open_session(
        *args: object,
        **kwargs: object,
    ) -> AsyncGenerator[ClientSession]:
        yield session

    monkeypatch.setattr(mcp_connections.asyncio, "Semaphore", Capacity)
    monkeypatch.setattr(mcp_connections, "_mcp_session", open_session)
    connections = McpConnections()
    denied = asyncio.create_task(_call(connections, "reject"))
    siblings = [asyncio.create_task(_call(connections, str(i))) for i in range(15)]
    try:
        await occupied.wait()
        waiting = asyncio.create_task(_call(connections, "queued"))
        await queued.wait()
        reject.set()
        with pytest.raises(type(failure)) as caught:
            await denied
        assert caught.value is failure
        assert (await waiting).content[0] == TextContent(type="text", text="queued")
        release.set()
        await asyncio.gather(*siblings)
        assert calls == 17
    finally:
        release.set()
        await connections.close()
