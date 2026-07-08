"""Tool definition registry.

ToolkitProvider ABC is the base class for each toolkit type, such as Shell or MCP.
Generic[ConfigT] lets subclasses use concrete config types without casts.
"""

import dataclasses
import enum
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from typing import Annotated, ClassVar, Generic, Literal, TypeVar

from pydantic import BaseModel, BeforeValidator, Field
from sqlalchemy.ext.asyncio import AsyncSession

from azents.engine.hooks.types import RuntimeHooks
from azents.engine.run.emit import PublishedEvent
from azents.engine.run.types import CheckStop, FunctionTool

# ---------------------------------------------------------------------------
# Toolkit State Machine types
# ---------------------------------------------------------------------------

# Engine event publish callback type
PublishEventFn = Callable[[PublishedEvent], Awaitable[None]]


class ToolkitStatus(enum.StrEnum):
    """Toolkit active state.

    ENABLED: engine passes tools and prompt to the LLM.
    DISABLED: engine fully excludes this toolkit, so the LLM does not know it exists.
    """

    ENABLED = "enabled"
    DISABLED = "disabled"


@dataclasses.dataclass(frozen=True)
class ToolkitState:
    """Tool state returned by toolkit each turn.

    Prompt content is intentionally excluded from this state machine. Static
    prompt content is collected through ``Toolkit.get_static_prompt()`` once at
    run start, and dynamic prompt content is collected through
    ``Toolkit.get_dynamic_prompt()`` on the dynamic prompt path.
    """

    status: ToolkitStatus
    tools: list[FunctionTool]


@dataclasses.dataclass(frozen=True)
class TurnContext:
    """Context passed to toolkit each turn. Only information that changes per turn.

    :param user_id: User ID; None for unlinked user or system context
    :param workspace_id: Workspace ID
    :param model: LLM model string
    :param session_id: Agent session ID
    :param run_id: Unique ID for message processing unit
    :param run_index: Run index increasing within the session
    :param publish_event: Engine event publish callback
    :param check_stop: Callback that checks whether execution should stop
    """

    user_id: str | None
    workspace_id: str
    model: str
    run_id: str
    publish_event: PublishEventFn
    session_id: str = ""
    run_index: int = 1
    check_stop: CheckStop | None = None


@dataclasses.dataclass(frozen=True)
class ToolCallHookContext:
    """Call context passed to Toolkit tool-call hook."""

    tool_name: str
    toolkit_slug: str
    args_json: str
    session_id: str
    agent_id: str
    workspace_id: str
    run_id: str


@dataclasses.dataclass(frozen=True)
class ToolCallHookOutcome:
    """Execution result summary passed to Toolkit tool-call after hook."""

    output: object | None
    error: str | None


# ---------------------------------------------------------------------------
# Tool definition enum, hardcoded in code and not stored in DB
# ---------------------------------------------------------------------------


class ToolkitType(enum.StrEnum):
    """List of tools provided by the platform."""

    SHELL = "shell"
    MCP = "mcp"
    GITHUB = "github"
    NOTION = "notion"
    GCP = "gcp"
    AWS = "aws"
    SENTRY = "sentry"
    GOOGLE_ANALYTICS = "google_analytics"
    KUBERNETES = "kubernetes"
    ENVVAR = "envvar"


class SessionType(enum.StrEnum):
    """Session type.

    USER: session where a real user is conversing
    SYSTEM: session automatically run by the system
    """

    USER = "user"
    SYSTEM = "system"


class ToolkitExecutionMode(enum.StrEnum):
    """Execution mode used by Toolkit resolution filters."""

    ROOT = "root"
    SUBAGENT = "subagent"


# ---------------------------------------------------------------------------
# Runtime context
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class ToolkitContext:
    """Runtime context injected when creating Tools.

    Contains only fields shared by all toolkits.
    Toolkit-specific dependencies, e.g. RuntimeRunnerOperationClient, are injected
    through Definition class constructors.

    :param session_id: Conversation session ID
    :param workspace_id: Workspace ID
    :param agent_id: Agent ID
    :param user_id: User ID; None for unlinked user or system context
    :param run_id: Unique ID for message processing unit (for rate limiting)
    :param publish_event: Engine event publish callback
    :param session_type: Session type (USER: user conversation, SYSTEM:
        automatic execution)
    """

    session_id: str
    workspace_id: str
    agent_id: str
    user_id: str | None
    run_id: str
    publish_event: PublishEventFn
    session_type: SessionType
    interface_type: str | None
    interface_channel_id: str | None


@dataclasses.dataclass(frozen=True)
class ResolveContext:
    """Per-request context passed to resolve().

    :param toolkit_id: Toolkit config ID
    :param toolkit_name: Human-readable Toolkit name
    :param credentials_json: Decrypted credential JSON; None means no authentication
    :param agent_id: Agent ID owning the current AgentSession
    :param session_id: Current AgentSession ID
    :param user_id: User ID; None for system context
    :param session: DB session
    :param web_url: Frontend URL for building OAuth redirect_uri
    :param oauth_secret_key: OAuth HMAC signing key
    :param workspace_id: Workspace ID
    :param workspace_handle: Workspace handle for building settings page URL
    :param mcp_proxy_url: MCP egress proxy URL; direct connection when None
    """

    toolkit_id: str
    toolkit_name: str
    credentials_json: str | None
    agent_id: str
    session_id: str
    user_id: str | None
    session: AsyncSession
    web_url: str
    oauth_secret_key: str
    workspace_id: str
    workspace_handle: str
    mcp_proxy_url: str | None = None


# ---------------------------------------------------------------------------
# Toolkit Provider ABC
# ---------------------------------------------------------------------------

ConfigT = TypeVar("ConfigT", bound=BaseModel)


class Toolkit(ABC, Generic[ConfigT]):
    """Executable Toolkit instance returned from resolve().

    ``update_context()`` is only for tool/status state. Prompt content is not part
    of that state machine: static prompt content is fetched explicitly at run
    start, and dynamic prompt content is fetched through a separate opt-in path.
    """

    display_name: str = ""
    """Name displayed in toolkit prompt. Injected by Provider.resolve()."""

    async def update_context(self, context: TurnContext) -> ToolkitState:
        """Receive current turn context and immediately return tool state.

        Do not return or mutate prompt content from this state-machine path.

        :param context: Context passed each turn
        :return: Current tool state
        """
        raise NotImplementedError

    async def get_static_prompt(self, context: TurnContext) -> str:
        """Return static prompt content to freeze for the current run.

        This is called separately from ``update_context()`` so implementation
        mistakes in the tool state machine cannot implicitly modify prompt
        content. Most toolkits return a stable configuration prompt or an empty
        string.
        """
        del context
        return ""

    async def get_dynamic_prompt(self, context: TurnContext) -> str:
        """Return dynamic prompt content for explicitly dynamic prompt sources.

        This path is reserved for prompt content that intentionally changes
        between turns, such as memory summaries. Most toolkits should return an
        empty string.
        """
        del context
        return ""

    async def __aenter__(self) -> Toolkit[ConfigT]:
        """Start background work when session starts, optional."""
        return self

    async def __aexit__(self, *exc: object) -> None:
        """Clean up background work when session ends, optional."""

    async def expose_env(self) -> dict[str, str]:
        """Return environment variable mapping for runtime shell execution.

        Return fresh values on every call. Static toolkits return values captured at
        resolve time, while dynamic toolkits such as short-lived tokens perform
        expiry check and renewal here.

        Default implementation returns empty dict. Only toolkits exposing credentials
        to runtime override this.

        ``make_tool`` handlers can only receive JSON arguments and cannot access
        ``TurnContext``. Therefore this method has no arguments, and toolkit
        instances must already have captured required context such as user_id
        from ``ResolveContext`` during ``resolve()``.

        :return: Environment variable mapping to inject (key -> value). Keys
            that do not match POSIX variable name rules
            (``^[A-Z_][A-Z0-9_]*$``) may be rejected downstream.
        """
        return {}

    def hooks(self) -> RuntimeHooks:
        """Return supported runtime hook callback mapping.

        Default implementation acts as a no-op provider without registered hooks.

        :return: lifecycle hook mapping
        """
        return {}

    async def on_before_tool_call(self, context: ToolCallHookContext) -> None:
        """Observation hook called before tool handler execution.

        Default implementation does nothing. Hooks do not change tool input or block
        execution; they are used only to update Toolkit internal state.

        :param context: Tool call context
        """

    async def on_after_tool_call(
        self,
        context: ToolCallHookContext,
        outcome: ToolCallHookOutcome,
    ) -> None:
        """Observation hook called after tool handler execution.

        Default implementation does nothing. Hooks do not change tool output and are
        used only to update Toolkit internal state.

        :param context: Tool call context
        :param outcome: Tool execution result summary
        """


@dataclasses.dataclass(frozen=True)
class TestConnectionResult:
    """test_connection() return value."""

    success: bool
    message: str
    discovered_auth_url: str | None
    discovered_token_url: str | None
    supports_dcr: bool | None


class ToolkitProvider(ABC, Generic[ConfigT]):
    """Toolkit Provider base class.

    Each toolkit type, such as Shell or MCP, inherits this class.
    Registered as singleton in DI registry,
    and creates executable Toolkit through resolve().

    Generic[ConfigT] allows subclass resolve and validate_config to use concrete
    config types directly without casts.
    """

    slug: ClassVar[str]
    """ToolkitType enum value, e.g. "shell"."""

    name: ClassVar[str]
    """Human-readable name."""

    description: ClassVar[str]
    """Short description."""

    system_prompt: ClassVar[str]
    """Definition-level LLM prompt."""

    config_model: ClassVar[type[BaseModel]]
    """Pydantic model used for Config validation and automatic schema generation."""

    @abstractmethod
    async def resolve(
        self,
        config: ConfigT,
        context: ResolveContext,
    ) -> Toolkit[ConfigT]:
        """Resolve per-config credentials and return executable Toolkit.

        :param config: Validated toolkit settings
        :param context: Resolve context such as credentials and user_id
        :return: Executable Toolkit instance
        """
        ...

    def to_mcp_config(self, config: ConfigT) -> McpToolkitConfig:
        """Convert config to McpToolkitConfig.

        MCP-based toolkits validate config as-is, while dedicated toolkits such as
        Sentry/Notion override by injecting fixed values. Used when OAuth
        endpoints reference server_url, auth_type, and similar fields.

        :param config: Validated toolkit settings
        :return: McpToolkitConfig
        """
        return McpToolkitConfig.model_validate(
            config.model_dump() if isinstance(config, BaseModel) else config
        )

    async def validate_credentials(
        self,
        session: AsyncSession,
        user_id: str,
        credentials: dict[str, object] | None,
    ) -> str | None:
        """Validate credential validity.

        Subclasses override this to implement toolkit-specific validation logic.
        Default implementation passes without validation.

        :param session: DB session
        :param user_id: User ID
        :param credentials: Toolkit credentials (dict or None)
        :return: Error message on failure, or None on success
        """
        return None

    async def test_connection(
        self,
        config: ConfigT,
        credentials_json: str | None,
        *,
        proxy_url: str | None = None,
    ) -> TestConnectionResult:
        """Test Toolkit connection.

        Subclasses override this to implement toolkit-specific connection test logic.
        Default implementation raises NotImplementedError.

        :param config: Validated toolkit settings
        :param credentials_json: Decrypted credential JSON; None means no authentication
        :param proxy_url: Egress proxy URL; direct connection when None
        :return: Connection test result
        """
        raise NotImplementedError

    @classmethod
    def config_schema(cls) -> dict[str, object]:
        """Automatically generate JSON Schema from config_model.

        :return: JSON Schema dict
        """
        return cls.config_model.model_json_schema()

    @classmethod
    def validate_config(cls, data: dict[str, object]) -> ConfigT:
        """Validate raw dict as ConfigT.

        config_model and ConfigT consistency is guaranteed by subclass definition.

        :param data: Config dict to validate
        :return: Validated ConfigT instance
        """
        return cls.config_model.model_validate(data)  # pyright: ignore[reportReturnType] — Type-system limitation: TypeVar cannot be used in ClassVar; subclasses guarantee consistency with config_model = ConcreteConfig and Generic[ConcreteConfig]  # noqa: E501


# ---------------------------------------------------------------------------
# Config models
# ---------------------------------------------------------------------------


class ShellToolkitConfig(BaseModel):
    """Shell tool settings model.

    Bundles common Builtin/Runtime toolkit settings in one place.
    ``resolve_agent_tools()`` receives runtime_domain_config and builds this config,
    so runtime tools receive domain configuration explicitly.
    """

    agent_data_root: str = Field(
        default="/mnt/agent-data",
        description="Agent data root path. "
        "User folder is located at {agent_data_root}/users/{user_id}.",
    )
    allowed_domains: list[str] = Field(
        default_factory=list,
        description=(
            "Allowed domain list. Empty means allow all; only denied_domains applies."
        ),
    )
    denied_domains: list[str] = Field(
        default_factory=list,
        description="Denied domain list. Always blocked regardless of allowed_domains.",
    )
    memory_enabled: bool = Field(
        default=True,
        description="Whether memory system is enabled",
    )


def _empty_to_none(v: object) -> object:
    """Convert empty string to None."""
    if v == "":
        return None
    return v


EmptyToNone = Annotated[str | None, BeforeValidator(_empty_to_none)]
"""Optional[str] type that normalizes empty string ("") to None."""


class McpToolkitConfig(BaseModel):
    """MCP Toolkit settings model."""

    server_url: str = Field(description="MCP server URL (SSE/HTTP)")
    auth_type: str = Field(
        description="Authentication type (none, header, bearer, oauth2)"
    )
    timeout: float = Field(default=30.0, description="MCP request timeout in seconds")
    header_name: EmptyToNone = Field(
        default=None, description="Authentication header name; required for header auth"
    )
    token_url: EmptyToNone = Field(default=None, description="OAuth2 token endpoint")
    auth_url: EmptyToNone = Field(
        default=None, description="OAuth2 authorization endpoint"
    )
    scopes: list[str] = Field(default_factory=list, description="OAuth2 scopes")
    discovery_url: EmptyToNone = Field(
        default=None, description="OAuth2 AS discovery URL (override)"
    )


class GitHubToolkitConfig(BaseModel):
    """GitHub Toolkit settings model.

    Standalone BaseModel containing only GitHub-specific fields.
    server_url/auth_type are set to fixed values inside Provider.
    Same delegation pattern as Sentry/Notion.
    """

    github_auth_type: Literal["pat", "github_app", "github_app_platform"] = Field(
        description="GitHub authentication method"
    )
    toolsets: list[str] = Field(
        default=["repos", "issues", "pull_requests", "users"],
        description="GitHub MCP tool groups to enable",
    )
    timeout: float = Field(default=30.0, description="MCP request timeout in seconds")
    inject_runtime_environment: bool = Field(
        default=False,
        description=(
            "When ON, inject GH_TOKEN / GITHUB_TOKEN variables into "
            "runtime child process. "
            "When OFF (default), use only as MCP secret as before. "
            "Assumes no isolation; enable only when accepting leakage risk."
        ),
    )


class NotionToolkitConfig(BaseModel):
    """Notion Toolkit settings model."""

    timeout: float = Field(default=30.0, description="MCP request timeout in seconds")


class SentryToolkitConfig(BaseModel):
    """Sentry Toolkit settings model."""

    timeout: float = Field(default=30.0, description="MCP request timeout in seconds")
    enabled_skills: list[str] = Field(
        default=["inspect", "seer"],
        description="Skill group list to enable",
    )


class GcpService(enum.StrEnum):
    """Supported GCP MCP services."""

    LOGGING = "logging"
    MONITORING = "monitoring"
    GKE = "gke"
    COMPUTE = "compute"
    CLOUD_RUN = "cloud_run"
    CLOUD_SQL = "cloud_sql"
    BIGQUERY = "bigquery"


_GCP_DEFAULT_SERVICES: list[GcpService] = [GcpService.LOGGING, GcpService.MONITORING]


class GcpToolkitConfig(BaseModel):
    """GCP Toolkit settings model."""

    project_id: str = Field(
        description="GCP project ID",
        min_length=6,
        max_length=30,
        pattern=r"^[a-z][a-z0-9-]{4,28}[a-z0-9]$",
    )
    services: list[GcpService] = Field(
        default_factory=lambda: list(_GCP_DEFAULT_SERVICES),
        description="Enabled GCP services",
        min_length=1,
    )
    writable_services: list[GcpService] = Field(
        default_factory=list,
        description="Services with write access enabled (default: all read-only)",
    )
    timeout: float = Field(
        default=30.0,
        description="MCP tool call timeout (seconds)",
        ge=1.0,
        le=300.0,
    )


class AwsToolkitConfig(BaseModel):
    """AWS Toolkit settings model."""

    region: str = Field(
        default="us-east-1",
        description="Default AWS region",
        pattern=r"^[a-z]{2}-[a-z]+-\d$",
    )
    role_arn: str | None = Field(
        default=None,
        description="IAM Role ARN to assume",
    )
    external_id: str | None = Field(
        default=None,
        description="ExternalId for AssumeRole",
    )
    timeout: float = Field(
        default=30.0,
        description="MCP tool call timeout (seconds)",
        ge=1.0,
        le=300.0,
    )


class GoogleAnalyticsToolkitConfig(BaseModel):
    """Google Analytics Toolkit settings model."""

    default_property_id: str | None = Field(
        default=None,
        description="Default GA4 property ID (e.g. 123456789)",
    )
    timeout: float = Field(
        default=30.0,
        description="MCP tool call timeout (seconds)",
        ge=1.0,
        le=300.0,
    )


class ClusterConfig(BaseModel):
    """Individual cluster settings (non-secret)."""

    name: str = Field(description="Cluster name referenced by the agent")
    auth_type: Literal["kubeconfig", "token", "eks", "gke"] = Field(
        description="Authentication method",
    )
    default_namespace: str = Field(
        default="default",
        description="Default value when namespace is unspecified",
    )
    context: str | None = Field(
        default=None,
        description="Context name used for kubeconfig authentication",
    )
    api_server: str | None = Field(
        default=None,
        description="API server URL for token authentication",
    )
    cluster_name: str | None = Field(
        default=None,
        description="EKS/GKE cluster name",
    )
    region: str | None = Field(
        default=None,
        description="EKS region or GKE location",
    )
    project_id: str | None = Field(
        default=None,
        description="GKE project ID",
    )


class KubernetesToolkitConfig(BaseModel):
    """Kubernetes Toolkit settings model."""

    clusters: list[ClusterConfig] = Field(
        description="Cluster list to connect",
    )
    read_only: bool = Field(
        default=True,
        description="Enable only read tools when True",
    )
    allowed_namespaces: list[str] | None = Field(
        default=None,
        description="Accessible namespace list; None means all",
    )
    denied_kinds: list[str] = Field(
        default=["Secret"],
        description="Denied resource kind list",
    )
    timeout: float = Field(
        default=30.0,
        description="API request timeout in seconds",
    )
