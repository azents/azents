---
title: "MCP Egress Proxy"
tags: [backend, infra, historical-reconstruction]
created: 2026-03-19
updated: 2026-03-19
implemented: 2026-03-19
document_role: primary
document_type: design
snapshot_id: mcp-260319
migration_source: "docs/azents/design/mcp-egress-proxy.md"
historical_reconstruction: true
---

# MCP Egress Proxy

## 1. Background

Users can freely input MCP (Model Context Protocol) server URL, which creates SSRF (Server-Side Request Forgery) risk.

### Current State

- Any URL can be entered in Toolkit setting `server_url` (no validation).
- MCP connection is made directly from worker pod (no proxy, no NetworkPolicy).
- sandbox pod has mitmproxy + NetworkPolicy, but MCP connection does not go through sandbox.

### Risks

| Attack vector | Severity | Description |
|----------|--------|------|
| AWS metadata exfiltration | CRITICAL | `http://169.254.169.254/` → IAM temporary credentials |
| Internal service access | CRITICAL | private IP access to RDS, Redis, K8s API, etc. |
| OAuth Discovery redirect | HIGH | server response redirects secondarily to internal URL |
| DCR POST amplification | HIGH | Dynamic Client Registration POSTs to internal service |

## 2. Design

### Architecture

```
worker pod
  │
  ├── LLM API, DB, Redis → direct connection (not through proxy)
  │
  └── MCP request (mcp_transport.py, mcp_discovery.py)
        │
        ↓
  mcp-egress-proxy (Squid, separate Deployment)
        │
        ├── private IP → blocked
        └── public IP → allowed → external MCP server
```

### Proxy Choice: Squid

Compared with mitmproxy (used in sandbox):

| | Squid | mitmproxy |
|--|-------|-----------|
| TLS | does not break TLS (CONNECT tunnel) | MITM decryption (requires CA cert) |
| Blocking method | `acl` + native IP | Python addon |
| Resource | ~10MB RAM | ~100MB RAM |
| Config | `squid.conf` | Python code |

MCP proxy only needs IP-level blocking, so Squid fits. TLS decryption, domain filtering, and audit logging are unnecessary.

### Placement: Separate Deployment

MCP traffic occurs only during toolkit initialization + tool calls (small volume). If sidecar is used, each worker pod has idle Squid wasting resources. Use separate 1-replica deployment shared by workers.

### Blocking Policy

Block only at IP level. No domain-level filtering.

```
acl blocked_nets dst 10.0.0.0/8 172.16.0.0/12 192.168.0.0/16 127.0.0.0/8 169.254.0.0/16 fd00::/8
http_access deny blocked_nets
http_access allow all
```

### Preventing Proxy Bypass

Do not enforce with NetworkPolicy. Control only by app-level httpx `proxy=` parameter.

- worker pod also needs direct access to LLM API, DB, Redis, etc., so whole egress must not be forced through proxy.
- NetworkPolicy is L4 policy and cannot distinguish "MCP request" from "LLM API request".
- Injecting `proxy=` only into MCP httpx client in app code is sufficient.

## 3. Implementation

### Squid Deployment

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: mcp-egress-proxy
  namespace: nointern
spec:
  replicas: 1
  selector:
    matchLabels:
      app: mcp-egress-proxy
  template:
    metadata:
      labels:
        app: mcp-egress-proxy
    spec:
      containers:
      - name: squid
        image: ubuntu/squid:latest
        ports:
        - containerPort: 3128
        volumeMounts:
        - name: config
          mountPath: /etc/squid/squid.conf
          subPath: squid.conf
        resources:
          requests:
            cpu: 50m
            memory: 32Mi
          limits:
            cpu: 200m
            memory: 128Mi
      volumes:
      - name: config
        configMap:
          name: mcp-egress-proxy-config
---
apiVersion: v1
kind: Service
metadata:
  name: mcp-egress-proxy
  namespace: nointern
spec:
  selector:
    app: mcp-egress-proxy
  ports:
  - port: 3128
    targetPort: 3128
---
apiVersion: v1
kind: ConfigMap
metadata:
  name: mcp-egress-proxy-config
  namespace: nointern
data:
  squid.conf: |
    # Block private IPs
    acl blocked_nets dst 10.0.0.0/8
    acl blocked_nets dst 172.16.0.0/12
    acl blocked_nets dst 192.168.0.0/16
    acl blocked_nets dst 127.0.0.0/8
    acl blocked_nets dst 169.254.0.0/16
    acl blocked_nets dst fc00::/7
    http_access deny blocked_nets

    # Allow rest
    http_access allow all

    # Port
    http_port 3128

    # Logging
    access_log stdio:/dev/stdout
    cache_log stdio:/dev/stderr

    # Disable cache (proxy purpose is not caching)
    cache deny all
```

### App Changes

**`core/config.py`** — add proxy URL setting:

```python
mcp_proxy_url: str | None = None
"""MCP-only egress proxy URL. If None, connect directly without proxy."""
```

**`core/mcp_transport.py`** — inject proxy into httpx client:

```python
@asynccontextmanager
async def _mcp_session(
    server_url: str,
    headers: dict[str, str],
    timeout: float,
    *,
    use_streamable_http: bool = False,
    proxy_url: str | None = None,
) -> AsyncGenerator[ClientSession]:
    timeout_td = timedelta(seconds=timeout)

    if use_streamable_http:
        client = httpx.AsyncClient(
            headers=headers,
            timeout=httpx.Timeout(timeout, read=300.0),
            proxy=proxy_url,
        )
        async with streamable_http_client(
            server_url, http_client=client
        ) as (r, w, _):
            async with ClientSession(r, w, ...) as session:
                await session.initialize()
                yield session
    else:
        def _proxy_client_factory(
            headers=None, timeout=None, auth=None,
        ):
            return httpx.AsyncClient(
                headers=headers,
                timeout=timeout,
                auth=auth,
                follow_redirects=True,
                proxy=proxy_url,
            )

        async with sse_client(
            server_url,
            headers=headers,
            timeout=timeout,
            httpx_client_factory=_proxy_client_factory,
        ) as (r, w):
            async with ClientSession(r, w, ...) as session:
                await session.initialize()
                yield session
```

**`core/mcp_discovery.py`** — apply proxy to discovery HTTP calls:

```python
async with httpx.AsyncClient(
    timeout=15.0,
    proxy=proxy_url,
) as client:
    response = await client.get(discovery_url)
```

### MCP Call Sites

| File | Function | proxy applied |
|------|------|-----------|
| `mcp_transport.py` | `_mcp_session()` | SSE: `httpx_client_factory`, Streamable: `httpx.AsyncClient(proxy=)` |
| `mcp_discovery.py` | `discover_resource_metadata()` | `httpx.AsyncClient(proxy=)` |
| `mcp_discovery.py` | `discover_auth_metadata()` | `httpx.AsyncClient(proxy=)` |
| `mcp_discovery.py` | `register_client()` | `httpx.AsyncClient(proxy=)` |
| `oauth2.py` | `exchange_authorization_code()` | `httpx.AsyncClient(proxy=)` |
| `oauth2.py` | `refresh_access_token()` | `httpx.AsyncClient(proxy=)` |
| `github.py` | `GitHubToolkit` (all auth methods) | through `McpBasedToolkit._proxy_url` |

## 4. Implementation Order

| Step | Task | Scope |
|------|------|------|
| 1 | Add `mcp_proxy_url` field to `Config` | config.py |
| 2 | Pass proxy parameter in `mcp_transport.py` | transport + call sites |
| 3 | Pass proxy parameter in `mcp_discovery.py` | discovery |
| 4 | Write Squid Deployment + Service + ConfigMap | infra |
| 5 | Add `MCP_PROXY_URL=http://mcp-egress-proxy:3128` to nointern-server environment variables | infra |
