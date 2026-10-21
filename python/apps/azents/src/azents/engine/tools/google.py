"""Local typed Workspace tools admitted against current canonical Google grants."""

import dataclasses
from collections.abc import Callable
from typing import ClassVar

from azents.core.google_oauth import GoogleOAuthError
from azents.core.session_resource_authority import (
    SessionExecutionOwner,
    SessionResourceAuthority,
    accepts_execution_owner,
)
from azents.core.tools import (
    GoogleToolkitConfig,
    ResolveContext,
    TestConnectionResult,
    Toolkit,
    ToolkitProvider,
    ToolkitState,
    ToolkitStatus,
    TurnContext,
)
from azents.engine.run.types import FunctionToolError
from azents.engine.tools.google_files import GoogleFileBridge
from azents.engine.tools.google_operations import GOOGLE_TOOLS, GoogleOperationCall
from azents.services.google_oauth.runtime import GoogleRuntimeService
from azents.services.google_workspace.execution import GoogleWorkspaceExecution
from azents.services.google_workspace.transport import (
    GoogleSdkLimits,
    GoogleWorkspaceSdk,
)

GoogleFileBridgeFactory = Callable[[SessionResourceAuthority], GoogleFileBridge]


class GoogleToolkit(Toolkit[GoogleToolkitConfig]):
    """Rebuild local tools each turn; retained handlers still re-admit every call."""

    def __init__(
        self,
        *,
        runtime: GoogleRuntimeService,
        sdk: GoogleWorkspaceSdk,
        context: ResolveContext,
        timeout: float,
        files: GoogleFileBridgeFactory | None,
    ) -> None:
        self.runtime = (
            runtime.for_personal(context.effect_admission.target)
            if context.effect_admission is not None
            else runtime
        )
        self.sdk = sdk
        self.context = context
        self.timeout = timeout
        self.files = files
        self.owner: SessionExecutionOwner | None = None

    def bind_execution_owner(self, owner: SessionExecutionOwner) -> None:
        if accepts_execution_owner(
            self.owner, owner, session_id=self.context.session_id
        ):
            self.owner = owner

    def bind_execution_authority(self, authority: SessionResourceAuthority) -> None:
        if (
            authority.agent_id != self.context.agent_id
            or authority.workspace_id != self.context.workspace_id
        ):
            raise ValueError("Google execution authority does not match the Toolkit.")
        self.bind_execution_owner(authority.execution_owner)

    async def update_context(self, context: TurnContext) -> ToolkitState:
        authority = context.resource_authority
        if authority is None or self.files is None:
            raise FunctionToolError(
                "Google tools require canonical Session file authority."
            )
        self.bind_execution_authority(authority)
        assert self.owner is not None
        try:
            await self.assert_effect_current()
            allowed = await self.runtime.direct_operations(
                self.owner, self.context.toolkit_id
            )
        except GoogleOAuthError:
            allowed = frozenset()
        bridge = self.files(authority)
        if bridge.authority != authority:
            raise ValueError("Google files must use exact current Session authority.")
        call = GoogleOperationCall(
            execution=GoogleWorkspaceExecution(self.runtime, self.sdk),
            files=bridge,
            owner=self.owner,
            toolkit_id=self.context.toolkit_id,
            limits=GoogleSdkLimits(
                maximum_response_bytes=bridge.maximum_bytes,
                maximum_total_received_bytes=bridge.maximum_bytes * 2,
                maximum_upload_bytes=bridge.maximum_bytes,
                timeout=self.timeout,
            ),
            proxy_url=self.context.mcp_proxy_url,
        )
        return ToolkitState(
            status=ToolkitStatus.ENABLED,
            tools=[
                item.bind(call) for item in GOOGLE_TOOLS if item.operation in allowed
            ],
        )


@dataclasses.dataclass(frozen=True)
class GoogleToolkitProvider(ToolkitProvider[GoogleToolkitConfig]):
    """Operator-owned Google registration with server-only credential execution."""

    runtime: GoogleRuntimeService
    sdk: GoogleWorkspaceSdk
    files: GoogleFileBridgeFactory | None
    slug = "google"
    name = "Google"
    description = "Gmail, Calendar and Drive through typed official Google SDK tools."
    system_prompt = ""
    config_model: ClassVar = GoogleToolkitConfig

    async def validate_credentials(
        self, credentials: dict[str, object] | None
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
        self, config: GoogleToolkitConfig, context: ResolveContext
    ) -> Toolkit[GoogleToolkitConfig]:
        return GoogleToolkit(
            runtime=self.runtime,
            sdk=self.sdk,
            context=context,
            timeout=config.timeout,
            files=self.files,
        )
