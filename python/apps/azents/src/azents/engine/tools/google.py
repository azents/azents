"""Bounded Google provider: current grant admission and screened MCP composition."""

import asyncio
import dataclasses
import logging
from typing import ClassVar

from mcp.types import (
    CallToolResult,
    EmbeddedResource,
    ResourceLink,
    TextContent,
    TextResourceContents,
)
from mcp.types import Tool as McpTool
from pydantic import TypeAdapter, ValidationError

from azents.core.engine_tool_state import McpToolSnapshotItem
from azents.core.google_oauth import GoogleOAuthError
from azents.core.google_policy import (
    GOOGLE_MCP_ENDPOINTS,
    GoogleService,
    selected_services,
)
from azents.core.google_screening import GoogleContentBlocked, inspect_google_content
from azents.core.mcp_transport import call_tool, list_tools
from azents.core.personal_toolkit_runtime import ToolkitEffectAdmission
from azents.core.session_resource_authority import SessionExecutionOwner
from azents.core.tools import (
    GoogleToolkitConfig,
    McpToolkitConfig,
    ResolveContext,
    TestConnectionResult,
    Toolkit,
    ToolkitProvider,
    ToolkitState,
    ToolkitStatus,
    TurnContext,
)
from azents.engine.run.types import FunctionTool, FunctionToolError, FunctionToolResult
from azents.engine.tools.background_discovery import (
    DISCOVERY_ERRORS,
    require_expected_discovery_failure,
)
from azents.engine.tools.mcp import McpToolkit
from azents.engine.tools.mcp_base import (
    McpAuthenticationFailureObserver,
    McpRequestAuthorization,
    _build_mcp_tool_snapshot,
    _extract_tool_result,
    _is_http_401,
    wrap_mcp_tool,
)
from azents.repos.engine_tool_repositories import EngineMcpSnapshotFactory
from azents.repos.session_execution import CanonicalExecutionOwnerGenerationStaleError
from azents.services.artifact import ArtifactService
from azents.services.google_oauth.runtime import GoogleRuntimeService
from azents.utils.logging import sanitized_exception_info

_ARGUMENTS = TypeAdapter(dict[str, object])
logger = logging.getLogger(__name__)


def _screen(value: object) -> None:
    """Handle inspector inability at this boundary without ever approving content."""
    try:
        inspect_google_content(value)
    except GoogleContentBlocked:
        raise
    except (ValueError, TypeError, RuntimeError, MemoryError) as error:
        logger.error(
            "Google content inspection failed",
            extra={"error_type": type(error).__name__},
            exc_info=sanitized_exception_info(
                error, message="Google content inspection failed."
            ),
        )
        raise GoogleContentBlocked("inspection_failed") from None


def screen_google_result(result: CallToolResult) -> None:
    """Inspect complete payload before extraction; reject uninspectable binary."""
    for content in result.content:
        if isinstance(content, EmbeddedResource):
            if not isinstance(content.resource, TextResourceContents):
                raise GoogleContentBlocked("unsupported_binary")
        elif not isinstance(content, TextContent | ResourceLink):
            raise GoogleContentBlocked("unsupported_binary")
    _screen(result.model_dump(mode="json"))


class GoogleServiceMcpToolkit(McpToolkit):
    """One fixed endpoint, with exact raw-name permission rechecks on every call."""

    def __init__(
        self,
        *,
        service: GoogleService,
        toolkit_id: str,
        runtime: GoogleRuntimeService,
        context: ResolveContext,
        timeout: float,
        snapshot_factory: EngineMcpSnapshotFactory,
        artifact_service: ArtifactService,
    ) -> None:
        self.service = service
        self.toolkit_id = toolkit_id
        self.runtime = (
            runtime.for_personal(context.effect_admission.target)
            if context.effect_admission is not None
            else runtime
        )
        super().__init__(
            config=McpToolkitConfig(
                server_url=GOOGLE_MCP_ENDPOINTS[service],
                auth_type="bearer",
                timeout=timeout,
            ),
            secret=None,
            on_auth_failure=None,
            proxy_url=context.mcp_proxy_url,
            artifact_service=artifact_service,
            snapshot_factory=snapshot_factory,
            agent_id=context.agent_id,
            session_id=context.session_id,
            state_name=f"google:{toolkit_id}:{service.value}",
        )

    def _owner(self) -> SessionExecutionOwner:
        if self._execution_owner is None:
            raise FunctionToolError("Google execution owner has not been bound.")
        return self._execution_owner

    async def _request_authorization(self) -> McpRequestAuthorization:
        try:
            receipt = await self.runtime.discovery_authorization(
                self._owner(),
                self.toolkit_id,
                self.service,
            )
        except GoogleOAuthError as error:
            raise FunctionToolError(str(error)) from None

        async def failed() -> None:
            await self.runtime.authentication_failed(
                self._owner(),
                self.toolkit_id,
                receipt,
            )

        return McpRequestAuthorization(
            headers={"Authorization": f"Bearer {receipt.access_token}"},
            on_authentication_failure=failed,
            auth=McpAuthenticationFailureObserver(),
        )

    async def _connect_and_list_tools(self) -> None:
        """Screen full remote contracts before any schema persistence or exposure."""
        authorization: McpRequestAuthorization | None = None
        try:
            authorization = await self._admitted_request_authorization()
            discovery = await list_tools(
                self._config.server_url,
                authorization.headers,
                self._config.timeout,
                proxy_url=self._proxy_url,
                auth=authorization.auth,
            )
            allowed = await self.runtime.permitted_tools(
                self._owner(),
                self.toolkit_id,
                self.service,
            )
            tools = []
            for tool in discovery.tools:
                if tool.name not in allowed:
                    continue
                if tool.input_schema.get("type") != "object":
                    continue
                try:
                    _screen(tool.model_dump(mode="json"))
                except GoogleContentBlocked:
                    continue
                tools.append(tool)
            await self._save_tool_snapshot(
                _build_mcp_tool_snapshot(
                    server_url=self._config.server_url,
                    mcp_tools=tools,
                    use_streamable_http=discovery.use_streamable_http,
                )
            )
        except asyncio.CancelledError:
            raise
        except CanonicalExecutionOwnerGenerationStaleError:
            self._owner_stale = True
        except GoogleOAuthError, FunctionToolError:
            self._bg_error = "Google discovery authorization is unavailable."
        except (*DISCOVERY_ERRORS, ExceptionGroup) as error:
            require_expected_discovery_failure(error)
            if (
                authorization is not None
                and isinstance(authorization.auth, McpAuthenticationFailureObserver)
                and (_is_http_401(error) or authorization.auth.authentication_failed)
                and authorization.on_authentication_failure is not None
            ):
                await authorization.on_authentication_failure()
            self._bg_error = "Google remote discovery is unavailable."

    def _tool(self, item: McpToolSnapshotItem) -> FunctionTool:
        # Common conversion owns the supported MCP-to-function schema shape.
        wrapped = wrap_mcp_tool(
            McpTool(
                name=item.raw_name,
                description=item.description,
                input_schema=item.input_schema,
            ),
            self._config.server_url,
            {},
            self._config.timeout,
            use_streamable_http=item.use_streamable_http,
            on_auth_failure=None,
            authorization_provider=None,
            proxy_url=self._proxy_url,
            artifact_sink_getter=None,
        )

        async def execute(arguments_json: str) -> str | FunctionToolResult:
            try:
                receipt = await self.runtime.authorize_tool(
                    self._owner(),
                    self.toolkit_id,
                    self.service,
                    item.raw_name,
                )
            except GoogleOAuthError as error:
                raise FunctionToolError(str(error)) from None
            if len(arguments_json) > 262144:
                raise FunctionToolError(
                    "Google arguments exceed the complete-inspection limit. "
                    "No Google operation was sent."
                )
            try:
                arguments = _ARGUMENTS.validate_json(arguments_json)
            except ValidationError:
                raise FunctionToolError(
                    "Invalid Google tool arguments. No Google operation was sent."
                ) from None
            try:
                _screen(arguments)
            except GoogleContentBlocked:
                raise FunctionToolError(
                    "Google tool arguments were blocked by content screening. "
                    "No Google operation was sent."
                ) from None
            try:
                observer = McpAuthenticationFailureObserver()
                result = await call_tool(
                    self._config.server_url,
                    {"Authorization": f"Bearer {receipt.access_token}"},
                    self._config.timeout,
                    item.raw_name,
                    arguments,
                    use_streamable_http=item.use_streamable_http,
                    proxy_url=self._proxy_url,
                    auth=observer,
                )
            except asyncio.CancelledError:
                raise
            except (*DISCOVERY_ERRORS, ExceptionGroup) as error:
                require_expected_discovery_failure(error)
                if _is_http_401(error) or observer.authentication_failed:
                    await self.runtime.authentication_failed(
                        self._owner(),
                        self.toolkit_id,
                        receipt,
                    )
                raise FunctionToolError(
                    "Google tool execution could not be confirmed. "
                    "The operation may have completed; "
                    "it was not automatically replayed."
                ) from None
            try:
                screen_google_result(result)
            except GoogleContentBlocked:
                raise FunctionToolError(
                    "Google response was blocked by content screening. "
                    "The operation may have completed; "
                    "no response artifact was published."
                ) from None
            return await _extract_tool_result(
                result,
                tool_name=f"{self.service.value}_{item.raw_name}",
                artifact_sink=self._current_artifact_sink(),
            )

        return dataclasses.replace(
            wrapped,
            handler=execute,
            spec=wrapped.spec.model_copy(
                update={"name": f"{self.service.value}_{item.raw_name}"}
            ),
        )

    async def update_context(self, context: TurnContext) -> ToolkitState:
        self._refresh_artifact_sink(context)
        try:
            allowed = await self.runtime.permitted_tools(
                self._owner(),
                self.toolkit_id,
                self.service,
            )
        except GoogleOAuthError:
            allowed = frozenset()
        snapshot = await self._load_tool_snapshot()
        tools: list[FunctionTool] = []
        if snapshot is not None:
            for item in snapshot.tools:
                if (
                    item.raw_name not in allowed
                    or item.server_url != self._config.server_url
                    or item.input_schema.get("type") != "object"
                ):
                    continue
                try:
                    _screen(item.model_dump(mode="json"))
                except GoogleContentBlocked:
                    continue
                tools.append(self._tool(item))
        if self._entered:
            self._ensure_refresh_task()
        return ToolkitState(status=ToolkitStatus.ENABLED, tools=tools)


class GoogleToolkit(Toolkit[GoogleToolkitConfig]):
    """Compose the three named services without generalizing generic MCP."""

    def __init__(self, services: list[GoogleServiceMcpToolkit]) -> None:
        self.services = services

    def bind_effect_admission(self, admission: ToolkitEffectAdmission | None) -> None:
        super().bind_effect_admission(admission)
        for service in self.services:
            service.bind_effect_admission(admission)

    def bind_execution_owner(self, owner: SessionExecutionOwner) -> None:
        for service in self.services:
            service.bind_execution_owner(owner)

    async def __aenter__(self) -> "GoogleToolkit":
        for service in self.services:
            await service.__aenter__()
        return self

    async def __aexit__(self, *exc: object) -> None:
        for service in reversed(self.services):
            await service.__aexit__(*exc)

    async def update_context(self, context: TurnContext) -> ToolkitState:
        tools: list[FunctionTool] = []
        for service in self.services:
            tools.extend((await service.update_context(context)).tools)
        return ToolkitState(
            status=ToolkitStatus.ENABLED,
            tools=sorted(tools, key=lambda tool: tool.spec.name),
        )


class GoogleToolkitProvider(ToolkitProvider[GoogleToolkitConfig]):
    """Registration is operator-owned; credentials are available only after review."""

    slug = "google"
    name = "Google"
    description = "Google Calendar, Drive and Gmail through official remote MCP."
    system_prompt = ""
    config_model: ClassVar = GoogleToolkitConfig

    def __init__(
        self,
        runtime: GoogleRuntimeService,
        snapshots: EngineMcpSnapshotFactory,
        artifacts: ArtifactService,
    ) -> None:
        self.runtime = runtime
        self.snapshots = snapshots
        self.artifacts = artifacts

    async def validate_credentials(
        self,
        credentials: dict[str, object] | None,
    ) -> str | None:
        if credentials is not None:
            return (
                "Google application secrets are operator-owned. "
                "Authorize and review the account through Google connection setup."
            )
        return None

    async def test_connection(
        self,
        config: GoogleToolkitConfig,
        credentials_json: str | None,
        *,
        proxy_url: str | None = None,
    ) -> TestConnectionResult:
        return TestConnectionResult(
            success=False,
            message="Authorize and review the Google account before use.",
            discovered_auth_url=None,
            discovered_token_url=None,
            supports_dcr=False,
        )

    async def resolve(
        self,
        config: GoogleToolkitConfig,
        context: ResolveContext,
    ) -> Toolkit[GoogleToolkitConfig]:
        return GoogleToolkit(
            [
                GoogleServiceMcpToolkit(
                    service=service,
                    toolkit_id=context.toolkit_id,
                    runtime=self.runtime,
                    context=context,
                    timeout=config.timeout,
                    snapshot_factory=self.snapshots,
                    artifact_service=self.artifacts,
                )
                for service in selected_services(tuple(config.tasks))
            ]
        )
