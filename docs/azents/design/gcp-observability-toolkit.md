---
title: "GCP Toolkit Design — Google Hosted Remote MCP"
tags: [backend, engine, frontend, infra]
created: 2026-03-26
updated: 2026-03-26
implemented: 2026-03-26
---

# GCP Toolkit Design

## Overview

Integrate Google-hosted Remote MCP servers as nointern Service Toolkit so agents can directly query and manage GCP resources.

Prioritize services needed for application/infrastructure monitoring, and connect multiple GCP MCP servers from one `gcp` Toolkit.

**User scenarios:**
1. "Show 500 error logs from the last hour" → Cloud Logging `list_log_entries`
2. "Analyze CPU usage metric trend" → Cloud Monitoring `list_timeseries`
3. "Check pod status in production GKE cluster" → GKE `kube_get`
4. "Show Cloud Run service list" → Cloud Run `list_services`
5. "Query error rate with PromQL" → Cloud Monitoring `query_range`

## Discussion Points and Decisions

### 1. Google Hosted Remote MCP vs stdio MCP

**Options:**
- A) Google Hosted Remote MCP (HTTP) — `https://{service}.googleapis.com/mcp`
- B) `@google-cloud/observability-mcp` (stdio, Google official preview)
- C) `google-cloud-mcp` (stdio, community)

**Decision: A — Google Hosted Remote MCP**

Rationale:
- **No sidecar needed** — HTTP transport connects through existing MCP infra without mcp-proxy sidecar.
- **Google-managed infra** — always up to date, Google Cloud ToS applies, no separate image build.
- **Rich tools** — Logging 6, Monitoring 7 (including PromQL), GKE 8, Compute 29.
- **Easy service expansion** — 20+ GCP services already have MCP endpoints; adding service only needs URL registration.
- Since 2026-03-17, MCP endpoints are automatically enabled when GCP API is enabled.

Downsides compared with stdio:
- Separate MCP server URL per service → multiple connections needed (see "Multiple server connection" below).
- Need direct implementation of SA Key to access_token exchange logic (no ADC library).

### 2. Supported services and priority

Classify into 3 tiers from App/Infra monitoring perspective:

| Tier | Service | Tool count | Rationale |
|------|--------|--------|------|
| **1 — Core Observability** | Cloud Logging | 6 | log query/analysis (essential for incident response) |
| | Cloud Monitoring | 7 | metrics/alerts/PromQL (SLO/SLI monitoring) |
| **2 — Infrastructure** | GKE | 8 | K8s resource query (`kube_get`, `kube_api_resources`) |
| | Compute Engine | 29 | VM status/disks/network |
| | Cloud Run | 4 | service status/deployments |
| **3 — Data** | Cloud SQL | 11 | DB instance management/SQL execution |
| | BigQuery | 5+ | data analysis/query |

**Decision: User chooses on/off per service. Default enables Tier 1 (Logging + Monitoring).**

Tier 2~3 are additionally selectable with checkboxes. Required IAM roles differ by service, so guide user to select based on permissions granted to SA.

### 3. Multiple server connection

**Problem:** Current `McpToolkitConfig` supports only one `server_url`. GCP Toolkit needs to connect to separate URL per service.

**Options:**
- A) Create separate ToolkitConfig per service (user creates 6 toolkits)
- B) One GCP Toolkit internally manages multiple MCP connections
- C) Extend `McpToolkitConfig` to support multiple URLs

**Decision: B — GcpToolkitProvider manages multiple MCP connections internally**

Rationale:
- User should see one "GCP" — per-service toolkit fragments UX.
- Provider `resolve()` creates `McpBasedToolkit` instance per selected service.
- `create_tools()` combines tools from every service and returns them.
- No need to change existing `McpToolkitConfig`.

### 4. Authentication method

**Decision: Service Account Key JSON → JWT → access_token exchange**

Flow:
```
SA Key JSON (stored in encrypted_credentials)
  → create JWT (RS256, iss=client_email, scope=required scopes)
  → POST https://oauth2.googleapis.com/token
  → access_token (valid 1 hour, auto-refresh)
  → Authorization: Bearer {access_token}
  → x-goog-user-project: {project_id}
```

access_token caching:
- Provider caches issued token in memory.
- Automatically refresh 5 minutes before expiration.
- Since service scopes differ, cache by scope combination.

### 5. Read/Write permission separation

**Problem:** Compute Engine, Cloud Run, Cloud SQL include write tools that modify infrastructure. For monitoring purpose, exposing only read-only is safer.

**Read/write distribution by tool:**

| Service | Read-only | Write | Write tool examples |
|--------|:-:|:-:|------|
| Cloud Logging | 6 | 0 | — |
| Cloud Monitoring | 7 | 0 | — |
| GKE | 8 | 0 | — |
| Compute Engine | 22 | 7 | `create_instance`, `delete_instance`, `stop_instance` |
| Cloud Run | 2 | 2 | `deploy_service_from_image` |
| Cloud SQL | 3 | 8 | `execute_sql`, `create_instance`, `update_instance` |

**Decision: per-service read-only / full-access mode selection**

- Google Hosted MCP tools have `readOnlyHint` annotation.
- Implementation possible by filtering tools with `readOnlyHint: false` in `create_tools()`.
- Defense in depth: recommend granting only viewer roles in IAM as well (SA permission + tool filtering double block).
- Logging/Monitoring/GKE are all read-only, so no setting needed — show toggle only for services with write tools.

Add per-service access mode to Config model:

```python
class GcpServiceAccess(BaseModel):
    """Per-service access mode."""

    service: GcpService
    read_only: bool = True  # default: read-only (safe)
```

### 6. x-goog-user-project header

Google Hosted MCP requires `x-goog-user-project` header for billing/quota attribution. Automatically inject `config.project_id`.

## Architecture

### Full flow

```mermaid
graph LR
    subgraph "Agent Home Pod"
        SB[sandbox container]
    end

    subgraph "Worker Pod"
        E[Engine]
        PROV[GcpToolkitProvider]
        MCP1["McpBasedToolkit<br/>(Logging)"]
        MCP2["McpBasedToolkit<br/>(Monitoring)"]
        MCP3["McpBasedToolkit<br/>(GKE)"]
    end

    subgraph "Google Cloud"
        G1["logging.googleapis.com/mcp"]
        G2["monitoring.googleapis.com/mcp"]
        G3["container.googleapis.com/mcp"]
    end

    E --> PROV
    PROV --> MCP1
    PROV --> MCP2
    PROV --> MCP3
    MCP1 -->|"HTTPS + Bearer"| G1
    MCP2 -->|"HTTPS + Bearer"| G2
    MCP3 -->|"HTTPS + Bearer"| G3
```

**Core: no sidecar.** Worker Pod directly connects to Google Cloud MCP server over HTTPS. Existing MCP egress proxy can still be used (mcp-egress-proxy already handles MCP HTTP traffic).

### Comparison with previous architecture

| Item | Previous design (stdio) | Current design (Hosted HTTP) |
|------|-------------------|------------------------|
| Transport | stdio → mcp-proxy → HTTP SSE | direct HTTPS |
| Sidecar | mcp-proxy sidecar needed | unnecessary |
| Auth | SA Key → `GOOGLE_APPLICATION_CREDENTIALS` | SA Key → JWT → Bearer token |
| Server management | MCP server preinstalled in image | managed by Google |
| Tool updates | image rebuild | automatic (Google-side update) |
| Cold start | Pod creation + MCP server start | none (HTTP immediate connection) |
| Infra change | Pod spec, ConfigMap, Secret | none |

## Data Model

### Service definitions

```python
class GcpService(enum.StrEnum):
    """Supported GCP MCP services."""

    LOGGING = "logging"
    MONITORING = "monitoring"
    GKE = "gke"
    COMPUTE = "compute"
    CLOUD_RUN = "cloud_run"
    CLOUD_SQL = "cloud_sql"


# Per-service MCP endpoint and OAuth scope
GCP_SERVICE_CONFIG: dict[GcpService, GcpServiceMeta] = {
    GcpService.LOGGING: GcpServiceMeta(
        endpoint="https://logging.googleapis.com/mcp",
        scopes=["https://www.googleapis.com/auth/logging.read"],
        iam_role="roles/logging.viewer",
        description="Cloud Logging — log queries and analysis",
    ),
    GcpService.MONITORING: GcpServiceMeta(
        endpoint="https://monitoring.googleapis.com/mcp",
        scopes=["https://www.googleapis.com/auth/monitoring.read"],
        iam_role="roles/monitoring.viewer",
        description="Cloud Monitoring — metrics, alerts, PromQL",
    ),
    GcpService.GKE: GcpServiceMeta(
        endpoint="https://container.googleapis.com/mcp",
        scopes=["https://www.googleapis.com/auth/cloud-platform"],
        iam_role="roles/container.viewer",
        description="GKE — cluster and Kubernetes resource status",
    ),
    GcpService.COMPUTE: GcpServiceMeta(
        endpoint="https://compute.googleapis.com/mcp",
        scopes=["https://www.googleapis.com/auth/compute.readonly"],
        iam_role="roles/compute.viewer",
        description="Compute Engine — VM instances, disks, networks",
    ),
    GcpService.CLOUD_RUN: GcpServiceMeta(
        endpoint="https://run.googleapis.com/mcp",
        scopes=["https://www.googleapis.com/auth/cloud-platform"],
        iam_role="roles/run.viewer",
        description="Cloud Run — service status and deployment",
    ),
    GcpService.CLOUD_SQL: GcpServiceMeta(
        endpoint="https://sqladmin.googleapis.com/mcp",
        scopes=["https://www.googleapis.com/auth/cloud-platform"],
        iam_role="roles/cloudsql.viewer",
        description="Cloud SQL — database instances and queries",
    ),
}

DEFAULT_SERVICES: list[GcpService] = [GcpService.LOGGING, GcpService.MONITORING]
```

### Config model (plaintext, JSONB)

```python
class GcpToolkitConfig(BaseModel):
    """GCP Toolkit configuration."""

    project_id: str = Field(
        description="GCP project ID",
        min_length=6,
        max_length=30,
        pattern=r"^[a-z][a-z0-9-]{4,28}[a-z0-9]$",
    )
    services: list[GcpService] = Field(
        default=DEFAULT_SERVICES,
        description="Enabled GCP services",
        min_length=1,
    )
    writable_services: list[GcpService] = Field(
        default=[],
        description="Services with write access allowed (default: all read-only)",
    )
    timeout: float = Field(
        default=30.0,
        description="MCP tool call timeout (seconds)",
        ge=1.0,
        le=300.0,
    )
```

### Credential model (encrypted)

```python
class GcpSecrets(BaseModel):
    """GCP Service Account Key (encrypted storage)."""

    type: Literal["service_account_key"] = "service_account_key"
    service_account_key: dict[str, Any] = Field(
        description="Full GCP Service Account Key JSON"
    )
```

### DB storage structure

| Field | Content | Example |
|------|------|------|
| `toolkit_type` | `"gcp"` | |
| `config` (JSONB) | `GcpToolkitConfig` | `{"project_id": "my-proj", "services": ["logging", "monitoring", "gke"]}` |
| `encrypted_credentials` | encrypted `GcpSecrets` | Fernet encrypted JSON |

## Provided Tool List

### Cloud Logging (6 tools)

| Tool | Description | Major parameters |
|------|------|-------------|
| `list_log_entries` | search/query log entries | `resourceNames`, `filter`, `orderBy`, `pageSize` |
| `list_log_names` | list log names in project | `parent` |
| `get_bucket` | detail of specific log bucket | `name` |
| `list_buckets` | list log buckets | `parent` |
| `get_view` | log view detail | `name` |
| `list_views` | list log views | `parent` |

### Cloud Monitoring (7 tools)

| Tool | Description | Major parameters |
|------|------|-------------|
| `list_timeseries` | query metric time series data | `name`, `filter`, `interval`, `view`, `aggregation` |
| `query_range` | **PromQL range query** | `name`, `query`, `start`, `end`, `step` |
| `get_alert_policy` | alert policy detail | `name` |
| `list_alert_policies` | list alert policies | `name`, `filter` |
| `get_alert` | alert (violation) detail | `name` |
| `list_alerts` | list alerts | `parent`, `filter` |
| `list_metric_descriptors` | metric type discovery | `name`, `filter` |

### GKE (8 tools)

| Tool | Description | Major parameters |
|------|------|-------------|
| `kube_api_resources` | list K8s API resources | cluster info |
| `kube_get` | **query K8s resources** (pods, deployments, etc.) | type, name, namespace, label selector |
| `list_clusters` | list GKE clusters | project, location |
| `get_cluster` | cluster detail | cluster name |
| `list_operations` | list GKE operations | project, location |
| `get_operation` | operation detail | operation name |
| `list_node_pools` | list node pools | cluster name |
| `get_node_pool` | node pool detail | node pool name |

### Compute Engine (29 tools = 22 read + 7 write)

| Tool | Description | R/W |
|------|------|:---:|
| `list_instances` | list VM instances | R |
| `get_instance_basic_info` | VM detail | R |
| `list_disks` / `get_disk_basic_info` | disk information | R |
| `list_instance_group_managers` | list instance group managers | R |
| `list_managed_instances` | list managed instances | R |
| `list_snapshots` | list snapshots | R |
| + 16 more read tools | templates, machine types, accelerators, etc. | R |
| `create_instance` / `delete_instance` | create/delete VM | **W** |
| `start_instance` / `stop_instance` / `reset_instance` | start/stop/reset VM | **W** |
| `set_instance_machine_type` | change machine type | **W** |

### Cloud Run (4 tools = 2 read + 2 write)

| Tool | Description | R/W |
|------|------|:---:|
| `list_services` | list Cloud Run services | R |
| `get_service` | service detail (URI, deployment status) | R |
| `deploy_service_from_image` | deploy container image | **W** |
| `deploy_service_from_archive` | deploy source archive | **W** |

### Cloud SQL (11 tools = 3 read + 8 write)

| Tool | Description | R/W |
|------|------|:---:|
| `list_instances` / `get_instance` | list/detail instances | R |
| `list_users` | list users | R |
| `get_operation` | operation status | R |
| `execute_sql` | execute SQL (DDL/DML/DQL) | **W** |
| `create_instance` / `clone_instance` / `update_instance` | instance management | **W** |
| `create_user` / `update_user` | user management | **W** |
| `import_data` | data import | **W** |

## Provider Implementation

### GcpToolkitProvider

```python
class GcpToolkitProvider(ToolkitProvider[GcpToolkitConfig]):
    """GCP Toolkit Provider.

    Direct HTTP connection to Google Hosted Remote MCP servers.
    Creates McpBasedToolkit instance per selected service and integrates
    tools from multiple MCP servers into one Toolkit.
    """

    slug: ClassVar[str] = "gcp"
    name: ClassVar[str] = "GCP"
    description: ClassVar[str] = (
        "Google Cloud Platform — Logging, Monitoring, GKE, "
        "Compute Engine, Cloud Run, Cloud SQL"
    )
    system_prompt: ClassVar[str] = (
        "You have access to Google Cloud Platform tools. "
        "Use them to query logs, metrics, alerts, Kubernetes resources, "
        "VM instances, and other GCP infrastructure from the configured project."
    )
    config_model: ClassVar[type[BaseModel]] = GcpToolkitConfig
```

### resolve flow

```python
async def resolve(
    self, config: GcpToolkitConfig, context: ResolveContext,
) -> Toolkit[GcpToolkitConfig]:
    """Configure MCP connection for selected services."""
    # 1. Decrypt credential
    secrets = GcpSecrets.model_validate_json(context.credentials_json)

    # 2. Collect required OAuth scopes (scope union by service)
    all_scopes: set[str] = set()
    for svc in config.services:
        all_scopes.update(GCP_SERVICE_CONFIG[svc].scopes)

    # 3. Create access token provider (caching + auto refresh)
    token_provider = GcpAccessTokenProvider(
        service_account_key=secrets.service_account_key,
        scopes=sorted(all_scopes),
    )

    # 4. Configure per-service MCP connection info
    server_configs = []
    for svc in config.services:
        meta = GCP_SERVICE_CONFIG[svc]
        server_configs.append(GcpMcpServerConfig(
            service=svc,
            endpoint=meta.endpoint,
            token_provider=token_provider,
            project_id=config.project_id,
            timeout=config.timeout,
        ))

    # 5. Return GcpToolkit
    return GcpToolkit(config=config, server_configs=server_configs)
```

### create_tools flow

```python
class GcpToolkit(Toolkit[GcpToolkitConfig]):
    """Unified provider of tools from multiple GCP MCP servers."""

    async def create_tools(
        self, config: GcpToolkitConfig, context: ToolkitContext,
    ) -> list[FunctionTool]:
        tools: list[FunctionTool] = []
        writable_set = set(config.writable_services)

        for server in self._server_configs:
            # tools/list call to each service's MCP server
            access_token = await server.token_provider.get_token()
            headers = {
                "Authorization": f"Bearer {access_token}",
                "x-goog-user-project": server.project_id,
            }
            mcp_tools = await mcp_list_tools(
                server.endpoint, headers=headers, timeout=server.timeout,
            )

            # read/write filtering
            is_writable = server.service in writable_set
            for tool in mcp_tools:
                # Exclude tools whose readOnlyHint is false unless write access is enabled.
                annotations = tool.get("annotations", {})
                is_read_only = annotations.get("readOnlyHint", True)
                if not is_read_only and not is_writable:
                    continue  # filter write tool

                tools.append(_wrap_gcp_mcp_tool(tool, server))

        return tools
```

### Access Token Provider

```python
class GcpAccessTokenProvider:
    """Issue, cache, and refresh access_token from SA Key."""

    def __init__(self, service_account_key: dict[str, Any], scopes: list[str]) -> None:
        self._key = service_account_key
        self._scopes = scopes
        self._token: str | None = None
        self._expires_at: datetime | None = None
        self._lock = asyncio.Lock()

    async def get_token(self) -> str:
        """Return valid access_token. Auto-refresh 5 minutes before expiration."""
        if self._token and self._expires_at and self._expires_at > datetime.now(UTC) + timedelta(minutes=5):
            return self._token

        async with self._lock:
            # double-check
            if self._token and self._expires_at and self._expires_at > datetime.now(UTC) + timedelta(minutes=5):
                return self._token

            # create JWT (RS256)
            now = datetime.now(UTC)
            payload = {
                "iss": self._key["client_email"],
                "scope": " ".join(self._scopes),
                "aud": "https://oauth2.googleapis.com/token",
                "iat": int(now.timestamp()),
                "exp": int((now + timedelta(hours=1)).timestamp()),
            }
            signed_jwt = jwt.encode(payload, self._key["private_key"], algorithm="RS256")

            # Token exchange
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    "https://oauth2.googleapis.com/token",
                    data={
                        "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                        "assertion": signed_jwt,
                    },
                )
                resp.raise_for_status()
                data = resp.json()

            self._token = data["access_token"]
            self._expires_at = now + timedelta(seconds=data["expires_in"])
            return self._token
```

### Connection Test

```python
async def test_connection(
    self, config: GcpToolkitConfig, credentials_json: str | None, proxy_url: str | None = None,
) -> TestConnectionResult:
    """Test connection by issuing token from SA Key + tools/list for each service."""
    if not credentials_json:
        return TestConnectionResult(success=False, message="No credentials provided")

    secrets = GcpSecrets.model_validate_json(credentials_json)
    key = secrets.service_account_key

    # 1. Token issue test
    try:
        all_scopes = set()
        for svc in config.services:
            all_scopes.update(GCP_SERVICE_CONFIG[svc].scopes)

        provider = GcpAccessTokenProvider(key, sorted(all_scopes))
        token = await provider.get_token()
    except Exception as e:
        return TestConnectionResult(success=False, message=f"Authentication failed: {e}")

    # 2. Per-service connection test (tools/list)
    results = []
    for svc in config.services:
        meta = GCP_SERVICE_CONFIG[svc]
        try:
            tools = await mcp_list_tools(
                meta.endpoint,
                headers={
                    "Authorization": f"Bearer {token}",
                    "x-goog-user-project": config.project_id,
                },
                timeout=10.0,
            )
            results.append(f"{svc.value}: {len(tools)} tools")
        except Exception as e:
            results.append(f"{svc.value}: FAILED ({e})")

    all_ok = all("FAILED" not in r for r in results)
    detail = "\n".join(results)
    return TestConnectionResult(
        success=all_ok,
        message=f"Project '{config.project_id}' as {key['client_email']}\n{detail}",
    )
```

## DI Registration

```python
# engine/tools/deps.py
def get_toolkit_registry(
    cipher: CredentialCipher,
    session_manager: SessionManager[AsyncSession],
    config: Config,
) -> dict[str, ToolkitProvider[Any]]:
    return {
        "mcp": McpToolkitProvider(...),
        "github": GitHubToolkitProvider(...),
        "notion": NotionToolkitProvider(...),
        "gcp": GcpToolkitProvider(),  # no external dependency
    }
```

## API

Use existing Toolkit CRUD API as-is. No additional endpoint needed.

### Create request example

```json
{
  "toolkit_type": "gcp",
  "slug": "gcp-prod",
  "name": "GCP Production",
  "description": "Production GCP monitoring",
  "config": {
    "project_id": "my-production-project",
    "services": ["logging", "monitoring", "gke"],
    "timeout": 30
  },
  "credentials": {
    "type": "service_account_key",
    "service_account_key": {
      "type": "service_account",
      "project_id": "my-production-project",
      "private_key": "-----BEGIN PRIVATE KEY-----\n...",
      "client_email": "observability-sa@my-production-project.iam.gserviceaccount.com",
      "token_uri": "https://oauth2.googleapis.com/token"
    }
  },
  "enabled": true
}
```

## Frontend (UI/UX)

### GcpConfigFields component

```
┌─────────────────────────────────────────────────┐
│ GCP Settings                                    │
│                                                 │
│ Project ID *                                    │
│ ┌─────────────────────────────────────────────┐ │
│ │ my-production-project                       │ │
│ └─────────────────────────────────────────────┘ │
│                                                 │
│ Services                                        │
│                                                 │
│ ── Core Observability ──                        │
│ ☑ Cloud Logging     log query/analysis          │
│ ☑ Cloud Monitoring   metrics/alerts/PromQL      │
│                                                 │
│ ── Infrastructure ──                            │
│ ☐ GKE               K8s resource query          │
│ ☑ Compute Engine     VM/disks/network           │
│    └ ☐ Write access (create/delete/start/stop VM) │
│ ☐ Cloud Run          service status/deployment  │
│    └ ☐ Write access (service deployment)        │
│                                                 │
│ ── Data ──                                      │
│ ☐ Cloud SQL          DB instances/SQL execution │
│    └ ☐ Write access (SQL execution/instance mgmt) │
│                                                 │
│ Service Account Key *                           │
│ ┌─────────────────────────────────────────────┐ │
│ │ { "type": "service_account", ...}         │ │
│ └─────────────────────────────────────────────┘ │
│ 📎 or upload .json file                         │
│                                                 │
│ ⓘ Required IAM roles for Service Account:       │
│   • roles/mcp.toolUser (required)               │
│   • roles/logging.viewer (Logging)              │
│   • roles/monitoring.viewer (Monitoring)        │
│   (display dynamically based on selected services) │
│                                                 │
│ ┌──────────────────┐                            │
│ │ Test Connection  │                            │
│ └──────────────────┘                            │
│ ✅ Project 'my-production-project'              │
│    as observability-sa@my-prod.iam.gsa.com      │
│    logging: 6 tools                             │
│    monitoring: 7 tools                          │
│    gke: 8 tools                                 │
│                                                 │
│ ▼ Advanced Settings                             │
│   Timeout: [30] seconds                         │
└─────────────────────────────────────────────────┘
```

### Dynamic IAM role guidance

Automatically show required roles based on selected services:

| Service | Read-only IAM | Write IAM |
|--------|--------------|-----------|
| (common) | `roles/mcp.toolUser` | (same) |
| Logging | `roles/logging.viewer` | — (no write tools) |
| Monitoring | `roles/monitoring.viewer` | — (no write tools) |
| GKE | `roles/container.viewer` | — (no write tools) |
| Compute | `roles/compute.viewer` | `roles/compute.instanceAdmin.v1` |
| Cloud Run | `roles/run.viewer` | `roles/run.admin` |
| Cloud SQL | `roles/cloudsql.viewer` | `roles/cloudsql.admin` |

## Infrastructure

### No infrastructure changes

Google Hosted MCP is HTTPS endpoint, so:
- **No sidecar needed** — no Pod spec change.
- **No ConfigMap/Secret needed** — credential encrypted in DB, decrypted at runtime.
- **No NetworkPolicy change** — `*.googleapis.com` is public IP, existing egress allowed.
- **No Docker image change** — MCP server runs in Google infra.

Only change: add `PyJWT` package dependency in `GcpAccessTokenProvider` (for JWT signing).

### Through MCP Egress Proxy

Existing mcp-egress-proxy handles MCP HTTP traffic, so GCP MCP traffic can also be proxied through same path. No additional configuration needed.

## Feasibility Verification

| Item | Status | Note |
|------|------|------|
| MCP server availability | ✅ | Google-managed, 20+ services |
| HTTP transport | ✅ | reuse existing McpBasedToolkit |
| SA Key → Bearer auth | ✅ | standard GCP OAuth2 JWT flow |
| multiple server connection | ✅ | per-service connection inside Provider |
| existing API compatibility | ✅ | Toolkit CRUD as-is |
| Frontend pattern | ✅ | GithubConfigFields pattern |
| infrastructure change | ✅ | **none** (largest advantage) |
| network security | ✅ | public IP, existing egress allowed |
| token auto-refresh | ✅ | expires in 1 hour, refresh 5 min before |

### Risks

| Risk | Impact | Mitigation |
|--------|------|------|
| Google MCP API change | tool compatibility | dynamic discovery with tools/list, robust against schema changes |
| SA Key leak | GCP resource access | Fernet encryption, least-privilege IAM, read-only default |
| Rate limiting | tool call failure | GCP default quota sufficient, retry logic |
| Token issuance failure | all services unavailable | pre-verify in Connection test, detailed error message |

## Implementation Plan

### Phase 1: Backend — Provider + Auth

1. Add `GCP = "gcp"` to `ToolkitType` enum.
2. Define `GcpToolkitConfig`, `GcpSecrets`, `GcpService` models.
3. Implement `GcpAccessTokenProvider` (JWT → access_token, caching).
4. Implement `GcpToolkitProvider` (resolve, validate_credentials, test_connection).
5. `GcpToolkit.create_tools()` — integrate tools from multiple MCP servers.
6. Register in `get_toolkit_registry()`.
7. DB migration: add `"gcp"` to `toolkit_type` enum.
8. Add `PyJWT` dependency.

### Phase 2: Frontend — GcpConfigFields

1. `GcpConfigFields.tsx` component (tiered service selection, SA Key input).
2. Add `gcp` branch to `ToolkitForm.tsx`.
3. Dynamic IAM role guidance.
4. Display per-service tool count in Connection test result.

### Phase 3: Verification

1. Connection test E2E (SA Key → token issue → tools/list).
2. Actual tool call E2E (log query, metric query).
3. Token auto-refresh verification (1 hour+ session).
4. Per-service enable/disable verification.

## Alternatives Considered

### 1. `@google-cloud/observability-mcp` (stdio, Google official preview)

Provides integrated 4 services as stdio MCP server: Logging/Monitoring/Trace/Error Reporting. Requires mcp-proxy sidecar, Pod spec change + image build + ConfigMap/Secret management burden. Infrastructure complexity is higher than Google Hosted MCP, and service coverage is narrower (no GKE/Compute). Preview status separate from Google Cloud ToS applicability.

### 2. `google-cloud-mcp` (stdio, community)

Community project (v0.1.3). Broad coverage including Profiler, but requires build and has uncertain long-term maintenance. No reason to choose it now that official Hosted MCP exists.

### 3. Create separate Toolkit per service

Register each GCP service as separate ToolkitType (gcp_logging, gcp_monitoring, ...). User must create per-service toolkit, causing UX fragmentation. SA Key also needs duplicate entry per service.

### 4. Manual registration with existing `mcp` type

User directly enters each service URL through generic MCP toolkit. Possible, but user must manually perform SA Key → JWT → token exchange for bearer auth. Service-specific scope management also manual. This removes value of automation.
