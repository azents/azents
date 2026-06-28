"""Common base for MCP-based Toolkits.

Provides connection, auth header building, and tool wrapping shared by every
Toolkit using MCP protocol (Raw MCP, GitHub, etc.).
Supports background MCP connection + dynamic status transition.
"""

import asyncio
import base64
import binascii
import dataclasses
import datetime
import hashlib
import json
import logging
import mimetypes
import time
from abc import ABC
from collections.abc import Awaitable, Callable
from typing import Generic, TypeVar
from urllib.parse import urlparse

import httpx
from azcommon.result import Success
from mcp.shared.exceptions import McpError
from mcp.types import (
    AudioContent,
    BlobResourceContents,
    CallToolResult,
    EmbeddedResource,
    ImageContent,
    ResourceLink,
    TextContent,
    TextResourceContents,
)
from mcp.types import Tool as McpBaseTool
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.mcp_transport import call_tool as mcp_call_tool
from azents.core.mcp_transport import list_tools as mcp_list_tools
from azents.core.tools import (
    McpToolkitConfig,
    SessionType,
    Toolkit,
    ToolkitState,
    ToolkitStatus,
    TurnContext,
)
from azents.engine.run.types import (
    FunctionTool,
    FunctionToolError,
    FunctionToolResult,
    FunctionToolSpec,
)
from azents.engine.tooling.toolkit_state import (
    ToolkitStateHandle,
    ToolkitStateIdentity,
    ToolkitStateModel,
    ToolkitStateStore,
)
from azents.rdb.session import SessionManager
from azents.services.artifact import ArtifactService

logger = logging.getLogger(__name__)

McpConfigT = TypeVar("McpConfigT", bound=McpToolkitConfig)
MCP_TOOL_SNAPSHOT_SCHEMA_VERSION = 1
MCP_TOOL_SNAPSHOT_STATE_NAME = "tool_snapshot"


@dataclasses.dataclass(frozen=True)
class McpArtifactSink:
    """Run context for storing MCP binary output in ArtifactStore."""

    artifact_service: ArtifactService
    session_id: str
    user_id: str
    run_id: str
    run_index: int


ArtifactSinkGetter = Callable[[], McpArtifactSink | None]


class McpToolSnapshotItem(BaseModel):
    """Serializable MCP tool snapshot item."""

    raw_name: str
    model_name: str
    description: str
    input_schema: dict[str, object]
    server_url: str
    use_streamable_http: bool = False


class McpToolSnapshotState(ToolkitStateModel):
    """Latest successful MCP tool snapshot."""

    schema_version: int = MCP_TOOL_SNAPSHOT_SCHEMA_VERSION
    loaded_at: str | None = None
    server_url: str = ""
    tool_hash: str = ""
    tools: list[McpToolSnapshotItem] = Field(default_factory=list)


def build_mcp_artifact_sink(
    context: TurnContext,
    artifact_service: ArtifactService | None,
) -> McpArtifactSink | None:
    """Configure MCP artifact storage context from TurnContext."""
    if artifact_service is None or context.user_id is None or not context.session_id:
        return None
    return McpArtifactSink(
        artifact_service=artifact_service,
        session_id=context.session_id,
        user_id=context.user_id,
        run_id=context.run_id,
        run_index=context.run_index,
    )


def _build_mcp_tool_snapshot(
    *,
    server_url: str,
    mcp_tools: list[McpBaseTool],
    use_streamable_http: bool,
) -> McpToolSnapshotState:
    """Build a deterministic serializable MCP tool snapshot."""
    items = [
        McpToolSnapshotItem(
            raw_name=tool.name,
            model_name=tool.name,
            description=tool.description or "",
            input_schema=tool.inputSchema,
            server_url=server_url,
            use_streamable_http=use_streamable_http,
        )
        for tool in sorted(mcp_tools, key=lambda item: item.name)
    ]
    payload = [item.model_dump(mode="json") for item in items]
    tool_hash = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return McpToolSnapshotState(
        loaded_at=datetime.datetime.now(datetime.UTC).isoformat(),
        server_url=server_url,
        tool_hash=tool_hash,
        tools=items,
    )


# ---------------------------------------------------------------------------
# MCP Tool wrapper
# ---------------------------------------------------------------------------


def _build_auth_headers(config: McpToolkitConfig, secret: str | None) -> dict[str, str]:
    """Create HTTP headers from authentication settings.

    :param config: MCP toolkit settings
    :param secret: Decrypted authentication secret such as API key or bearer token
    :return: Authentication header dict
    """
    if secret is None or config.auth_type == "none":
        return {}

    if config.auth_type == "header":
        header_name = config.header_name or "Authorization"
        return {header_name: secret}

    if config.auth_type in (
        "bearer",
        "oauth2_client_credentials",
        "oauth2_delegated",
        "oauth2",
    ):
        return {"Authorization": f"Bearer {secret}"}

    return {}


async def _extract_tool_result(
    result: CallToolResult,
    *,
    tool_name: str,
    artifact_sink: McpArtifactSink | None,
) -> str | FunctionToolResult:
    """Convert CallToolResult to text or artifact output part.

    :param result: MCP CallToolResult
    :param tool_name: Called tool name
    :param artifact_sink: ArtifactStore storage context
    :return: tool handler return value
    """
    output: list[dict[str, object]] = []
    text_parts: list[str] = []
    for index, item in enumerate(result.content):
        match item:
            case TextContent():
                text_parts.append(item.text)
            case EmbeddedResource():
                if isinstance(item.resource, TextResourceContents):
                    artifact_part = await _create_text_artifact_output_part(
                        sink=artifact_sink,
                        tool_name=tool_name,
                        part_index=index,
                        filename=_filename_from_uri(str(item.resource.uri)),
                        media_type=item.resource.mimeType or "text/plain",
                        text=item.resource.text,
                    )
                    if artifact_part is None:
                        text_parts.append(f"[text resource: {item.resource.uri}]")
                    else:
                        output.append(artifact_part)
                elif isinstance(item.resource, BlobResourceContents):
                    artifact_part = await _create_artifact_output_part(
                        sink=artifact_sink,
                        tool_name=tool_name,
                        part_index=index,
                        filename=_filename_from_uri(str(item.resource.uri)),
                        media_type=item.resource.mimeType or "application/octet-stream",
                        base64_data=item.resource.blob,
                    )
                    if artifact_part is None:
                        text_parts.append(f"[binary resource: {item.resource.uri}]")
                    else:
                        output.append(artifact_part)
                else:
                    text_parts.append("[unsupported resource content]")
            case ImageContent():
                artifact_part = await _create_artifact_output_part(
                    sink=artifact_sink,
                    tool_name=tool_name,
                    part_index=index,
                    filename=_default_filename(tool_name, index, item.mimeType),
                    media_type=item.mimeType,
                    base64_data=item.data,
                )
                if artifact_part is None:
                    text_parts.append(
                        f"[unsupported content type: image ({item.mimeType})]"
                    )
                else:
                    output.append(artifact_part)
            case AudioContent():
                artifact_part = await _create_artifact_output_part(
                    sink=artifact_sink,
                    tool_name=tool_name,
                    part_index=index,
                    filename=_default_filename(tool_name, index, item.mimeType),
                    media_type=item.mimeType,
                    base64_data=item.data,
                )
                if artifact_part is None:
                    text_parts.append(
                        f"[unsupported content type: audio ({item.mimeType})]"
                    )
                else:
                    output.append(artifact_part)
            case ResourceLink():
                text_parts.append(f"[resource link: {item.name}] {item.uri}")

    text = "\n".join(text_parts)
    if result.isError:
        text = f"[MCP Error] {text}"

    if not output:
        return text
    if text:
        output.insert(0, {"type": "text", "text": text})
    return FunctionToolResult(output=output)


async def _create_artifact_output_part(
    *,
    sink: McpArtifactSink | None,
    tool_name: str,
    part_index: int,
    filename: str,
    media_type: str,
    base64_data: str,
) -> dict[str, object] | None:
    """Store MCP base64 content in ArtifactStore and return output part."""
    if sink is None:
        return None
    try:
        body = base64.b64decode(base64_data, validate=True)
    except binascii.Error, ValueError:
        logger.warning(
            "MCP tool returned invalid base64 content",
            extra={"tool_name": tool_name, "part_index": part_index},
        )
        return None
    return await _create_artifact_output_part_from_body(
        sink=sink,
        tool_name=tool_name,
        part_index=part_index,
        filename=filename,
        media_type=media_type,
        body=body,
    )


async def _create_text_artifact_output_part(
    *,
    sink: McpArtifactSink | None,
    tool_name: str,
    part_index: int,
    filename: str,
    media_type: str,
    text: str,
) -> dict[str, object] | None:
    """Store MCP text resource in ArtifactStore and return output part."""
    if sink is None:
        return None
    return await _create_artifact_output_part_from_body(
        sink=sink,
        tool_name=tool_name,
        part_index=part_index,
        filename=filename,
        media_type=media_type,
        body=text.encode("utf-8"),
    )


async def _create_artifact_output_part_from_body(
    *,
    sink: McpArtifactSink,
    tool_name: str,
    part_index: int,
    filename: str,
    media_type: str,
    body: bytes,
) -> dict[str, object] | None:
    """Store MCP content bytes in ArtifactStore and return output part."""
    created = await sink.artifact_service.create(
        session_id=sink.session_id,
        user_id=sink.user_id,
        created_run_id=sink.run_id,
        created_run_index=sink.run_index,
        filename=filename,
        media_type=media_type,
        body=body,
        source_tool_name=tool_name,
        source_part_index=part_index,
    )
    if not isinstance(created, Success):
        return None
    artifact = created.value
    return {
        "type": "artifact",
        "artifact_id": artifact.id,
        "uri": artifact.uri,
        "name": artifact.name,
        "media_type": artifact.media_type,
        "size": artifact.size_bytes,
        "status": artifact.status.value,
        "expires_at": artifact.expires_at.isoformat(),
    }


def _filename_from_uri(uri: str) -> str:
    """Extract display file name from URI path."""
    path = urlparse(uri).path
    name = path.rsplit("/", maxsplit=1)[-1]
    return name or "resource"


def _default_filename(tool_name: str, part_index: int, media_type: str) -> str:
    """Create default file name for MCP inline content."""
    extension = mimetypes.guess_extension(media_type) or ""
    return f"{tool_name}-{part_index}{extension}"


def _is_http_status(exc: BaseException, codes: set[int]) -> bool:
    """Check whether exception is one of specified HTTP status codes.

    Recursively check even when wrapped in ExceptionGroup.
    """
    if isinstance(exc, BaseExceptionGroup):
        return any(_is_http_status(sub, codes) for sub in exc.exceptions)
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in codes
    return False


def _is_http_401(exc: Exception) -> bool:
    """Check whether exception is HTTP 401 Unauthorized."""
    return _is_http_status(exc, {401})


def _is_http_auth_error(exc: Exception) -> bool:
    """Check whether exception is HTTP auth/permission error (401, 403)."""
    return _is_http_status(exc, {401, 403})


def _find_http_status_error(exc: BaseException) -> httpx.HTTPStatusError | None:
    """Find HTTP status error in exception tree."""
    if isinstance(exc, BaseExceptionGroup):
        for sub in exc.exceptions:
            found = _find_http_status_error(sub)
            if found is not None:
                return found
        return None
    if isinstance(exc, httpx.HTTPStatusError):
        return exc
    return None


def _find_mcp_error(exc: BaseException) -> McpError | None:
    """Find MCP protocol error in exception tree."""
    if isinstance(exc, BaseExceptionGroup):
        for sub in exc.exceptions:
            found = _find_mcp_error(sub)
            if found is not None:
                return found
        return None
    if isinstance(exc, McpError):
        return exc
    return None


def _mcp_transport_tool_error_message(exc: BaseException) -> str | None:
    """Convert MCP transport error to user-visible tool error message."""
    status_error = _find_http_status_error(exc)
    if status_error is not None:
        response = status_error.response
        request = status_error.request
        reason = response.reason_phrase or "HTTP error"
        return (
            f"MCP server returned HTTP {response.status_code} {reason} "
            f"for {request.url}."
        )

    mcp_error = _find_mcp_error(exc)
    if mcp_error is not None:
        return f"MCP tool call failed: {mcp_error}"

    return None


def wrap_mcp_tool(
    mcp_tool: McpBaseTool,
    server_url: str,
    headers: dict[str, str],
    timeout: float,
    *,
    use_streamable_http: bool = False,
    on_auth_failure: Callable[[], Awaitable[str | None]] | None = None,
    proxy_url: str | None = None,
    auth: httpx.Auth | None = None,
    artifact_sink_getter: ArtifactSinkGetter | None = None,
) -> FunctionTool:
    """Wrap MCP tool as azents Tool.

    Create new connection for each call.
    When on_auth_failure is set, reissue token on 401 response and retry once.

    :param mcp_tool: Tool spec fetched from MCP server
    :param server_url: MCP server URL
    :param headers: Authentication headers
    :param timeout: Request timeout in seconds
    :param use_streamable_http: Use Streamable HTTP when True, SSE when False
    :param on_auth_failure: Token reissue callback called on 401; no retry when None
    :param proxy_url: egress proxy URL; direct connection when None
    :param auth: httpx Auth handler for per-request signing such as SigV4
    :return: azents Tool instance
    """
    spec = FunctionToolSpec(
        name=mcp_tool.name,
        description=mcp_tool.description or "",
        input_schema=mcp_tool.inputSchema,
    )

    async def handler(arguments_json: str) -> str | FunctionToolResult:
        """Call MCP tool."""
        try:
            args: dict[str, object] = (
                json.loads(arguments_json) if arguments_json else {}
            )
        except json.JSONDecodeError as exc:
            raise FunctionToolError(f"Invalid JSON in tool arguments: {exc}") from None
        try:
            result = await mcp_call_tool(
                server_url,
                headers,
                timeout,
                mcp_tool.name,
                args,
                use_streamable_http=use_streamable_http,
                proxy_url=proxy_url,
                auth=auth,
            )
        except Exception as exc:
            if on_auth_failure is not None and _is_http_401(exc):
                new_token = await on_auth_failure()
                if new_token is not None:
                    new_headers = {**headers, "Authorization": f"Bearer {new_token}"}
                    try:
                        result = await mcp_call_tool(
                            server_url,
                            new_headers,
                            timeout,
                            mcp_tool.name,
                            args,
                            use_streamable_http=use_streamable_http,
                            proxy_url=proxy_url,
                            auth=auth,
                        )
                    except Exception as retry_exc:
                        message = _mcp_transport_tool_error_message(retry_exc)
                        if message is not None:
                            raise FunctionToolError(message) from None
                        raise
                    return await _extract_tool_result(
                        result,
                        tool_name=mcp_tool.name,
                        artifact_sink=(
                            artifact_sink_getter()
                            if artifact_sink_getter is not None
                            else None
                        ),
                    )
            message = _mcp_transport_tool_error_message(exc)
            if message is not None:
                raise FunctionToolError(message) from None
            raise
        return await _extract_tool_result(
            result,
            tool_name=mcp_tool.name,
            artifact_sink=(
                artifact_sink_getter() if artifact_sink_getter is not None else None
            ),
        )

    return FunctionTool(spec=spec, handler=handler)


# ---------------------------------------------------------------------------
# McpBasedToolkitProvider ABC
# ---------------------------------------------------------------------------


class McpBasedToolkit(Toolkit[McpConfigT], ABC, Generic[McpConfigT]):
    """Common base for Toolkit based on MCP protocol.

    Provides shared logic for MCP-based Toolkits such as MCP server connection,
    tool list lookup, and Tool wrapping.
    Subclass sets _config and _secret in __init__.

    **Dynamic status transition (state machine)**:
    - ``__aenter__``: Start MCP connection as background task
    - ``update_context()``: Return immediately by connection status
    - ``__aexit__``: Cancel background task
    """

    _config: McpConfigT
    _secret: str | None
    _on_auth_failure: Callable[[], Awaitable[str | None]] | None
    _proxy_url: str | None
    _session_type: SessionType
    _artifact_service: ArtifactService | None
    _session_manager: SessionManager[AsyncSession] | None
    _agent_id: str
    _session_id: str
    _state_namespace: str
    _state_name: str

    # Background connection status
    _bg_task: asyncio.Task[None] | None
    _bg_error: str | None
    _artifact_sink: McpArtifactSink | None
    _entered: bool

    def _init_bg_state(self) -> None:
        """Initialize background connection status.

        Must be called at end of subclass __init__.
        """
        self._bg_task = None
        self._bg_error = None
        self._artifact_sink = None
        self._entered = False
        self._agent_id = getattr(self, "_agent_id", "")
        self._session_id = getattr(self, "_session_id", "")
        self._session_manager = getattr(self, "_session_manager", None)
        self._state_namespace = getattr(self, "_state_namespace", "mcp")
        self._state_name = getattr(self, "_state_name", MCP_TOOL_SNAPSHOT_STATE_NAME)

    def set_agent_id(self, agent_id: str) -> None:
        """Inject agent ID for Toolkit State identity."""
        self._agent_id = agent_id

    def set_session_id(self, session_id: str) -> None:
        """Inject session ID for Toolkit State identity."""
        self._session_id = session_id

    def _current_artifact_sink(self) -> McpArtifactSink | None:
        """Return Artifact sink for current run."""
        return self._artifact_sink

    def _refresh_artifact_sink(self, context: TurnContext) -> None:
        """Update Artifact sink for current run from TurnContext."""
        self._artifact_sink = build_mcp_artifact_sink(
            context,
            self._artifact_service,
        )

    def get_credentials(
        self,
    ) -> tuple[str | None, None, str | None]:
        """Return bound credential.

        Interface for passing credential resolved by McpToolkitProvider when composing
        derived Toolkits such as Notion and Sentry.

        :return: (secret, None, proxy_url) tuple
        """
        return self._secret, None, self._proxy_url

    async def __aenter__(self) -> McpBasedToolkit[McpConfigT]:
        """Start MCP server connection in background."""
        self._entered = True

        self._ensure_refresh_task()
        return self

    async def __aexit__(self, *exc: object) -> None:
        """Cancel background connection task."""
        if self._bg_task is not None and not self._bg_task.done():
            self._bg_task.cancel()
            try:
                await self._bg_task
            except asyncio.CancelledError:
                pass
        self._bg_task = None

    def _ensure_refresh_task(self) -> None:
        """Start background refresh unless one is already running."""
        if self._bg_task is not None and not self._bg_task.done():
            return
        self._bg_task = asyncio.create_task(self._connect_and_list_tools())

    async def _connect_and_list_tools(self) -> None:
        """Connect to MCP server in background and collect tool list.

        Store a successful deterministic snapshot atomically in Toolkit State.
        """
        config = self._config
        headers = _build_auth_headers(config, self._secret)
        started = time.monotonic()

        try:
            mcp_tools, use_streamable_http = await mcp_list_tools(
                config.server_url, headers, config.timeout, proxy_url=self._proxy_url
            )
        except Exception as exc:
            if _is_http_auth_error(exc):
                logger.warning(
                    "MCP server auth failed",
                    extra={"server_url": config.server_url},
                )
                self._bg_error = f"MCP server auth failed: {config.server_url}"
            else:
                logger.exception(
                    "Failed to connect to MCP server",
                    extra={"server_url": config.server_url},
                )
                self._bg_error = f"MCP server connection failed: {exc}"
            return

        mcp_tools = sorted(mcp_tools, key=lambda item: item.name)
        snapshot = _build_mcp_tool_snapshot(
            server_url=config.server_url,
            mcp_tools=mcp_tools,
            use_streamable_http=use_streamable_http,
        )
        await self._save_tool_snapshot(snapshot)

        logger.info(
            "MCP tool snapshot refreshed",
            extra={
                "server_url": config.server_url,
                "tool_count": len(mcp_tools),
                "tool_names": [t.name for t in mcp_tools],
                "tool_hash": snapshot.tool_hash,
                "transport": "streamable_http" if use_streamable_http else "sse",
                "duration_seconds": round(time.monotonic() - started, 3),
            },
        )

        self._bg_error = (
            None  # Clear previous error when reconnection succeeds after retry
        )

    async def update_context(self, context: TurnContext) -> ToolkitState:
        """Return current toolkit state immediately based on internal state.


        :param context: Context passed each turn
        :return: Current state (tools + prompt)
        """
        self._refresh_artifact_sink(context)
        snapshot = await self._load_tool_snapshot()
        tools = self._tools_from_snapshot(snapshot) if snapshot is not None else []
        if self._entered:
            self._ensure_refresh_task()
        return ToolkitState(status=ToolkitStatus.ENABLED, tools=tools, prompt="")

    async def _load_tool_snapshot(self) -> McpToolSnapshotState | None:
        """Load the latest successful MCP tool snapshot from Toolkit State."""
        if self._session_manager is None:
            return None
        async with self._session_manager() as session:
            handle = self._tool_snapshot_handle(session)
            if handle is None:
                return None
            snapshot = await handle.load(default_factory=McpToolSnapshotState)
        if not snapshot.tools:
            return None
        if snapshot.server_url != self._config.server_url:
            return None
        return snapshot

    async def _save_tool_snapshot(self, snapshot: McpToolSnapshotState) -> None:
        """Atomically save a successful MCP tool snapshot."""
        if self._session_manager is None:
            return
        async with self._session_manager() as session:
            handle = self._tool_snapshot_handle(session)
            if handle is None:
                return
            await handle.load(default_factory=McpToolSnapshotState)
            await handle.save(snapshot)

    def _tool_snapshot_handle(
        self,
        session: AsyncSession,
    ) -> ToolkitStateHandle[McpToolSnapshotState] | None:
        """Create Toolkit State handle for MCP tool snapshot."""
        if not self._agent_id or not self._session_id:
            return None
        identity = ToolkitStateIdentity(
            agent_id=self._agent_id,
            session_id=self._session_id,
            toolkit_namespace=self._state_namespace,
            state_name=self._state_name,
        )
        return ToolkitStateStore(session=session).handle(
            identity,
            McpToolSnapshotState,
        )

    def _tools_from_snapshot(
        self, snapshot: McpToolSnapshotState
    ) -> list[FunctionTool]:
        """Rebuild FunctionTool wrappers from a stored snapshot."""
        config = self._config
        headers = _build_auth_headers(config, self._secret)
        tools: list[FunctionTool] = []
        for item in sorted(snapshot.tools, key=lambda tool: tool.model_name):
            mcp_tool = McpBaseTool(
                name=item.raw_name,
                description=item.description,
                inputSchema=item.input_schema,
            )
            tool = wrap_mcp_tool(
                mcp_tool,
                item.server_url,
                headers,
                config.timeout,
                use_streamable_http=item.use_streamable_http,
                on_auth_failure=self._on_auth_failure,
                proxy_url=self._proxy_url,
                artifact_sink_getter=self._current_artifact_sink,
            )
            if item.model_name != item.raw_name:
                tool = dataclasses.replace(
                    tool,
                    spec=dataclasses.replace(tool.spec, name=item.model_name),
                )
            tools.append(tool)
        return tools
