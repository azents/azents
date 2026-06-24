"""AWS Toolkit.

Service Toolkit that connects directly to AWS Managed MCP Server via HTTPS + SigV4.
Accesses 15,000+ AWS APIs through a single endpoint,
and supports direct Access Key use or STS AssumeRole.
"""

import asyncio
import logging
from collections.abc import Generator
from datetime import timedelta
from textwrap import dedent
from typing import ClassVar

import httpx
from azcommon.datetime import tznow
from botocore.auth import SigV4Auth as BotoSigV4Auth
from botocore.awsrequest import AWSRequest
from botocore.credentials import Credentials
from pydantic import BaseModel, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.mcp_transport import (
    extract_network_error,
)
from azents.core.mcp_transport import (
    list_tools as mcp_list_tools,
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
from azents.engine.run.types import FunctionTool
from azents.engine.tools.mcp_base import (
    McpArtifactSink,
    build_mcp_artifact_sink,
    wrap_mcp_tool,
)
from azents.services.artifact import ArtifactService

logger = logging.getLogger(__name__)

_AWS_MCP_ENDPOINT = "https://aws-mcp.us-east-1.api.aws/mcp"
_AWS_MCP_SERVICE = "aws-mcp"
_AWS_MCP_REGION = "us-east-1"
# Refresh margin for AssumeRole temporary credentials
_ASSUME_REFRESH_MARGIN = timedelta(minutes=5)
# AssumeRole session validity period
_ASSUME_DURATION_SECONDS = 3600


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
    """Add AWS SigV4 signature to httpx request."""

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
        """Call STS AssumeRole to obtain temporary credentials."""
        assert self._role_arn is not None  # noqa: S101

        sts_auth = AwsSigV4Auth(self._base_credentials, self._region, "sts")

        params: dict[str, str] = {
            "Action": "AssumeRole",
            "Version": "2011-06-15",
            "RoleArn": self._role_arn,
            "RoleSessionName": "azents-aws-toolkit",
            "DurationSeconds": str(_ASSUME_DURATION_SECONDS),
        }
        if self._external_id:
            params["ExternalId"] = self._external_id

        async with httpx.AsyncClient(auth=sts_auth, timeout=30.0) as client:
            resp = await client.get(
                f"https://sts.{self._region}.amazonaws.com/",
                params=params,
            )
            resp.raise_for_status()

        # Parse XML response with simple tag extraction
        text = resp.text
        access_key = _extract_xml_tag(text, "AccessKeyId")
        secret_key = _extract_xml_tag(text, "SecretAccessKey")
        session_token = _extract_xml_tag(text, "SessionToken")

        self._assumed = Credentials(access_key, secret_key, session_token)
        self._assumed_expiry = tznow().timestamp() + _ASSUME_DURATION_SECONDS
        return self._assumed


def _extract_xml_tag(xml: str, tag: str) -> str:
    """Extract simple tag value from XML."""
    start = xml.find(f"<{tag}>")
    end = xml.find(f"</{tag}>")
    if start == -1 or end == -1:
        msg = f"Tag <{tag}> not found in STS response"
        raise ValueError(msg)
    return xml[start + len(tag) + 2 : end]


# ---------------------------------------------------------------------------
# AwsToolkit
# ---------------------------------------------------------------------------


class AwsToolkit(Toolkit[AwsToolkitConfig]):
    """Provide AWS Managed MCP Server tools.

    **Dynamic status transition (state machine)**:
    - ``__aenter__``: Start background MCP connection
    - ``update_context()``: Return immediately based on connection status
      (loading / ready / error)
    - ``__aexit__``: Cancel background task

    :param credential_provider: AWS credential provider
    :param default_region: Default AWS region
    :param timeout: MCP tool call timeout
    :param proxy_url: MCP egress proxy URL
    """

    def __init__(
        self,
        *,
        config: AwsToolkitConfig,
        credential_provider: AwsCredentialProvider,
        default_region: str,
        timeout: float,
        proxy_url: str | None = None,
        artifact_service: ArtifactService | None = None,
    ) -> None:
        self._config = config
        self._credential_provider = credential_provider
        self._default_region = default_region
        self._timeout = timeout
        self._proxy_url = proxy_url
        self._artifact_service = artifact_service
        # Background connection status
        self._bg_task: asyncio.Task[None] | None = None
        self._bg_tools: list[FunctionTool] | None = None
        self._bg_error: str | None = None
        self._artifact_sink: McpArtifactSink | None = None
        self._entered = False

    def _current_artifact_sink(self) -> McpArtifactSink | None:
        """Return Artifact sink for current run."""
        return self._artifact_sink

    def _refresh_artifact_sink(self, context: TurnContext) -> None:
        """Update Artifact sink for current run from TurnContext."""
        self._artifact_sink = build_mcp_artifact_sink(
            context,
            self._artifact_service,
        )

    async def __aenter__(self) -> AwsToolkit:
        """Start AWS MCP server connection in background."""
        self._entered = True
        self._bg_task = asyncio.create_task(self._connect_and_list_tools())
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

    async def _connect_and_list_tools(self) -> None:
        """Connect to AWS MCP server in background and collect tools."""
        try:
            credentials = await self._credential_provider.get_credentials()
        except Exception:
            logger.exception("Failed to get AWS credentials")
            self._bg_error = "AWS credential acquisition failed"
            return

        sigv4_auth = AwsSigV4Auth(credentials, _AWS_MCP_REGION, _AWS_MCP_SERVICE)

        try:
            mcp_tools, use_streamable_http = await mcp_list_tools(
                _AWS_MCP_ENDPOINT,
                {},
                self._timeout,
                proxy_url=self._proxy_url,
                auth=sigv4_auth,
            )
        except Exception as exc:
            logger.exception("Failed to connect to AWS MCP server")
            self._bg_error = f"AWS MCP server connection failed: {exc}"
            return

        tools: list[FunctionTool] = []
        for mcp_tool in mcp_tools:
            tools.append(
                wrap_mcp_tool(
                    mcp_tool=mcp_tool,
                    server_url=_AWS_MCP_ENDPOINT,
                    headers={},
                    timeout=self._timeout,
                    use_streamable_http=use_streamable_http,
                    proxy_url=self._proxy_url,
                    auth=sigv4_auth,
                    artifact_sink_getter=self._current_artifact_sink,
                )
            )
        self._bg_tools = tools

    async def update_context(self, context: TurnContext) -> ToolkitState:
        """Return immediately based on AWS MCP Server connection status.

        After __aenter__: return based on background connection status.
        When called without __aenter__: existing synchronous mode
        (backward compatibility).
        """
        self._refresh_artifact_sink(context)
        if not self._entered:
            return await self._sync_update_context()

        # Return immediately based on background status (keep previous tools)
        cached = self._bg_tools or []

        if self._bg_task is not None and not self._bg_task.done():
            return ToolkitState(
                status=ToolkitStatus.ENABLED,
                tools=cached,
                prompt="Loading tools..." if not cached else "",
            )

        if self._bg_error is not None:
            return ToolkitState(
                status=ToolkitStatus.ENABLED,
                tools=cached,
                prompt=self._bg_error if not cached else "",
            )

        if self._bg_tools is not None:
            prompt = self._build_prompt()
            return ToolkitState(
                status=ToolkitStatus.ENABLED,
                tools=self._bg_tools,
                prompt=prompt,
            )

        return ToolkitState(
            status=ToolkitStatus.ENABLED,
            tools=[],
            prompt="Waiting for connection...",
        )

    async def _sync_update_context(self) -> ToolkitState:
        """Collect tools from AWS MCP Server synchronously (backward compatibility)."""
        credentials = await self._credential_provider.get_credentials()
        sigv4_auth = AwsSigV4Auth(credentials, _AWS_MCP_REGION, _AWS_MCP_SERVICE)

        try:
            mcp_tools, use_streamable_http = await mcp_list_tools(
                _AWS_MCP_ENDPOINT,
                {},
                self._timeout,
                proxy_url=self._proxy_url,
                auth=sigv4_auth,
            )
        except Exception:
            logger.exception("Failed to connect to AWS MCP server")
            return ToolkitState(
                status=ToolkitStatus.ENABLED,
                tools=[],
                prompt="AWS MCP server connection failed.",
            )

        tools: list[FunctionTool] = []
        for mcp_tool in mcp_tools:
            tools.append(
                wrap_mcp_tool(
                    mcp_tool=mcp_tool,
                    server_url=_AWS_MCP_ENDPOINT,
                    headers={},
                    timeout=self._timeout,
                    use_streamable_http=use_streamable_http,
                    proxy_url=self._proxy_url,
                    auth=sigv4_auth,
                    artifact_sink_getter=self._current_artifact_sink,
                )
            )

        prompt = self._build_prompt()
        return ToolkitState(status=ToolkitStatus.ENABLED, tools=tools, prompt=prompt)

    def _build_prompt(self) -> str:
        """Create AWS prompt."""
        role_info = (
            f"\nAssumed Role: {self._config.role_arn}" if self._config.role_arn else ""
        )
        return f"AWS Region: {self._default_region}{role_info}"


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

    def __init__(self, artifact_service: ArtifactService | None = None) -> None:
        """Initialize AwsToolkitProvider."""
        self._artifact_service = artifact_service

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
            artifact_service=self._artifact_service,
        )

    async def validate_credentials(
        self,
        session: AsyncSession,
        user_id: str,
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
