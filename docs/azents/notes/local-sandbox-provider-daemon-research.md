---
title: "Local sandbox provider daemon research"
created: 2026-05-20
tags: [nointern, sandbox, provider, docker, agent-runtime, research]
status: research-note
---

# Local sandbox provider daemon research

## 1. Goal

This note summarizes research for a customer-provided sandbox pool model.

The target product experience is:

1. A customer runs a NoIntern sandbox provider daemon on their own local machine.
2. The daemon authenticates with NoIntern using a customer/workspace-scoped credential.
3. After authentication, the daemon is automatically registered as a sandbox provider for the customer's NoIntern workspace.
4. When an `AgentRuntime` needs a sandbox, NoIntern allocates it to that provider.
5. The provider daemon starts a local Docker container for that runtime, mounts persistent per-runtime workspace volumes, and injects the existing sandbox-control client environment.
6. The sandbox container's in-sandbox client opens the existing outbound `sandbox-control` gRPC stream back to NoIntern.
7. NoIntern continues to use the existing command/file/checkpoint control plane.

The intended customer-facing command should be close to:

```bash
nointern-sandbox-provider login
nointern-sandbox-provider start
```

or, for token-based automation:

```bash
NOINTERN_PROVIDER_TOKEN=... nointern-sandbox-provider start
```

The daemon should then appear in the NoIntern workspace UI as an online sandbox provider with capacity and health information.

## 2. Current architecture findings

The current NoIntern sandbox implementation is already close to supporting this model because sandbox lifecycle and sandbox command/file control are separated.

Relevant files:

- `python/apps/nointern/src/nointern/runtime/sandbox/session_sandbox.py`
- `python/apps/nointern/src/nointern/runtime/sandbox/session_sandbox_manager.py`
- `python/apps/nointern/src/nointern/runtime/sandbox/session_sandbox_docker.py`
- `python/apps/nointern/src/nointern/runtime/sandbox/session_sandbox_k8s.py`
- `python/apps/nointern/src/nointern/runtime/sandbox/control/server.py`
- `python/apps/nointern/src/nointern/runtime/sandbox/control/service.py`
- `python/apps/nointern/src/nointern/runtime/sandbox/control/registry.py`
- `python/apps/nointern/src/nointern/runtime/sandbox/control/router.py`
- `python/apps/nointern/src/nointern/runtime/sandbox/control/worker_client.py`
- `python/apps/nointern-sandbox-client/src/nointern_sandbox_client/*`
- `proto/nointern/sandbox_control/v1/sandbox_control.proto`
- `docs/nointern/adr/0008-agent-runtime-sandbox-control-channel.md`
- `docs/nointern/design/in-sandbox-sandbox-client-control-channel.md`

### 2.1 Lifecycle and command/file transport are separate

`SessionSandboxClient` is the backend lifecycle interface. It handles infrastructure-level operations such as:

- `ensure_ready(...)`
- `observe_runtime(...)`
- `list_runtimes()`
- `delete_session(...)`
- `sandbox_reachable_url(...)`
- `close()`

Although the names still contain `Session`, the current design treats the actual sandbox owner as `AgentRuntime`. `AgentSession` remains a user-facing/session/event boundary.

Direct backend `exec`, `read_file`, and `write_file` paths are no longer the primary transport. The Docker backend raises if these direct paths are used:

```python
raise RuntimeError("Sandbox exec requires sandbox-control worker client")
```

This means a new provider backend can focus on lifecycle only. It does not need to invent a new command/file protocol.

### 2.2 Existing Docker backend is the closest implementation reference

`DockerSessionSandboxClient` creates one main runtime container per agent runtime. It bind-mounts:

```text
{data_path}/agent-runtimes/{runtime_id}/home-sandbox -> /home/sandbox
{data_path}/agent-runtimes/{runtime_id}/tmp-agent    -> /tmp/agent
```

It injects the following environment variables into the container:

```text
SANDBOX_CONTROL_ENDPOINT
SANDBOX_CONTROL_AGENT_RUNTIME_ID
SANDBOX_CONTROL_AGENT_ID
SANDBOX_CONTROL_WORKSPACE_ID
SANDBOX_CONTROL_CONNECTION_ID
SANDBOX_CONTROL_GENERATION
```

Those variables are the key runtime contract for launching a sandbox container that can attach to NoIntern.

A local customer provider daemon can reuse this exact contract while moving Docker control out of the NoIntern worker process and into a customer-owned daemon.

### 2.3 The in-sandbox client is already outbound-first

`python/apps/nointern-sandbox-client` is a small process intended to run inside the sandbox. It reads `SANDBOX_CONTROL_*` settings, opens a gRPC stream to `sandbox-control`, and handles:

- shell exec via local subprocess
- file read/write/stat/list/delete via local POSIX filesystem
- request/response correlation through `request_id`

The client connects outbound using:

```python
grpc.aio.insecure_channel(settings.endpoint)
```

For a customer local provider, this should evolve to use a TLS-authenticated public endpoint, but the high-level protocol shape is already correct.

### 2.4 sandbox-control already supports the desired control plane

`proto/nointern/sandbox_control/v1/sandbox_control.proto` defines two services:

```proto
service SandboxControlRuntime {
  rpc Connect(stream ClientMessage) returns (stream ServerMessage);
}

service SandboxControlWorker {
  rpc Exec(WorkerExecRequest) returns (WorkerExecResponse);
  rpc TerminateExec(WorkerTerminateExecRequest) returns (WorkerAck);
  rpc FileRead(WorkerFileReadRequest) returns (WorkerFileReadResponse);
  rpc FileWrite(WorkerFileWriteRequest) returns (WorkerAck);
  rpc FileStat(WorkerFileStatRequest) returns (FileStatResult);
  rpc FileList(WorkerFileListRequest) returns (FileListResult);
  rpc FileDelete(WorkerFileDeleteRequest) returns (WorkerAck);
  rpc CheckpointCreate(WorkerCheckpointCreateRequest) returns (WorkerCheckpointResult);
  rpc CheckpointRestore(WorkerCheckpointRestoreRequest) returns (WorkerCheckpointResult);
}
```

The runtime-side `Connect` stream is opened by the sandbox container. The worker-side service is used by NoIntern to execute commands, read/write files, and create/restore checkpoints.

The active connection registry is Redis-backed and keyed by `AgentRuntime.id`. It records:

- `agent_runtime_id`
- `connection_id`
- `generation`
- `control_instance_id`
- `registered_at`
- `last_heartbeat_at`
- `state`

The `generation` field fences stale connections. This is important for container restart, provider reconnect, and duplicate connection handling.

## 3. Proposed high-level architecture

The recommended direction is to keep the existing `sandbox-control` protocol and add a new provider lifecycle plane.

```text
Customer local machine
┌──────────────────────────────────────────────┐
│ nointern-sandbox-provider daemon              │
│                                              │
│  - authenticates with NoIntern                │
│  - registers as workspace sandbox provider    │
│  - receives allocation requests over outbound │
│    provider-control stream                    │
│  - manages local Docker containers            │
│                                              │
│  Docker                                      │
│   └─ nointern-agent-runtime                  │
│       └─ nointern-sandbox-client             │
│           └─ outbound sandbox-control gRPC    │
└──────────────────────────────────────────────┘
                 │ outbound
                 ▼
NoIntern cloud
┌──────────────────────────────────────────────┐
│ Provider Control Service                      │
│  - provider registration                      │
│  - provider heartbeat/capacity                │
│  - allocation/delete/observe routing          │
│                                              │
│ Sandbox Control Service                       │
│  - existing runtime gRPC stream               │
│  - exec/file/checkpoint routing               │
│                                              │
│ Sandbox lifecycle manager                     │
│  - AgentRuntime lifecycle                     │
│  - hibernate/checkpoint/restore               │
└──────────────────────────────────────────────┘
```

There are two outbound connections:

1. Provider daemon to provider-control.
2. Individual sandbox container to sandbox-control.

This avoids requiring customers to expose inbound ports from their local machine.

## 4. Integration point in NoIntern

The cleanest NoIntern integration is a new `SessionSandboxClient` implementation, for example:

```python
class ExternalProviderSessionSandboxClient(SessionSandboxClient):
    async def ensure_ready(...):
        ...

    async def observe_runtime(...):
        ...

    async def list_runtimes(...):
        ...

    async def delete_session(...):
        ...

    def sandbox_reachable_url(...):
        ...
```

This backend would not talk to Docker or Kubernetes directly. Instead, it would talk to a provider-control service that has active outbound connections from customer provider daemons.

Expected flow:

1. `SessionSandboxManager._ensure_backend_and_control_ready()` calls backend `ensure_ready(...)`.
2. `ExternalProviderSessionSandboxClient.ensure_ready(...)` asks provider-control to allocate the runtime to an online provider.
3. Provider-control sends `AllocateRuntime` to the selected daemon.
4. The daemon starts a Docker container and injects `SANDBOX_CONTROL_*` env vars.
5. The container's `nointern-sandbox-client` registers to existing sandbox-control.
6. `SessionSandboxManager` continues with existing `control_runtime.wait_ready(...)`.

This keeps most of the existing manager/control path unchanged.

## 5. Customer authentication and registration UX

### 5.1 Preferred UX: device login

The best customer experience is a device login flow:

```bash
nointern-sandbox-provider login
```

The CLI prints:

```text
Open this URL:
https://example.invalid/device

Enter code:
ABCD-EFGH
```

The customer logs in, selects a workspace, and approves the local provider. The daemon receives a provider credential and stores it locally.

Then:

```bash
nointern-sandbox-provider start
```

After connecting, the provider appears in the workspace UI.

### 5.2 Automation UX: provider token

For non-interactive setup, the workspace UI can create a provider token:

```bash
nointern-sandbox-provider start \
  --workspace ws_123 \
  --token niprov_xxxxx
```

or:

```bash
NOINTERN_PROVIDER_TOKEN=niprov_xxxxx nointern-sandbox-provider start
```

### 5.3 Provider credential scope

The daemon should not store a general user access token. It should store a restricted provider credential scoped to one workspace/provider.

Suggested permissions:

```text
allow:
  - sandbox_provider:connect
  - sandbox_provider:heartbeat
  - sandbox_provider:report_runtime
  - sandbox_provider:receive_allocation
  - sandbox_provider:receive_delete

deny:
  - read workspace files directly
  - read user messages
  - call agent APIs
  - access billing/admin APIs
```

## 6. Provider daemon responsibilities

The local daemon should own local-machine concerns:

- authenticate to NoIntern
- register provider identity and capacity
- send heartbeat and health information
- receive allocation/delete/observe requests
- pull or verify allowed runtime images
- create Docker containers
- create per-runtime persistent volume directories
- inject sandbox-control environment variables
- enforce resource limits
- observe container health
- preserve `/home/sandbox` across stop/delete when requested
- clean up orphan containers
- rediscover existing runtime containers/volumes after daemon restart

Suggested local data layout:

```text
~/.nointern/sandbox-provider/
  config.yaml
  provider.db
  runtimes/
    arun_123/
      home-sandbox/
      tmp-agent/
      metadata.json
    arun_456/
      home-sandbox/
      tmp-agent/
      metadata.json
```

The daemon should mount:

```text
~/.nointern/sandbox-provider/runtimes/{agent_runtime_id}/home-sandbox -> /home/sandbox
~/.nointern/sandbox-provider/runtimes/{agent_runtime_id}/tmp-agent    -> /tmp/agent
```

## 7. Provider-control API sketch

Provider-control should also be outbound-first.

```proto
service SandboxProviderControl {
  rpc ConnectProvider(stream ProviderMessage) returns (stream ServerProviderMessage);
}
```

Initial message types:

```proto
message ProviderRegister {
  string provider_id = 1;
  string workspace_id = 2;
  string display_name = 3;
  string daemon_version = 4;
  string os = 5;
  string arch = 6;
  string docker_version = 7;
  uint32 max_runtimes = 8;
  repeated string capabilities = 9;
}

message ProviderHeartbeat {
  uint64 sequence = 1;
  uint32 running_runtimes = 2;
  uint32 available_slots = 3;
  uint64 available_memory_bytes = 4;
  uint64 available_disk_bytes = 5;
  repeated RuntimeObservation runtimes = 6;
}

message RuntimeAllocateRequest {
  string request_id = 1;
  string agent_runtime_id = 2;
  string agent_id = 3;
  string workspace_id = 4;
  string image = 5;
  string sandbox_control_endpoint = 6;
  string sandbox_control_connection_id = 7;
  uint64 sandbox_control_generation = 8;
  repeated string allowed_domains = 9;
  repeated string denied_domains = 10;
  map<string, string> labels = 11;
}

message RuntimeDeleteRequest {
  string request_id = 1;
  string agent_runtime_id = 2;
  bool preserve_volume = 3;
}

message RuntimeObservation {
  string agent_runtime_id = 1;
  string provider_runtime_id = 2;
  string state = 3;
  string reason = 4;
  string container_id = 5;
  string image = 6;
  uint64 generation = 7;
}
```

This is intentionally a sketch. The first implementation should keep the provider API minimal and reuse existing sandbox-control for command/file/checkpoint operations.

## 8. State and data model candidates

### 8.1 SandboxProvider

Persistent DB model candidate:

```text
sandbox_provider
- id
- workspace_id
- owner_user_id
- display_name
- type: local_docker | external_vendor | managed
- status: online | offline | draining | disabled
- created_at
- last_seen_at
- max_runtimes
- running_runtimes
- capabilities json
- version
```

### 8.2 SandboxProviderCredential

```text
sandbox_provider_credential
- id
- provider_id
- token_hash
- expires_at
- revoked_at
- created_by_user_id
- last_used_at
```

### 8.3 Provider connection registry

This should be short-lived and Redis-backed, similar to sandbox-control connection registry:

```text
provider_connection
- provider_id
- connection_id
- generation
- control_instance_id
- last_heartbeat_at
- capacity
- state
```

### 8.4 Runtime provider lease

A runtime-to-provider lease is needed to avoid duplicate allocation and to recover from daemon/control-plane restarts:

```text
runtime_provider_lease
- agent_runtime_id
- workspace_id
- provider_id
- provider_runtime_id
- allocation_generation
- state: allocated | starting | running | hibernated | deleting | lost
- created_at
- updated_at
- last_observed_at
```

## 9. Hibernate and persistence model

There are two possible hibernate models.

### 9.1 Recommended MVP: NoIntern-driven hibernate with provider volume preservation

NoIntern remains the lifecycle state authority.

Hibernate flow:

1. NoIntern detects idle runtime.
2. NoIntern creates a checkpoint if configured.
3. NoIntern sends `DeleteRuntime(preserve_volume=true)` to provider.
4. Provider stops/removes the container but keeps the per-runtime volume directory.
5. NoIntern marks the runtime as hibernated.

Resume flow:

1. NoIntern requests allocation for the same `agent_runtime_id`.
2. Provider starts a new container with the same local volume mount.
3. The in-sandbox client registers to sandbox-control.
4. NoIntern waits for sandbox-control readiness.

This gives the customer the practical behavior of local hibernate/resume while keeping NoIntern as the state authority.

### 9.2 Future: provider-initiated hibernate

Later, the provider may request hibernate because of local conditions:

- laptop shutdown
- battery pressure
- disk pressure
- user manually pauses the provider
- daemon upgrade

The safer pattern is provider-requested, NoIntern-approved hibernate:

```text
Provider -> NoIntern: RuntimeHibernateRequested(reason)
NoIntern -> sandbox-control: CheckpointCreate if needed
NoIntern -> Provider: StopRuntime(preserve_volume=true)
NoIntern -> DB: mark hibernated
```

The provider should not unilaterally mutate durable runtime state in NoIntern.

## 10. Security prerequisites

A customer-provided local provider introduces a public/external trust boundary. The following are prerequisites before production use:

1. Provider credentials must be workspace-scoped and revocable.
2. Provider-control must use TLS.
3. sandbox-control must use TLS for public/local-machine providers.
4. sandbox-control register should require a runtime-scoped authorization token, not just `SANDBOX_CONTROL_AGENT_RUNTIME_ID` env vars.
5. Allocation leases should bind provider id, runtime id, connection generation, and sandbox-control auth token.
6. The provider daemon must restrict runtime images to an allowlist or signed image policy.
7. Host path mounts must be limited to daemon-owned data roots.
8. The Docker socket must never be mounted into sandbox containers.
9. Containers need memory, CPU, pids, and disk constraints.
10. Rootless Docker or stronger isolation should be evaluated.
11. The workspace UI must allow disabling/revoking a provider.
12. Provider offline/lost handling must prevent stale runtimes from being treated as ready.

The current local Docker backend uses local-dev assumptions and should not be treated as production isolation policy for customer machines without hardening.

## 11. Scheduling and provider selection

Initial policy can be simple:

1. Find online providers registered to the workspace.
2. Filter by capacity and required capabilities.
3. Prefer a user-selected provider if set.
4. Otherwise choose least-loaded provider.
5. If configured, fall back to managed K8s sandbox.

Config shape candidate:

```text
sandbox.backend = k8s | docker | external_provider | hybrid
external_provider.mode = required | preferred | disabled
```

Workspace-level settings can expose:

```text
Local sandbox providers:
- disabled
- preferred for this workspace
- required for selected agents
```

## 12. Implementation phases

### Phase 0 — Design vocabulary and docs

- Define provider-control vs sandbox-control.
- Define provider, runtime lease, provider credential, provider connection.
- Document expected customer UX.

### Phase 1 — Provider registration only

- Add provider credential creation.
- Add provider daemon skeleton.
- Implement outbound provider register/heartbeat.
- Show provider status in workspace UI or internal admin endpoint.
- No runtime allocation yet.

### Phase 2 — External provider backend

- Add `ExternalProviderSessionSandboxClient`.
- Add config value for `external_provider` backend or hybrid mode.
- Implement `ensure_ready`, `delete_session`, `observe_runtime`, `list_runtimes` through provider-control.
- Reuse existing `SessionSandboxManager` readiness wait through sandbox-control.

### Phase 3 — Local Docker runtime daemon

- Provider daemon creates Docker containers.
- Provider daemon injects `SANDBOX_CONTROL_*` env vars.
- Provider daemon mounts persistent per-runtime `/home/sandbox` and `/tmp/agent` directories.
- Existing `nointern-sandbox-client` connects to sandbox-control.
- Verify shell exec and file read/write.

### Phase 4 — Hibernate/resume

- Implement `DeleteRuntime(preserve_volume=true)`.
- Reallocate same `agent_runtime_id` with same local volume.
- Add daemon restart rediscovery.
- Add orphan container/volume reconciliation.

### Phase 5 — Security hardening

- Provider credential revocation.
- Runtime-scoped sandbox-control auth.
- TLS endpoint for sandbox-control and provider-control.
- Image policy.
- Rootless Docker/resource limits.
- Provider offline/lost recovery.

## 13. Open questions

1. Should local provider volume persistence be considered authoritative, or should remote checkpoint remain required for durable workspaces?
2. Should provider selection be workspace-level, agent-level, or runtime-level?
3. Should provider-control be a new service or part of existing sandbox-control deployment?
4. What auth mechanism should sandbox-control runtime registration use for public providers?
5. How should NoIntern handle provider reconnect when containers are still running locally?
6. Should a local provider support multiple workspaces, or should each daemon credential map to one workspace?
7. How should image updates be coordinated with long-lived local volumes?
8. What minimum Docker isolation profile is acceptable for a customer-provided provider?
9. Should provider daemons expose any local UI/logs for customer debugging?
10. How should billing/usage attribution work for customer-provided compute?

## 14. Recommendation

Start with the minimal architecture:

```text
existing sandbox-control protocol
+ new provider-control outbound stream
+ new ExternalProviderSessionSandboxClient lifecycle backend
+ local Docker provider daemon
+ NoIntern-driven hibernate with provider volume preservation
```

This approach preserves the current AgentRuntime-centric lifecycle model and avoids rewriting command/file/checkpoint transport. It also matches the desired customer UX: a customer authenticates locally, starts a daemon, and the daemon automatically becomes available as sandbox capacity in the customer's NoIntern workspace.
