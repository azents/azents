---
title: "Sandbox Daemon Design — Shell + File Tool Integration"
tags: [architecture, engine, infra]
created: 2026-03-25
updated: 2026-03-25
implemented: 2026-03-25
---

# Sandbox Daemon Design

## Overview

Introduce lightweight HTTP daemon inside sandbox container of Agent Home Pod to provide Shell execution and LLM-facing file tools in integrated way.

**Problems solved:**
- Production dependency problems of K8s exec (K8s API load, rate limit, WebSocket resources)
- EFS path limitation of File tool (cannot access entire sandbox filesystem)
- N+1 call inefficiency of grep/glob

**Things not changed:**
- File-API service (kept for memory, skills, attachments, session data)
- Engine/Worker architecture (Engine stays in Worker Pod)

## Architecture

```
Worker Pod                               Agent Home Pod (nointern-sandbox)
┌──────────────────────────┐            ┌──────────────────────────────────┐
│ Engine                   │            │ sandbox container                │
│ ├─ ReAct loop            │            │ ┌──────────────────────────────┐ │
│ ├─ LLM, DB, Redis       │  HTTP      │ │ supervisord                  │ │
│ ├─ all secrets           │ ────────→  │ │ ├─ sandbox-daemon (:8081)   │ │
│ └─ Adapters              │ Pod IP     │ │ ├─ mitmproxy (:8080)        │ │
│                          │            │ │ └─ socat (unix↔tcp)         │ │
│ File-API (:8081)         │            │ └──────────────────────────────┘ │
│ ├─ Memory/Skills read   │            │                                  │
│ ├─ Attachments           │            │ EFS mount (/mnt/agent-data)      │
│ └─ SessionDataSaver     │            └──────────────────────────────────┘
└──────────────────────────┘
```

## Sandbox Daemon

### Role

HTTP server running inside sandbox container. It handles every request through bwrap-exec and preserves filesystem isolation based on bwrap mount namespace.

### API

#### Shell execution

```
POST /exec
Content-Type: application/json

{
  "command": "ls -la /home/sandbox",
  "user_id": "user-123",     # optional, reflected in bwrap --user-dir
  "timeout": 30
}

Response: Chunked HTTP streaming (stdout/stderr interleaved)
```

- Run command with bwrap-exec.
- Stream stdout/stderr in real time with Chunked HTTP.
- stdin unnecessary (bwrap-exec runs `bash -c`).

#### File read

```
GET /files?path=/home/sandbox/myfile.txt&user_id=user-123

Response: 200 OK
Content-Type: application/octet-stream (or detected MIME)
Body: file content
```

- Read file through bwrap-exec.
- Support binary files (images, etc., several MB).
- Support offset/limit (for text read).

#### File write

```
PUT /files?path=/home/sandbox/myfile.txt&user_id=user-123
Content-Type: application/octet-stream
Body: file content

Response: 200 OK
{
  "uri": "/home/sandbox/myfile.txt",
  "media_type": "text/plain",
  "size": 1234,
  "name": "myfile.txt"
}
```

- Write safely via bwrap-exec using base64 stdin delivery.
- Automatically create parent directory.
- Return attachment metadata.

#### File edit

```
PATCH /files?path=/home/sandbox/myfile.txt&user_id=user-123
Content-Type: application/json

{
  "old_string": "foo",
  "new_string": "bar",
  "replace_all": false
}

Response: 200 OK
```

- Daemon internally performs read → exact match replace → write.
- Completes in single HTTP call.

#### File delete

```
DELETE /files?path=/home/sandbox/myfile.txt&user_id=user-123

Response: 204 No Content
```

#### Glob (file search)

```
GET /files/glob?pattern=/data/agent/*.txt&user_id=user-123

Response: 200 OK
["data/agent/a.txt", "/data/agent/b.txt"]
```

- Run `find` in bwrap-exec — complete in one call.
- Greatly improves over current N+1 calls (list + fnmatch).

#### Grep (content search)

```
GET /files/grep?pattern=error&path=/data/agent/&user_id=user-123

Response: 200 OK
[
  {"file": "/data/agent/log.txt", "line": 42, "content": "error occurred"}
]
```

- Run `grep -rn` in bwrap-exec — complete in one call.
- Greatly improves over current N+1 calls (list + per-file get + Python regex).

#### Health

```
GET /health

Response: 200 OK
```

### Code Location

`python/apps/nointern-sandbox-daemon/` — separate app following same pattern as File-API (`nointern-file-api`).

### Framework

FastAPI. Same as existing File-API.

## Security Model

### bwrap network isolation

```
Inside bwrap (user code)                 Outside bwrap (container)
┌──────────────────────────┐           ┌──────────────────────────┐
│ --unshare-net            │           │                          │
│ only loopback exists     │           │ sandbox-daemon :8081     │
│                          │           │ mitmproxy :8080          │
│ socat :3128 ─────────────│──→ /run/proxy/proxy.sock             │
│   (HTTP_PROXY)           │           │       → socat → :8080   │
└──────────────────────────┘           └──────────────────────────┘
```

- bwrap separates network namespace with `--unshare-net`.
- User code can access only loopback + socat(:3128 → unix socket → mitmproxy).
- Direct access to sandbox daemon port(:8081) is not possible.
- Ingress NetworkPolicy is **required** — daemon handles shell execution, so allow only Worker Pod:

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: sandbox-ingress-allow-worker
  namespace: nointern-sandbox
spec:
  podSelector:
    matchLabels:
      app: agent-home
  policyTypes:
    - Ingress
  ingress:
    - from:
        - namespaceSelector:
            matchLabels:
              name: nointern-server
      ports:
        - port: 8081
          protocol: TCP
```

### Path Security

bwrap mount namespace determines file access scope:

```bash
--ro-bind /usr /usr                    # system binaries (read-only)
--ro-bind /etc /etc                    # system config (read-only)
--ro-bind /opt/platform-data /data/platform  # Platform skills (read-only)
--bind "$HOME_DIR" /home/sandbox       # Agent home (read/write)
--bind "$AGENT_DIR" /data/agent        # Agent data (read/write)
--bind "$USER_DIR" /data/user          # User data (read/write, per user_id)
```

LLM can access whole sandbox filesystem (including system files). This is intended behavior.

## Responsibility Split with File-API

| Role | Owner | Pod required | Reason |
|---|---|---|---|
| LLM-facing file tool | sandbox daemon | required | whole filesystem, through bwrap |
| Shell execution | sandbox daemon | required | bwrap-exec |
| Memory/Skills read | File-API | not required | at tool resolution time, works without Pod |
| Platform skills | File-API | not required | baked into sandbox image, Worker cannot access |
| Attachment upload/download | File-API | not required | used by API Server |
| Image storage, output truncation | File-API | not required | SessionDataSaver (inside engine) |

File tools always go through sandbox daemon. If Pod is absent, lazy creation happens before execution (same pattern as shell). No File-API fallback.

## Cold Start Lifecycle

```
Message arrives
├── Tool resolution (Phase 1)
│   ├── Memory read → File-API (Pod unnecessary)
│   ├── Skills read → File-API (Pod unnecessary)
│   └── Create Tool objects (file/shell tool — not executed yet)
├── LLM call
└── Tool execution (Phase 2)
    ├── LLM calls file/shell tool
    ├── Agent Home Pod ensure_ready (lazy creation, ~10s)
    │   └── Worker sends "Starting..." to interface
    └── HTTP request to sandbox daemon
```

## Process Management

### Introduce supervisord

All processes are managed by supervisord. Existing entrypoint.sh mitmproxy/socat setup is also moved to supervisord.

Even if socat starts before mitmproxy, it is fine — socat creates unix socket listener and forwards to TCP:8080 when connection arrives. If mitmproxy is not up yet, only that connection fails and socat itself remains. Once mitmproxy is up, subsequent connections work normally.

| Process | Role | Port |
|---|---|---|
| mitmproxy | HTTP proxy (domain filtering) | 8080 |
| socat | unix socket ↔ TCP bridge | /run/proxy/proxy.sock |
| sandbox-daemon | Shell + File HTTP API | 8081 |

```ini
[supervisord]
nodaemon=true
logfile=/proc/1/fd/1
pidfile=/var/run/supervisord.pid

[program:mitmproxy]
command=mitmdump --mode regular@8080 --set confdir=/etc/mitmproxy --set ssl_insecure=true -s /etc/mitmproxy/addon.py --quiet
autostart=%(ENV_ENABLE_PROXY)s
autorestart=true
stopsignal=TERM
stdout_logfile=/proc/1/fd/1
stderr_logfile=/proc/1/fd/2

[program:socat]
command=socat UNIX-LISTEN:/run/proxy/proxy.sock,fork,reuseaddr TCP:127.0.0.1:8080
autostart=%(ENV_ENABLE_PROXY)s
autorestart=true
stopsignal=TERM
stdout_logfile=/proc/1/fd/1
stderr_logfile=/proc/1/fd/2

[program:sandbox-daemon]
command=python -m nointern_sandbox_daemon --port 8081
autostart=true
autorestart=true
stopsignal=TERM
stopasgroup=true
killasgroup=true
stdout_logfile=/proc/1/fd/1
stderr_logfile=/proc/1/fd/2
```

Change `ENABLE_PROXY` env to `true`/`false` string (from existing `1`/`0`).

entrypoint.sh → `exec supervisord -c /etc/supervisor/supervisord.conf`

### Health Check

Daemon `/health` endpoint also checks proxy socket existence. Replace existing `_wait_for_proxy()` K8s exec polling with K8s native readiness probe.

```yaml
readinessProbe:
  httpGet:
    path: /health
    port: 8081
  initialDelaySeconds: 2
  periodSeconds: 5
  failureThreshold: 3
livenessProbe:
  httpGet:
    path: /health
    port: 8081
  initialDelaySeconds: 10
  periodSeconds: 10
  failureThreshold: 3
```

Daemon `/health` response:
- when proxy enabled: daemon ready + proxy socket exists → 200
- when proxy disabled: daemon ready → 200

### Resources

Baseline memory increases by ~100MB due to daemon addition.

```yaml
resources:
  requests:
    cpu: "500m"
    memory: "768Mi"     # increased from existing 512Mi
  limits:
    cpu: "2"
    memory: "2Gi"       # unchanged
```

## Engine/Worker Code Changes

### AgentHomeClient Interface

Keep existing interface. Replace only implementation:

```python
class AgentHomeClient(abc.ABC):
    async def exec(agent_id, command, *, user_id, timeout) -> ExecResult
    async def write_file(agent_id, path, content) -> None
    async def read_file(agent_id, path) -> bytes
    # ... keep existing methods
```

- K8s: `kubernetes_asyncio.stream.stream_pod_exec()` → `httpx.AsyncClient.post(f"http://{pod_ip}:8081/exec")`
- Docker: `aiodocker container.exec()` → `httpx.AsyncClient.post(f"http://{container_ip}:8081/exec")`

### LLM-facing file tools

Replace current `session_storage` (FileApiClient) with new `SandboxDaemonClient`.

| Tool | Current | Change |
|---|---|---|
| read_text | FileApiClient.get() | SandboxDaemonClient.get() |
| read_image | FileApiClient.get() | SandboxDaemonClient.get() |
| write | FileApiClient.put() | SandboxDaemonClient.put() |
| edit | FileApiClient.get() + put() | SandboxDaemonClient.edit() (one call) |
| delete_file | FileApiClient.delete() | SandboxDaemonClient.delete() |
| glob | FileApiClient.list() + fnmatch | SandboxDaemonClient.glob() (one call) |
| grep | FileApiClient.list() + N×get() | SandboxDaemonClient.grep() (one call) |
| present_file | FileApiClient.get() | SandboxDaemonClient.get() + thumbnail generation in engine |

## Implementation Plan

### Phase 1: Daemon MVP

1. Create `python/apps/nointern-sandbox-daemon/`
   - FastAPI app, `/exec`, `/files/*`, `/health` endpoints
   - bwrap-exec subprocess execution
   - Chunked HTTP streaming (shell stdout/stderr)
2. Add supervisord to Dockerfile and write supervisord config.
3. Convert entrypoint.sh to supervisord.

### Phase 2: Engine Integration

1. Implement `SandboxDaemonClient` (httpx-based).
2. Replace `AgentHomeClient.exec()` implementation (K8s exec → daemon HTTP).
3. Convert LLM-facing file tools to SandboxDaemonClient.
4. Add health check to K8s Pod spec.

### Phase 3: Verification and Cleanup

1. Verify Docker local development environment.
2. Run K8s environment E2E tests.
3. Remove K8s exec dependency code.
4. Measure performance (daemon vs K8s exec).
