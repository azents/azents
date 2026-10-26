"""Toolkit-owned MCP connections with task-local authentication and bounded cleanup."""

import asyncio
import contextvars
import dataclasses
import logging
import math
import time
from collections.abc import AsyncGenerator, Awaitable, Callable, Hashable
from contextlib import AsyncExitStack

import httpx2 as httpx
from anyio import BrokenResourceError, ClosedResourceError, EndOfStream
from mcp import MCPError
from mcp.client.session import ClientSession, IncomingMessage
from mcp.types import (
    CONNECTION_CLOSED,
    INVALID_REQUEST,
    CallToolResult,
    ErrorData,
    JSONRPCError,
    JSONRPCMessage,
    JSONRPCRequest,
    PaginatedRequestParams,
    Tool,
    ToolListChangedNotification,
)
from pydantic import TypeAdapter

from azents.core.mcp_transport import (
    McpToolListResult,
    _is_http_405,
    _mcp_session,
    discovery_rate_limit_delay,
)
from azents.utils.logging import sanitized_exception_info

logger = logging.getLogger(__name__)
FRESHNESS_SECONDS = 300.0
_CLEANUP_SECONDS = 10.0


@dataclasses.dataclass(frozen=True, repr=False)
class McpConnectionAuth:
    """Immutable connection identity and request-local authentication behavior."""

    headers: dict[str, str]
    auth: httpx.Auth | None
    identity: Hashable | None
    before_send: Callable[[], Awaitable[None]] | None


@dataclasses.dataclass
class _DispatchState:
    authorization: McpConnectionAuth
    streamable: bool
    caller: asyncio.Task[object] | None
    failure: Exception | None = dataclasses.field(default=None, init=False)


_request_auth: contextvars.ContextVar[_DispatchState] = contextvars.ContextVar(
    "mcp_request_auth"
)
_wire_message = TypeAdapter(JSONRPCMessage)


def _connection_unusable(error: Exception) -> bool:
    """Only session-wide failure invalidates a shared connection."""
    if isinstance(error, ExceptionGroup):
        return any(_connection_unusable(item) for item in error.exceptions)
    if isinstance(error, (BrokenResourceError, ClosedResourceError, EndOfStream)):
        return True
    return isinstance(error, MCPError) and (
        (error.code == CONNECTION_CLOSED and error.message == "Connection closed")
        or (error.code == INVALID_REQUEST and error.message == "Session terminated")
    )


def _single_preparation_timeout(error: Exception) -> TimeoutError | None:
    """Recognize one timeout wrapped only by singleton SDK task groups."""
    while isinstance(error, ExceptionGroup) and len(error.exceptions) == 1:
        error = error.exceptions[0]
    return error if isinstance(error, TimeoutError) else None


class _GuardedClient(httpx.AsyncClient):
    """Contain local admission errors before HTTP dispatch, outside SDK tasks.

    Accept the public default sentinel without importing its private annotation.
    MCP uses configured Auth objects and the SDK's explicit redirect policy.
    """

    async def send(
        self,
        request: httpx.Request,
        *,
        stream: bool = False,
        auth: object = httpx.USE_CLIENT_DEFAULT,
        follow_redirects: object = httpx.USE_CLIENT_DEFAULT,
    ) -> httpx.Response:
        state = _request_auth.get()
        authorization = state.authorization
        if authorization.before_send is not None and request.method == "POST":
            try:
                await authorization.before_send()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                # Hand the exact local failure back to this operation through a
                # typed non-success response. No network I/O occurs, and no error
                # escapes into the SDK's shared transport task group.
                state.failure = exc
                if not state.streamable:
                    # Legacy SSE's shared writer requires 202 for POSTs. Wake
                    # only this operation through cancellation and rethrow its
                    # recorded error; a non-2xx response would close the writer.
                    if state.caller is not None:
                        state.caller.cancel()
                    return httpx.Response(202, request=request)
                message = _wire_message.validate_json(await request.aread())
                rejection = JSONRPCError(
                    jsonrpc="2.0",
                    id=message.id if isinstance(message, JSONRPCRequest) else None,
                    error=ErrorData(
                        code=-32003, message="MCP request admission was denied."
                    ),
                )
                return httpx.Response(
                    403,
                    request=request,
                    json=rejection.model_dump(mode="json", by_alias=True),
                )
        redirects = (
            self.follow_redirects
            if follow_redirects is httpx.USE_CLIENT_DEFAULT
            else follow_redirects
        )
        if not isinstance(redirects, bool):
            raise TypeError("MCP redirect policy must be a boolean")
        if auth is httpx.USE_CLIENT_DEFAULT:
            return await super().send(
                request, stream=stream, follow_redirects=redirects
            )
        if auth is None or isinstance(auth, httpx.Auth):
            return await super().send(
                request, stream=stream, auth=auth, follow_redirects=redirects
            )
        raise TypeError("Managed MCP connections require an HTTP Auth object")


class _ContextAuth(httpx.Auth):
    """Resolve auth in the SDK message's captured context, never shared defaults."""

    requires_request_body = True

    async def async_auth_flow(
        self, request: httpx.Request
    ) -> AsyncGenerator[httpx.Request, httpx.Response]:
        authorization = _request_auth.get().authorization
        request.headers.update(authorization.headers)
        if authorization.auth is None:
            yield request
            return
        flow = authorization.auth.async_auth_flow(request)
        try:
            outgoing = await anext(flow)
            while True:
                response = yield outgoing
                try:
                    outgoing = await flow.asend(response)
                except StopAsyncIteration:
                    break
        finally:
            await flow.aclose()


@dataclasses.dataclass(frozen=True, repr=False)
class _Identity:
    url: str
    streamable: bool
    proxy: str | None
    timeout: float
    headers: tuple[tuple[str, str], ...]
    auth: Hashable | None


class _Connection:
    """Own SDK contexts in one task; caller tasks borrow the initialized session."""

    def __init__(self, identity: _Identity, authorization: McpConnectionAuth) -> None:
        self.identity = identity
        self.authorization = authorization
        self.ready: asyncio.Future[ClientSession] = (
            asyncio.get_running_loop().create_future()
        )
        self.stop = asyncio.Event()
        self.list_lock = asyncio.Lock()
        self.capacity = asyncio.Semaphore(16)
        self.operations: set[asyncio.Task[object]] = set()
        self.tools: list[Tool] = []
        self.listed_at: float | None = None
        self.stale = True
        self.retired = False
        self.owner = asyncio.create_task(self._own(), name="mcp-connection")
        self.ready.add_done_callback(self._observe_ready)

    @staticmethod
    def _observe_ready(future: asyncio.Future[ClientSession]) -> None:
        # Preparation may outlive a cancelled waiter. Consume the Future's error;
        # awaiting it still raises the same error for subsequent waiters.
        if not future.cancelled():
            future.exception()

    async def _message(self, message: IncomingMessage) -> None:
        if isinstance(message, ToolListChangedNotification):
            self.stale = True
        elif isinstance(message, Exception):
            self.retire()

    async def _own(self) -> None:
        state = _DispatchState(
            self.authorization, self.identity.streamable, asyncio.current_task()
        )
        token = _request_auth.set(state)
        try:
            async with AsyncExitStack() as stack:
                try:
                    async with asyncio.timeout(self.identity.timeout):
                        session = await stack.enter_async_context(
                            _mcp_session(
                                self.identity.url,
                                {},
                                self.identity.timeout,
                                use_streamable_http=self.identity.streamable,
                                proxy_url=self.identity.proxy,
                                auth=_ContextAuth(),
                                message_handler=self._message,
                                http_client_type=_GuardedClient,
                            )
                        )
                        await self.list_tools(session)
                        if state.failure is not None:
                            raise state.failure
                except Exception as error:
                    timeout = _single_preparation_timeout(error)
                    if timeout is None:
                        raise
                    # Unwind SDK task groups without injecting this preparation
                    # timeout into them, which would wrap it in ExceptionGroup.
                    await stack.aclose()
                    if timeout is error:
                        raise
                    raise timeout from error
                self.ready.set_result(session)
                logger.debug("MCP connection prepared")
                await self.stop.wait()
        except asyncio.CancelledError:
            if not self.ready.done():
                if state.failure is not None:
                    self.ready.set_exception(state.failure)
                    self.retired = True
                    return
                self.ready.cancel()
            raise
        except Exception as exc:
            # This is a task-lifetime error handoff, not a business-error fallback.
            # Initial errors reach every waiter; asynchronous/cleanup errors are
            # observed once here when there is no live request to receive them.
            self.retired = True
            failure = state.failure if state.failure is not None else exc
            if not self.ready.done():
                self.ready.set_exception(failure)
                if not self.operations:
                    logger.error(
                        "Unobserved MCP preparation failed",
                        exc_info=sanitized_exception_info(
                            failure, message="MCP preparation failed"
                        ),
                    )
            else:
                logger.error(
                    "MCP connection terminated with an error",
                    exc_info=sanitized_exception_info(
                        failure, message="MCP connection failed"
                    ),
                )
        finally:
            _request_auth.reset(token)

    async def list_tools(self, session: ClientSession) -> list[Tool]:
        async with self.list_lock:
            if (
                not self.stale
                and self.listed_at is not None
                and time.monotonic() - self.listed_at < FRESHNESS_SECONDS
            ):
                return self.tools
            tools: list[Tool] = []
            cursor: str | None = None
            seen: set[str] = set()
            # Clear before I/O so a concurrent notification is not lost.
            self.stale = False
            try:
                while True:
                    page = await session.list_tools(
                        params=PaginatedRequestParams(cursor=cursor) if cursor else None
                    )
                    tools.extend(page.tools)
                    cursor = page.next_cursor
                    if cursor is None:
                        break
                    if cursor in seen:
                        raise RuntimeError(
                            "MCP tool listing repeated a pagination cursor"
                        )
                    seen.add(cursor)
            except BaseException:
                self.stale = True
                raise
            self.tools = tools
            self.listed_at = time.monotonic()
            return tools

    def retire(self) -> None:
        self.retired = True
        if not self.operations:
            self.stop.set()

    async def close(self) -> None:
        self.retire()
        for operation in tuple(self.operations):
            operation.cancel()
        if self.operations:
            await asyncio.wait(self.operations, timeout=_CLEANUP_SECONDS / 2)
        self.stop.set()
        _, pending = await asyncio.wait({self.owner}, timeout=_CLEANUP_SECONDS / 2)
        if pending:
            self.owner.cancel()
            logger.error("MCP connection cleanup exceeded its deadline")


class McpConnections:
    """One manager per Toolkit binding; no process-global sessions or credentials."""

    def __init__(self) -> None:
        self._current: dict[str, _Connection] = {}
        self._retiring: set[_Connection] = set()
        self._closed = False

    @property
    def stale(self) -> bool:
        """Whether a prepared connection received a tool-list-change notification."""
        return any(
            connection.stale and connection.listed_at is not None
            for connection in self._current.values()
        )

    def _connection(
        self,
        url: str,
        timeout: float,
        streamable: bool,
        proxy: str | None,
        authorization: McpConnectionAuth,
    ) -> _Connection:
        if self._closed:
            raise RuntimeError("MCP connections are closed")
        identity = _Identity(
            url,
            streamable,
            proxy,
            timeout,
            tuple(
                sorted(
                    (key.casefold(), value)
                    for key, value in authorization.headers.items()
                )
            ),
            authorization.identity,
        )
        current = self._current.get(url)
        if current is not None and (
            current.identity != identity or current.retired or current.owner.done()
        ):
            current.retire()
            self._retiring.add(current)
            current = None
        if current is None:
            current = _Connection(identity, authorization)
            self._current[url] = current
        self._retiring = {item for item in self._retiring if not item.owner.done()}
        return current

    async def _perform(
        self,
        url: str,
        timeout: float,
        streamable: bool,
        proxy: str | None,
        authorization: McpConnectionAuth,
        tool_name: str | None,
        arguments: dict[str, object] | None,
    ) -> list[Tool] | CallToolResult:
        connection = self._connection(url, timeout, streamable, proxy, authorization)
        operation = asyncio.create_task(
            self._borrow(connection, timeout, authorization, tool_name, arguments)
        )
        connection.operations.add(operation)
        try:
            return await operation
        finally:
            connection.operations.discard(operation)
            if connection.retired and not connection.operations:
                connection.stop.set()

    async def _borrow(
        self,
        connection: _Connection,
        timeout: float,
        authorization: McpConnectionAuth,
        tool_name: str | None,
        arguments: dict[str, object] | None,
    ) -> list[Tool] | CallToolResult:
        state = _DispatchState(
            authorization, connection.identity.streamable, asyncio.current_task()
        )
        token = _request_auth.set(state)
        try:
            async with asyncio.timeout(timeout):
                session = await asyncio.shield(connection.ready)
                async with connection.capacity:
                    if connection.retired:
                        raise RuntimeError("MCP connection was retired before dispatch")
                    if authorization.before_send is not None:
                        await authorization.before_send()
                    await connection.list_tools(session)
                    if tool_name is None:
                        return connection.tools
                    result = await session.call_tool(tool_name, arguments=arguments)
                    if state.failure is not None:
                        raise state.failure
                    return result
        except asyncio.CancelledError:
            if state.failure is not None:
                raise state.failure from None
            raise
        except Exception as exc:
            if state.failure is not None:
                raise state.failure from None
            if _connection_unusable(exc):
                connection.retire()
            raise
        finally:
            _request_auth.reset(token)

    async def list_tools(
        self,
        server_url: str,
        headers: dict[str, str],
        timeout: float,
        *,
        proxy_url: str | None,
        auth: httpx.Auth | None,
        auth_identity: Hashable | None,
        before_send: Callable[[], Awaitable[None]] | None,
    ) -> McpToolListResult:
        """Coalesce fresh listings, retaining existing read-only retry semantics."""
        authorization = McpConnectionAuth(
            dict(headers), auth, auth_identity, before_send
        )
        current = self._current.get(server_url)
        streamable = current.identity.streamable if current is not None else True
        for attempt in range(4):
            try:
                try:
                    tools = await self._perform(
                        server_url,
                        timeout,
                        streamable,
                        proxy_url,
                        authorization,
                        None,
                        None,
                    )
                except Exception as exc:
                    if not streamable or not _is_http_405(exc):
                        raise
                    streamable = False
                    tools = await self._perform(
                        server_url, timeout, False, proxy_url, authorization, None, None
                    )
                if not isinstance(tools, list):
                    raise TypeError("MCP discovery returned a tool result")
                return McpToolListResult(tools, streamable)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                delay = discovery_rate_limit_delay(exc)
                if delay is None or attempt == 3:
                    raise
                if delay == 0:
                    delay = float(2**attempt)
                if not math.isfinite(delay) or not 0 <= delay <= 60:
                    raise
                await asyncio.sleep(delay)
        raise AssertionError("unreachable")

    async def call_tool(
        self,
        server_url: str,
        headers: dict[str, str],
        timeout: float,
        tool_name: str,
        arguments: dict[str, object],
        *,
        use_streamable_http: bool,
        proxy_url: str | None,
        auth: httpx.Auth | None,
        auth_identity: Hashable | None,
        before_send: Callable[[], Awaitable[None]] | None,
    ) -> CallToolResult:
        """Dispatch once. Reconnect for later operations, never replay this one."""
        result = await self._perform(
            server_url,
            timeout,
            use_streamable_http,
            proxy_url,
            McpConnectionAuth(dict(headers), auth, auth_identity, before_send),
            tool_name,
            arguments,
        )
        if isinstance(result, list):
            raise TypeError("MCP call returned a tool listing")
        return result

    async def close(self) -> None:
        """Stop new admission and close every owned connection exactly once."""
        self._closed = True
        connections = set(self._current.values()) | self._retiring
        self._current = {}
        self._retiring = set()
        if connections:
            cleanup = asyncio.gather(
                *(connection.close() for connection in connections)
            )
            await asyncio.shield(cleanup)
