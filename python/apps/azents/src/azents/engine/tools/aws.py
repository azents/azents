"""AWS Toolkit.

Service Toolkit that connects directly to AWS Managed MCP Server via HTTPS + SigV4.
Accesses 15,000+ AWS APIs through a single endpoint,
and supports direct Access Key use or STS AssumeRole.
"""

import asyncio
import datetime
import hashlib
import json
import logging
from collections.abc import Callable, Generator
from datetime import timedelta
from textwrap import dedent
from typing import ClassVar

import boto3
import httpx2 as httpx
from azcommon.datetime import tznow
from botocore.auth import SigV4Auth as BotoSigV4Auth
from botocore.awsrequest import AWSRequest
from botocore.config import Config as BotoConfig
from botocore.credentials import Credentials
from botocore.exceptions import BotoCoreError, ClientError
from mcp.types import Tool as McpBaseTool
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from azents.core.engine_tool_state import (
    McpToolSnapshotItem,
    McpToolSnapshotState,
)
from azents.core.mcp_transport import (
    call_tool as mcp_call_tool,
)
from azents.core.mcp_transport import (
    extract_network_error,
)
from azents.core.mcp_transport import (
    list_tools as mcp_list_tools,
)
from azents.core.session_resource_authority import (
    SessionExecutionOwner,
    accepts_execution_owner,
)
from azents.core.tools import (
    AwsToolkitConfig,
    ResolveContext,
    TestConnectionResult,
    Toolkit,
    ToolkitProvider,
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
from azents.engine.tools.background_discovery import (
    DISCOVERY_ERRORS,
    observe_discovery_failure,
    require_expected_discovery_failure,
)
from azents.engine.tools.mcp_base import (
    McpArtifactSink,
    _extract_tool_result,  # reuse common MCP result extraction for AWS wrapper.
    build_mcp_artifact_sink,
)
from azents.repos.engine_tool_repositories import EngineMcpSnapshotFactory
from azents.repos.session_execution import (
    CanonicalExecutionOwnerGenerationStaleError,
)
from azents.services.artifact import ArtifactService
from azents.utils.logging import sanitized_exception_info

logger = logging.getLogger(__name__)

_AWS_MCP_ENDPOINT = "https://aws-mcp.us-east-1.api.aws/mcp"
_AWS_MCP_SERVICE = "aws-mcp"
_AWS_MCP_REGION = "us-east-1"
# Refresh margin for AssumeRole temporary credentials
_ASSUME_REFRESH_MARGIN = timedelta(minutes=5)
# AssumeRole session validity period
_ASSUME_DURATION_SECONDS = 3600
_AWS_TOOLKIT_STATE_NAMESPACE = "aws"


# ---------------------------------------------------------------------------
# Secrets
# ---------------------------------------------------------------------------


class AwsSecrets(BaseModel):
    """AWS IAM credentials (encrypted storage)."""

    access_key_id: str
    secret_access_key: str


# ---------------------------------------------------------------------------
# SigV4 Auth (httpx integration)
# ---------------------------------------------------------------------------


class AwsSigV4Auth(httpx.Auth):
    """Add AWS SigV4 signature to httpx2 request."""

    requires_request_body = True

    def __init__(
        self,
        credentials: Credentials,
        region: str,
        service: str,
    ) -> None:
        self._signer = BotoSigV4Auth(credentials, service, region)

    def auth_flow(
        self, request: httpx.Request
    ) -> Generator[httpx.Request, httpx.Response, None]:
        """Add SigV4 signature headers to request.

        If httpx default headers (accept, accept-encoding, connection, etc.)
        are included in signature, AWS rejects it with IncompleteSignatureException.
        Pass only Content-Type; botocore automatically adds host and x-amz-date.
        """
        # Pass only minimum headers to include in signature to botocore
        sign_headers: dict[str, str] = {}
        content_type = request.headers.get("content-type")
        if content_type is not None:
            sign_headers["Content-Type"] = content_type

        aws_request = AWSRequest(
            method=request.method,
            url=str(request.url),
            data=request.content,
            headers=sign_headers,
        )
        self._signer.add_auth(aws_request)
        for key, value in aws_request.headers.items():
            request.headers[key] = value
        yield request


# ---------------------------------------------------------------------------
# Credential Provider (direct use / AssumeRole)
# ---------------------------------------------------------------------------


class _AssumedRoleCredentials(BaseModel):
    """Validate recognized credential fields from an extensible SDK response."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    access_key_id: str = Field(alias="AccessKeyId", min_length=1)
    secret_access_key: str = Field(alias="SecretAccessKey", min_length=1)
    session_token: str = Field(alias="SessionToken", min_length=1)


class _AssumeRoleResponse(BaseModel):
    """Decode the credential receipt; other public STS metadata is diagnostic."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    credentials: _AssumedRoleCredentials = Field(alias="Credentials")


class AwsCredentialProvider:
    """AWS credential management. Direct Access Key use or AssumeRole.

    :param access_key_id: IAM Access Key ID
    :param secret_access_key: IAM Secret Access Key
    :param region: STS API call region
    :param role_arn: Role ARN to assume; direct use when None
    :param external_id: ExternalId for AssumeRole
    """

    def __init__(
        self,
        access_key_id: str,
        secret_access_key: str,
        region: str,
        role_arn: str | None = None,
        external_id: str | None = None,
    ) -> None:
        self._base_credentials = Credentials(access_key_id, secret_access_key)
        self._region = region
        self._role_arn = role_arn
        self._external_id = external_id
        self._assumed: Credentials | None = None
        self._assumed_expiry: float | None = None
        self._lock = asyncio.Lock()

    async def get_credentials(self) -> Credentials:
        """Return valid credentials."""
        if self._role_arn is None:
            return self._base_credentials

        if self._is_assumed_valid():
            assert self._assumed is not None  # noqa: S101
            return self._assumed

        async with self._lock:
            if self._is_assumed_valid():
                assert self._assumed is not None  # noqa: S101
                return self._assumed
            return await self._assume_role()

    def _is_assumed_valid(self) -> bool:
        """Check whether temporary credentials are valid."""
        if self._assumed is None or self._assumed_expiry is None:
            return False
        return (
            self._assumed_expiry
            > tznow().timestamp() + _ASSUME_REFRESH_MARGIN.total_seconds()
        )

    async def _assume_role(self) -> Credentials:
        """Obtain SDK-owned credentials without blocking the event loop."""
        assumed = await asyncio.to_thread(self._assume_role_sync)
        self._assumed = assumed
        self._assumed_expiry = tznow().timestamp() + _ASSUME_DURATION_SECONDS
        return assumed

    def _assume_role_sync(self) -> Credentials:
        """Own one public STS client for the existing bounded AssumeRole call."""
        assert self._role_arn is not None  # noqa: S101

        session = boto3.Session(
            aws_access_key_id=self._base_credentials.access_key,
            aws_secret_access_key=self._base_credentials.secret_key,
            aws_session_token=self._base_credentials.token,
            region_name=self._region,
        )
        client = session.client(
            "sts",
            region_name=self._region,
            endpoint_url=f"https://sts.{self._region}.amazonaws.com/",
            config=BotoConfig(
                connect_timeout=30,
                read_timeout=30,
                retries={"total_max_attempts": 1},
            ),
        )
        try:
            if self._external_id:
                response = client.assume_role(
                    RoleArn=self._role_arn,
                    RoleSessionName="azents-aws-toolkit",
                    DurationSeconds=_ASSUME_DURATION_SECONDS,
                    ExternalId=self._external_id,
                )
            else:
                response = client.assume_role(
                    RoleArn=self._role_arn,
                    RoleSessionName="azents-aws-toolkit",
                    DurationSeconds=_ASSUME_DURATION_SECONDS,
                )
            receipt = _AssumeRoleResponse.model_validate(response).credentials
            return Credentials(
                receipt.access_key_id,
                receipt.secret_access_key,
                receipt.session_token,
            )
        finally:
            client.close()


# ---------------------------------------------------------------------------
# AwsToolkit
# ---------------------------------------------------------------------------


class AwsToolkit(Toolkit[AwsToolkitConfig]):
    """Provide AWS Managed MCP Server tools from Toolkit State snapshots."""

    def __init__(
        self,
        *,
        config: AwsToolkitConfig,
        credential_provider: AwsCredentialProvider,
        default_region: str,
        timeout: float,
        proxy_url: str | None,
        artifact_service: ArtifactService | None,
        snapshot_factory: EngineMcpSnapshotFactory | None,
        agent_id: str,
        session_id: str,
        state_name: str,
    ) -> None:
        self._config = config
        self.credential_provider = credential_provider
        self._default_region = default_region
        self._timeout = timeout
        self._proxy_url = proxy_url
        self.artifact_service = artifact_service
        self._session_id = session_id
        self.snapshot_store = (
            snapshot_factory.create(
                agent_id=agent_id,
                session_id=session_id,
                toolkit_namespace=_AWS_TOOLKIT_STATE_NAMESPACE,
                state_name=state_name,
            )
            if snapshot_factory is not None
            else None
        )
        self._bg_task: asyncio.Task[None] | None = None
        self._artifact_sink: McpArtifactSink | None = None
        self._entered = False
        self._execution_owner: SessionExecutionOwner | None = None
        self._owner_stale = False

    def bind_execution_owner(self, owner: SessionExecutionOwner) -> None:
        """Bind snapshot state before starting background discovery."""
        if accepts_execution_owner(
            self._execution_owner,
            owner,
            session_id=self._session_id,
        ):
            if self.snapshot_store is not None:
                self.snapshot_store = self.snapshot_store.for_execution(owner)
            self._execution_owner = owner

    def _current_artifact_sink(self) -> McpArtifactSink | None:
        """Return Artifact sink for current run."""
        return self._artifact_sink

    def _refresh_artifact_sink(self, context: TurnContext) -> None:
        """Update Artifact sink for current run from TurnContext."""
        self._artifact_sink = build_mcp_artifact_sink(
            context,
            self.artifact_service,
        )

    async def __aenter__(self) -> AwsToolkit:
        """Start AWS MCP snapshot refresh in background."""
        self._entered = True
        self._ensure_refresh_task()
        return self

    async def __aexit__(self, *exc: object) -> None:
        """Cancel background refresh task."""
        if self._bg_task is not None and not self._bg_task.done():
            self._bg_task.cancel()
            try:
                await self._bg_task
            except asyncio.CancelledError:
                pass
        self._bg_task = None

    def _ensure_refresh_task(self) -> None:
        """Start background refresh unless one is already running."""
        if self._owner_stale:
            return
        if self._bg_task is not None and not self._bg_task.done():
            return
        self._bg_task = asyncio.create_task(self._refresh_tool_snapshot())
        self._bg_task.add_done_callback(
            observe_discovery_failure(logger, toolkit="aws")
        )

    async def _refresh_tool_snapshot(self) -> None:
        """Refresh the AWS MCP tool snapshot in the background."""
        try:
            credentials = await self.credential_provider.get_credentials()
            sigv4_auth = AwsSigV4Auth(credentials, _AWS_MCP_REGION, _AWS_MCP_SERVICE)
            mcp_tools, use_streamable_http = await mcp_list_tools(
                _AWS_MCP_ENDPOINT,
                {},
                self._timeout,
                proxy_url=self._proxy_url,
                auth=sigv4_auth,
            )
        except asyncio.CancelledError:
            raise
        except (*DISCOVERY_ERRORS, ExceptionGroup) as error:
            require_expected_discovery_failure(error)
            logger.exception(
                "Failed to refresh AWS MCP tool snapshot",
                exc_info=sanitized_exception_info(
                    error, message="AWS MCP discovery failed"
                ),
            )
            return

        snapshot = _build_aws_tool_snapshot(
            mcp_tools=mcp_tools,
            use_streamable_http=use_streamable_http,
        )
        try:
            await self._save_tool_snapshot(snapshot)
        except CanonicalExecutionOwnerGenerationStaleError:
            self._owner_stale = True
            return
        logger.info(
            "AWS MCP tool snapshot refreshed",
            extra={
                "tool_count": len(snapshot.tools),
                "tool_hash": snapshot.tool_hash,
            },
        )

    async def update_context(self, context: TurnContext) -> ToolkitState:
        """Return AWS tools from the latest successful Toolkit State snapshot."""
        self._refresh_artifact_sink(context)
        snapshot = await self._load_tool_snapshot()
        tools = self._tools_from_snapshot(snapshot) if snapshot is not None else []
        if self._entered:
            self._ensure_refresh_task()
        return ToolkitState(status=ToolkitStatus.ENABLED, tools=tools)

    async def get_static_prompt(self, context: TurnContext) -> str:
        """Return static AWS toolkit prompt for the current run."""
        del context
        return self._build_prompt()

    async def _load_tool_snapshot(self) -> McpToolSnapshotState | None:
        """Load the latest successful AWS MCP tool snapshot."""
        store = self.snapshot_store
        if store is None:
            return None
        snapshot = await store.load()
        if snapshot is None:
            return None
        if not snapshot.tools or snapshot.server_url != _AWS_MCP_ENDPOINT:
            return None
        return snapshot

    async def _save_tool_snapshot(self, snapshot: McpToolSnapshotState) -> None:
        """Atomically save a successful AWS MCP tool snapshot."""
        if self.snapshot_store is not None:
            await self.snapshot_store.replace(snapshot)

    def _tools_from_snapshot(
        self, snapshot: McpToolSnapshotState
    ) -> list[FunctionTool]:
        """Rebuild AWS tool wrappers from a stored snapshot."""
        return [
            _wrap_aws_snapshot_tool(
                item=item,
                credential_provider=self.credential_provider,
                timeout=self._timeout,
                proxy_url=self._proxy_url,
                artifact_sink_getter=self._current_artifact_sink,
            )
            for item in sorted(snapshot.tools, key=lambda tool: tool.model_name)
        ]

    def _build_prompt(self) -> str:
        """Create AWS prompt."""
        role_info = (
            f"\nAssumed Role: {self._config.role_arn}" if self._config.role_arn else ""
        )
        return f"AWS Region: {self._default_region}{role_info}"


def _build_aws_tool_snapshot(
    *,
    mcp_tools: list[McpBaseTool],
    use_streamable_http: bool,
) -> McpToolSnapshotState:
    """Build a deterministic AWS MCP tool snapshot."""
    items = [
        McpToolSnapshotItem(
            raw_name=tool.name,
            model_name=tool.name,
            description=tool.description or "",
            input_schema=tool.input_schema,
            server_url=_AWS_MCP_ENDPOINT,
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
        server_url=_AWS_MCP_ENDPOINT,
        tool_hash=tool_hash,
        tools=items,
    )


def _wrap_aws_snapshot_tool(
    *,
    item: McpToolSnapshotItem,
    credential_provider: AwsCredentialProvider,
    timeout: float,
    proxy_url: str | None,
    artifact_sink_getter: Callable[[], McpArtifactSink | None] | None,
) -> FunctionTool:
    """Wrap an AWS MCP snapshot item as a FunctionTool."""
    spec = FunctionToolSpec(
        name=item.model_name,
        description=item.description,
        input_schema=item.input_schema,
    )

    async def handler(arguments_json: str) -> str | FunctionToolResult:
        try:
            args: dict[str, object] = (
                json.loads(arguments_json) if arguments_json else {}
            )
        except json.JSONDecodeError as exc:
            raise FunctionToolError(f"Invalid JSON in tool arguments: {exc}") from None
        credentials = await credential_provider.get_credentials()
        auth = AwsSigV4Auth(credentials, _AWS_MCP_REGION, _AWS_MCP_SERVICE)
        result = await mcp_call_tool(
            item.server_url,
            {},
            timeout,
            item.raw_name,
            args,
            use_streamable_http=item.use_streamable_http,
            proxy_url=proxy_url,
            auth=auth,
        )
        return await _extract_tool_result(
            result,
            tool_name=item.raw_name,
            artifact_sink=(
                artifact_sink_getter() if artifact_sink_getter is not None else None
            ),
        )

    return FunctionTool(spec=spec, handler=handler)


def _aws_snapshot_state_name(*, toolkit_id: str, config: AwsToolkitConfig) -> str:
    """Return stable Toolkit State name for an AWS MCP tool snapshot."""
    payload = {
        "toolkit_id": toolkit_id,
        "region": config.region,
        "role_arn": config.role_arn,
        "external_id": config.external_id,
    }
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:16]
    return f"tool_snapshot:{digest}"


# ---------------------------------------------------------------------------
# AwsToolkitProvider
# ---------------------------------------------------------------------------


class AwsToolkitProvider(ToolkitProvider[AwsToolkitConfig]):
    """AWS Toolkit Provider.

    Direct HTTP + SigV4 connection to AWS Managed MCP Server.
    and supports direct Access Key use or STS AssumeRole.
    """

    slug: ClassVar[str] = "aws"
    name: ClassVar[str] = "AWS"
    description: ClassVar[str] = (
        "Amazon Web Services — CloudWatch, Cost Explorer, EC2, ECS, "
        "EKS, Lambda, S3, RDS, and 15,000+ more APIs"
    )
    system_prompt: ClassVar[str] = dedent("""\
        You have access to AWS tools via the AWS MCP Server.
        Use aws___search_documentation to find API usage.
        Use aws___suggest_aws_commands to get correct API syntax.
        Use aws___call_aws to execute AWS API calls.
        The default region is configured in the toolkit settings.""")
    config_model: ClassVar[type[BaseModel]] = AwsToolkitConfig

    def __init__(
        self,
        *,
        artifact_service: ArtifactService | None = None,
        snapshot_factory: EngineMcpSnapshotFactory | None = None,
    ) -> None:
        """Initialize AwsToolkitProvider."""
        self.artifact_service = artifact_service
        self.snapshot_factory = snapshot_factory

    async def resolve(
        self,
        config: AwsToolkitConfig,
        context: ResolveContext,
    ) -> Toolkit[AwsToolkitConfig]:
        """Decrypt credentials and configure MCP connection."""
        if context.credentials_json is None:
            msg = "AWS toolkit requires Access Key credentials"
            raise ValueError(msg)

        secrets = AwsSecrets.model_validate_json(context.credentials_json)

        credential_provider = AwsCredentialProvider(
            access_key_id=secrets.access_key_id,
            secret_access_key=secrets.secret_access_key,
            region=config.region,
            role_arn=config.role_arn,
            external_id=config.external_id,
        )

        return AwsToolkit(
            config=config,
            credential_provider=credential_provider,
            default_region=config.region,
            timeout=config.timeout,
            proxy_url=context.mcp_proxy_url,
            artifact_service=self.artifact_service,
            snapshot_factory=self.snapshot_factory,
            agent_id=context.agent_id,
            session_id=context.session_id,
            state_name=_aws_snapshot_state_name(
                toolkit_id=context.toolkit_id,
                config=config,
            ),
        )

    async def validate_credentials(
        self,
        credentials: dict[str, object] | None,
    ) -> str | None:
        """Validate Access Key structure."""
        if credentials is None:
            return "AWS Access Key is required"

        try:
            secrets = AwsSecrets.model_validate(credentials)
        except ValidationError as e:
            return f"Invalid credentials format: {e}"

        if not secrets.access_key_id.startswith("AKIA"):
            return (
                "Access Key ID should start with 'AKIA' "
                f"(got '{secrets.access_key_id[:4]}...')"
            )

        return None

    async def test_connection(
        self,
        config: AwsToolkitConfig,
        credentials_json: str | None,
        *,
        proxy_url: str | None = None,
    ) -> TestConnectionResult:
        """Test connection with SigV4 authentication + tools/list."""
        if not credentials_json:
            return TestConnectionResult(
                success=False,
                message="No credentials provided",
                discovered_auth_url=None,
                discovered_token_url=None,
                supports_dcr=None,
            )

        try:
            secrets = AwsSecrets.model_validate_json(credentials_json)
        except ValidationError as e:
            return TestConnectionResult(
                success=False,
                message=f"Invalid credentials: {e}",
                discovered_auth_url=None,
                discovered_token_url=None,
                supports_dcr=None,
            )

        credential_provider = AwsCredentialProvider(
            access_key_id=secrets.access_key_id,
            secret_access_key=secrets.secret_access_key,
            region=config.region,
            role_arn=config.role_arn,
            external_id=config.external_id,
        )

        try:
            credentials = await credential_provider.get_credentials()
        except (BotoCoreError, ClientError) as exc:
            return TestConnectionResult(
                success=False,
                message=f"Authentication failed: {type(exc).__name__}",
                discovered_auth_url=None,
                discovered_token_url=None,
                supports_dcr=None,
            )
        except Exception as exc:
            net_msg = extract_network_error(exc)
            if net_msg is None:
                raise
            return TestConnectionResult(
                success=False,
                message=f"Authentication failed: {net_msg}",
                discovered_auth_url=None,
                discovered_token_url=None,
                supports_dcr=None,
            )

        sigv4_auth = AwsSigV4Auth(credentials, _AWS_MCP_REGION, _AWS_MCP_SERVICE)

        try:
            tools, _ = await mcp_list_tools(
                _AWS_MCP_ENDPOINT,
                {},
                10.0,
                proxy_url=proxy_url,
                auth=sigv4_auth,
            )
        except Exception as exc:
            net_msg = extract_network_error(exc)
            if net_msg is None:
                raise
            return TestConnectionResult(
                success=False,
                message=net_msg,
                discovered_auth_url=None,
                discovered_token_url=None,
                supports_dcr=None,
            )

        role_info = f" (assumed {config.role_arn})" if config.role_arn else ""
        return TestConnectionResult(
            success=True,
            message=(
                f"Connected to AWS MCP Server{role_info}. {len(tools)} tools available."
            ),
            discovered_auth_url=None,
            discovered_token_url=None,
            supports_dcr=None,
        )
