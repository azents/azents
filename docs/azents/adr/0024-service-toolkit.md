---
title: "ADR-0024: Service Toolkit Design Discussion"
created: 2026-03-11
tags: [backend, engine]
updated: 2026-03-12
---

# ADR-0024: Service Toolkit Design Discussion

> 📌 **Related design document**: [service-toolkit-base.md](../design/service-toolkit-base.md)
>
> This document records design-stage discussion.

## Background

MCP Toolkit is general-purpose but complex to configure. Each service has different authentication method, MCP server URL, scope, and similar details, making it hard for users to understand and configure directly in a Raw MCP Toolkit.

**Service Toolkit** provides service-friendly configuration UI while reusing MCP Toolkit infrastructure internally.

```text
┌─────────────────────────────────────────────────┐
│              ToolkitProvider (ABC)              │
├──────────┬──────────────┬───────────────────────┤
│  Shell   │  MCP (Raw)   │  McpBasedProvider(ABC)│
│          │              ├─────┬──────┬──────────┤
│          │              │Slack│GitHub│  Notion  │
└──────────┴──────────────┴─────┴──────┴──────────┘
```

- **MCP (Raw)**: power users directly configure arbitrary MCP servers.
- **Service Toolkit**: service-specific defaults + simplified authentication settings; internally reuses MCP infrastructure.

## Prerequisite: Clean Up Toolkit Naming

Current code naming is confusing. **Do this before implementing Service Toolkit.**

### Current → New

| Concept | Current Code | After Change | Notes |
|------|-----------|---------|------|
| Toolkit type identifier (enum) | `ToolDefinition` | `ToolkitType` | Remove confusion between "Tool" and "Toolkit" |
| Toolkit type identifier (column) | `tool_slug` | `toolkit_type` | Align column name |
| Toolkit implementation base (ABC) | `ToolkitDefinition` | `ToolkitProvider` | "Definition" sounds like static metadata, but this actually owns dynamic logic such as tool creation and credential exchange. "Provider" fits the role. |
| Workspace config instance | `RDBToolkit` / `slug` | keep | |
| Agent assignment | `RDBAgentToolkit` | keep | |
| Registry | `TOOLKIT_REGISTRY` | keep | type: `dict[ToolkitType, type[ToolkitProvider[Any]]]` |

### Relationship Clarification

- **ToolkitType** — identifies the toolkit kind: `"shell"`, `"mcp"`, `"slack"`, `"github"`.
- **ToolkitProvider** — knows how a toolkit kind behaves, including tool creation and credential exchange.
- **Toolkit** — configuration instance created in a Workspace: ToolkitType + Config + Credentials.
- **AgentToolkit** — Toolkit assigned to an Agent.

Runtime: find `ToolkitProvider` by `Toolkit.toolkit_type` → pass `Toolkit.config` → create tools.

## Core Implementation: Shared Base Class

```python
class McpBasedToolkitProvider(ToolkitProvider[ConfigT], ABC):
    """Common base for MCP-server-based toolkits."""

    @abstractmethod
    def resolve_mcp_params(self, config: ConfigT) -> ResolvedMcpParams:
        """Convert service-specific config into MCP connection params."""
        ...

    async def create_tools(self, config: ConfigT, context: ToolkitContext):
        params = self.resolve_mcp_params(config)
        headers = _build_auth_headers(params)
        mcp_tools = await mcp_list_tools(params.server_url, headers, ...)
        return [_wrap_mcp_tool(t, ...) for t in mcp_tools]
```

Service-specific implementations only handle config conversion and defaults.

```python
class ToolkitType(enum.StrEnum):
    SHELL = "shell"
    MCP = "mcp"
    SLACK = "slack"
    GITHUB = "github"

class SlackToolkitProvider(McpBasedToolkitProvider[SlackToolkitConfig]):
    slug = "slack"
    ...

class GitHubToolkitProvider(McpBasedToolkitProvider[GitHubToolkitConfig]):
    slug = "github"
    ...
```

## Discussion: MCP Server URL

### Conclusion

- **Services with official MCP servers**, such as Slack and GitHub: hardcode the official URL as config default.
- **Services without official MCP servers**, such as Discord: NoIntern hosts one and migrates when an official server appears.
- Since Service Toolkit abstracts the URL, user settings can remain unchanged even if the backend server changes later.

Users do not need to know the MCP server URL. They only configure authentication.

## Discussion: Credential Sources

Credential sources differ by service:

| Service | Reuse Existing Installation | Direct Input (BYOA) |
|--------|----------------------|-----------------|
| **Slack** | platform app bot_token | own app token |
| **Discord** | platform bot token | own bot token |
| **GitHub** | none | PAT / GitHub App / OAuth App |
| **Notion** | none | Integration token |
| **Jira** | none | API token / OAuth |

Common patterns:

1. **Existing Installation link** — reuse token when a bot is already installed, as with Slack and Discord.
2. **Direct credential input** — common to every service.
3. **Service decides auth type** — users do not need to know MCP authentication terms.

### Slack: Installation-based

The NoIntern platform app's bot_token already includes the scopes needed for MCP calls. If a Slack Installation exists, Slack Toolkit works immediately without additional credentials.

**BYOA**: Phase 1 implements Installation-based behavior while keeping BYOA in mind. Power users who need BYOA immediately can use Raw MCP Toolkit for now.

### GitHub: Analysis by Auth Mode

GitHub supports three authentication methods:

#### 1. PAT (Personal Access Token)

- A specific user enters a PAT as the workspace representative.
- All agents call with that token.
- MCP mapping: **bearer**, storing PAT in `encrypted_credentials`.
- system context (scheduled run): **available**.
- Setup: enter PAT only.
- Same as existing MCP `bearer` authentication. Simple.

#### 2. GitHub App

- Install GitHub App → app_id + private_key + installation_id.
- Platform signs JWT → exchanges for installation access token → uses as bearer.
- MCP mapping: **no exact existing auth type matches**.
- system context: **available**.
- Setup: app_id, private_key, installation_id.
- JWT signing → access token exchange is GitHub-specific logic and cannot be covered by generic OAuth2 flow.
- This justifies allowing Service Toolkit to contain service-specific auth logic.

#### 3. OAuth App

- Per-user authentication through GitHub OAuth App client_id/secret.
- MCP mapping: **oauth2_per_user**, storing per-user token in `mcp_oauth2_tokens`.
- system context: **not available**.
- Setup: manager enters client_id, client_secret.
- Reuses existing MCP `oauth2_per_user` infrastructure.

#### Conclusion: Placement of GitHub App auth logic

GitHub App JWT signing is service-specific logic. Approaches reviewed:

- **(a) Base hook**: add credential exchange hook to `McpBasedToolkitProvider` — pollutes the base.
- **(b) Add credential type**: add service-specific types such as `McpSecretsGitHubApp` to MCP infrastructure — pollutes MCP infrastructure.
- **(c) Service Toolkit exchange**: Service Toolkit exchanges token itself, then passes bearer — service-specific isolation.

**Conclusion: choose (c), but separate timing from `create_tools()` into the resolve stage.**

Current credential flow:

```text
resolve.py: decrypt credentials → Provider(secret=decrypted_value) → create_tools()
```

Add a service-specific token exchange stage:

```text
resolve.py:
  1. decrypt encrypted_credentials, current behavior
  2. resolve_credentials() — service-specific token exchange, new
     e.g. GitHub App signs JWT → installation access token
  3. pass final bearer token into provider constructor
  → create_tools() receives only a token and calls MCP
```

```python
class McpBasedToolkitProvider(ToolkitProvider[ConfigT], ABC):
    async def resolve_credentials(
        self, raw_secret: str | None, config: ConfigT,
    ) -> str | None:
        """Convert decrypted credential into the token actually used.
        Default: return as-is. Override per service."""
        return raw_secret
```

- Credential exchange and tool creation responsibilities are separated.
- Service-specific logic such as JWT signing is encapsulated in the service Provider's `resolve_credentials()`.
- Base class and MCP infrastructure stay clean.

## Completed Discussions

### `agent_toolkits` constraint

#### Conclusion: keep current behavior

- DB constraint is `UNIQUE(agent_id, toolkit_id)`, preventing only duplicate attachment of the same toolkit config.
- Multiple toolkits of the same kind are allowed, such as two GitHub Toolkits for different orgs.
- Tool prefix is based on Toolkit `slug`, so name conflicts do not occur.
- No additional restriction is needed.

### Service Toolkit addition cost

#### Conclusion: low cost

Per service, required work:

- Config model (Pydantic) with service-specific fields.
- Provider class overriding `resolve_mcp_params()` and `resolve_credentials()`.
- Registry registration by adding enum.
- Frontend form with service-specific configuration UI.

`McpBasedToolkitProvider` handles MCP connection and tool wrapping, so service-specific code only handles config conversion, defaults, and auth exchange. Each service should stay within a few hundred lines.

### Coexistence with Raw MCP

#### Conclusion: keep Raw MCP

- Keep it for power users configuring arbitrary MCP servers directly.
- Services without Service Toolkit can still connect through Raw MCP.
- `McpToolkitProvider` also inherits `McpBasedToolkitProvider`, so there is no code duplication.

## Implementation Feasibility Check

We identified three issues in the current code that must be solved to implement Service Toolkit.

### Issue 1: MCP-specific credential logic in resolve.py

**Current state**: `resolve_agent_tools()` hardcodes around 50 lines of MCP credential handling logic. Adding Service Toolkits would keep adding `elif` branches.

```python
# current resolve.py (problem)
if at.toolkit_type == ToolkitType.MCP:
    # per-user OAuth2: look up user token + refresh on expiry (~20 lines)
    # create per_user_auth context (~15 lines)
    definition = _make_mcp_definition(toolkit.credentials, ...)
else:
    validated_config = type(definition).validate_config(toolkit.config)
```

**Conclusion**: add a `resolve()` method to `ToolkitProvider` ABC and encapsulate credential logic inside each Provider.

```python
class ToolkitProvider(ABC, Generic[ConfigT]):
    @abstractmethod
    async def resolve(self, context: ResolveContext) -> "ToolkitProvider[ConfigT]":
        """Resolve per-config credentials. Return a new instance if needed."""
        ...
```

Then resolve.py only calls `provider.resolve(context)` without knowing Provider type. DB dependencies such as token repositories are injected into Provider constructors.

### Issue 2: Unify duplicated registry structure

**Current state**: Toolkit registry exists in two places.

| Location | Type | Purpose |
|------|------|------|
| `core/tool_registry.py` | `dict[ToolkitType, type[ToolkitProvider]]` | class mapping, static metadata |
| `worker/engine.py` `__post_init__` | `dict[str, ToolkitProvider]` | instance mapping, runtime tool creation |

**Conclusion**: unify into one `dict[str, ToolkitProvider[Any]]`. Since classmethods can also be called from instances, a class registry is unnecessary.

- Remove `TOOLKIT_REGISTRY` module variable.
- Remove `_toolkit_registry` construction code from `engine.__post_init__`.
- Assemble and inject registry through FastAPI Depends chain.

```python
# engine/tools/deps.py
def get_toolkit_registry(
    shell: Annotated[ShellToolkitProvider, Depends()],
    mcp: Annotated[McpToolkitProvider, Depends()],
) -> dict[str, ToolkitProvider[Any]]:
    return {
        "shell": shell,
        "mcp": mcp,
    }
```

Each Provider declares dependencies with `Annotated[..., Depends()]` in its constructor, so FastAPI resolves dependencies automatically. No separate `get_*` factory function is needed.

```python
class McpToolkitProvider(McpBasedToolkitProvider[McpToolkitConfig]):
    def __init__(
        self,
        token_repo: Annotated[MCPOAuth2TokenRepository, Depends()],
        auth_request_repo: Annotated[MCPAuthRequestRepository, Depends()],
    ) -> None:
        self.token_repo = token_repo
        self.auth_request_repo = auth_request_repo
```

### Issue 3: Scope for extracting McpBasedToolkitProvider

**Current state**: `McpToolkitProvider` in mcp.py, about 250 lines, mixes Raw MCP-specific logic with common MCP logic.

| Feature | Shareable | Raw MCP Only |
|------|:---------:|:------------:|
| MCP server connection (SSE/Streamable HTTP) | O | |
| `mcp_list_tools()` | O | |
| `_wrap_mcp_tool()` | O | |
| `_build_auth_headers()` | O | |
| per-user OAuth2 branch | O | |
| `_make_request_authorization_tool()` | O | |
| Parse URL/secret from credentials | | O |
| Config validation based on URL | | O |

**Conclusion**: extract common logic into `McpBasedToolkitProvider` base class.

```python
class McpBasedToolkitProvider(ToolkitProvider[ConfigT], ABC):
    """Common MCP-protocol logic: connection, tool listing, wrapping, auth."""
    ...

class McpToolkitProvider(McpBasedToolkitProvider[McpToolkitConfig]):
    """Raw MCP: user directly enters URL. credentials → URL/secret parsing."""
    ...

class SlackToolkitProvider(McpBasedToolkitProvider[SlackToolkitConfig]):
    """Slack: fixed MCP server URL, Slack-specific config schema."""
    ...
```
