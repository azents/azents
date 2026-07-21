---
title: "Sandbox System Redesign"
created: 2026-05-25
tags: [architecture, backend, engine, infra, historical-reconstruction, migration]
document_role: primary
document_type: adr
snapshot_id: sandbox-260525
historical_reconstruction: true
migration_source: "docs/azents/adr/0038-sandbox-system-redesign.md"
---

# sandbox-260525/ADR: Sandbox System Redesign

## Status

Accepted. This ADR records the decision that legacy Sandbox system must be replaced by Agent Runtime system. Later implementation details are recorded in `docs/azents/design/sandbox-260525-sandbox-redesign.md` and current behavior is defined by Living Specs.

## Context

Legacy Sandbox system grew from session-bound command execution into mixed runtime platform. Terms and responsibilities for Runtime, Sandbox, Session Workspace, Provider, sandbox-control, sandbox daemon, checkpoint, and file workspace became entangled.

Recurring issues:

- UI sometimes displayed Sandbox as stopped while backend resource was running, or exposed file/bash operations while Runner was not ready.
- API, Worker, and UI inferred lifecycle state and in-runtime operation availability from same source.
- Non-durable process-local handle/cache/active-session lookup became implicit source of truth in distributed system.
- Query APIs created side effects such as starting sandbox or observing provider.
- `/home/sandbox` path and S3 checkpoint/restore implementation leaked into domain contracts.
- Provider, Runner, and Control were coupled inside server process, making rollout/reconnect/failover fragile.

We need a clean domain model: Agent-scoped Runtime, external Provider, in-runtime Runner, stateless Control, explicit coordination store, and server-owned state summary.

## Decision

### 1. Replace user-facing Sandbox concept with Agent Runtime

Agent Runtime is the top-level execution abstraction. Sandbox becomes implementation detail. Product/UI/API language should use Agent Runtime and Agent Workspace instead of Session Sandbox/Session Workspace.

Runtime is Agent-scoped, not active-session-scoped. Runtime lookup must not depend on current active session. Session is transcript/event boundary; Runtime is execution and workspace boundary.

### 2. Separate Provider, Runner, Control, and Agent Workspace

- **Runtime Provider** owns lifecycle and backend resource: create/start/stop/restart/reset/observe. It also guarantees Agent Workspace persistence and reports workspace path.
- **Runner** runs inside Runtime and executes bash/file operations. It reports readiness, health, generation, operation progress/final events.
- **Control** is NoIntern runtime control plane. It receives Provider/Runner connections, manages durable state, routes commands/operations, and computes summary/actions.
- **Agent Workspace** is durable file workspace inside Runtime. Path is Provider-reported absolute path metadata, not hardcoded `/home/sandbox`.

Provider and Runner are external clients connecting outbound to Control. NoIntern server does not import Provider internals or reach into provider process directly.

### 3. Store domain state durably in PostgreSQL

PostgreSQL owns durable domain state:

- Agent Runtime settings and provider assignment
- desired state and desired generation
- provider observed state and observed generation
- provider connection state and generation
- runner state and generation
- Agent Workspace path metadata
- current-generation failure summary
- Runtime Provider registration and scope
- Agent/session history

Control replicas are stateless. Process memory is not source of truth.

### 4. Use Runtime Coordination Store only for active coordination

Runtime Coordination Store is separate abstraction for short-lived routing/operation coordination. Distributed deployment may use Redis Streams; standalone deployment may use in-memory queues.

It stores:

- provider command request stream
- runner request stream
- request body stream
- reply stream
- active operation metadata
- operation heartbeat / last event timestamp
- connection registry and generation fencing token
- routing grace period state
- background completion claim/idempotency state

It does not store domain state. Operation metadata/reply streams can be cleaned after foreground response finishes or background completion is delivered to Worker input queue.

### 5. Control never creates side effects from query APIs

Runtime query, Agent Workspace query, UI summary query, and list/detail endpoints only read stored durable state. They must not start Runtime, trigger observe, allocate backend resource, or send Provider command.

State changes happen only from:

- explicit user lifecycle command
- Provider state event
- Provider reconnect/disconnect
- Runner reconnect/disconnect
- periodic reconciliation tick
- explicit operation request/cancel/resume

### 6. Lifecycle is desired-state based and idempotent

Desired state has only `running` and `stopped`. `restart` and `reset` are commands, not stable states.

Every lifecycle command increments desired generation:

- `start`: desired state = running
- `stop`: desired state = stopped
- `restart`: final desired state = running, workspace preserved
- `reset`: destructive, final desired state supplied explicitly, Agent Workspace may be deleted
- `observe`: does not change desired state

Provider command includes desired generation. Provider observed/failure event includes desired generation. Control treats only current generation failure as current failure; older generation failures are stale diagnostics.

Retry is expressed by calling same lifecycle action again and increasing generation. No separate retry state is needed.

### 7. Provider observed state and Runner state are separate

Provider observed state represents backend resource lifecycle:

```text
unknown | stopped | starting | running | stopping | recovering | resetting | failed
```

`running` means backend resource exists/runs. It does not mean bash/file operations are usable.

Runner state represents in-runtime operation usability:

```text
unknown | disconnected | starting | ready | degraded | failed
```

Runner unavailable blocks bash/file/Agent Workspace operations but must not be interpreted as Runtime stopped. If backend is running and Provider is connected, stop/restart/reset may still be available.

Provider connection state is only:

```text
connected | disconnected
```

Configuration/capability/permission failures are separate domain errors, not connection state values.

### 8. Server computes UI summary/actions

API may expose raw axes, but frontend must render from server-provided summary/actions.

Summary statuses include user-facing states such as stopped, starting, running, stopping, resetting, recovering, provider disconnected, runner unavailable, failed.

Actions include:

- can start
- can stop
- can restart
- can reset
- can use runner
- can retry where relevant

Backend running but Runner unavailable should still expose stop/restart/reset. File/bash availability is only `can use runner`.

### 9. Control owns reconciliation

Control compares desired state and provider observed state. It does not directly manipulate Kubernetes Pod, Docker container, VM, or any backend resource. It reconciles only by sending Provider command or requesting observe.

When Provider sends event, Control validates generation, stores durable state, and compares with desired state. If desired is running and observed becomes stopped, Control may send start/recover command.

When Provider reconnects, it must re-report observed state for runtimes it owns. Control must not assume backend stopped just because provider disconnected.

Periodic reconciliation tick handles stale starting/stopping/resetting states, command timeouts, stale observed state, and missed events.

### 10. Rollout and reconnect use generation fencing

Control rollout is not lifecycle transition. If Provider/Runner stream disconnects during rollout, Control updates only connection/runner state. Desired state and provider observed state are not changed by rollout alone.

Provider/Runner reconnect receives new generation. Late events/responses from previous generation are ignored as stale.

Runner generation change is failure boundary for running operations. Operations accepted/running under old Runner generation are not attached to new generation; they finish as lost/failed/interrupted.

Provider generation change does not imply backend stopped. Provider must re-report observed state after reconnect; Control then reconciles.

### 11. Routing queues are ephemeral, not durable job queues

Runtime routing queue delivers request to active Runtime owner consumer. It does not store job for long-term automatic execution.

When request is published, routing layer gives short grace period for consumer to attach or claim request. If no consumer claims within grace, request fails as route unavailable with no side effect.

If consumer claimed request but connection is lost while forwarding to Provider/Runner, execution status may be unknown. Control must not automatically retry because Provider/Runner may have received request.

### 12. Provider command path and Runner request path are separate

Provider command path carries lifecycle/reconciliation commands: start, stop, restart, reset, observe.

Runner request path carries in-runtime operations: bash, file list/read/write/upload/download.

They may target same Runtime but are routed independently because Provider and Runner can be connected to different Control replicas.

Runner request is routed only when persistent Runtime state and Runner usability allow execution. Requests during stop/restart/reset/recover are not queued for later; they fail immediately with state-specific error. Reset is destructive, so pre-reset request must never run in post-reset Runtime.

### 13. Internal request/reply streams support operation resume

Control replica routing uses request stream and reply stream. Request payload includes command and reply stream id. Active Provider/Runner owner consumer executes and streams result events to reply stream.

Reply stream may contain stdout/stderr, progress, file chunk, final result, final error. It is ephemeral relay for active operation, not durable result storage.

For long-running operations, Worker reads reply stream by cursor. If Control replica dies during operation, Worker resumes through another Control replica using same request id and last cursor. Reading reply stream does not delete messages; stream is append-only until TTL/trim.

Operation metadata records request id, runtime id, target, command, stream ids, status, deadline, owner generation, cancel flag, timestamps, and optional body ref.

Operation statuses:

```text
pending | accepted | running | finished | failed | canceled | expired
```

Deadline is operation lifetime, not Control connection lifetime. Rollout/resume does not fail operation if deadline remains.

### 14. Background Runtime operation completes through Worker input queue

Background operation does not keep Worker waiting or listening. Worker starts operation and returns handle as tool result. Control observes operation metadata/reply stream and publishes final completion to Worker input queue.

Completion payload includes task id, operation request id, workspace id, agent id, parent session id, tool name, final status, summary/result/error, created_at, idempotency key.

Worker handles completion through normal dispatch and injects parent session message. Control tracks completion publish state and Worker input queue deduplicates by idempotency key based on operation request id.

Task status/stop query Control operation metadata instead of worker-local asyncio task registry. task_stop asks Control to cancel operation; Control propagates cancel to Runner/Provider best-effort.

### 15. Request body stream supports chunk dedup

Large request body or streaming input uses request body stream. Command envelope references request body stream id.

Chunks have monotonic protocol-level chunk id. Runner tracks applied chunk ids per operation and ignores duplicate chunks. Out-of-order or missing chunk is operation error. At-least-once delivery and Runner-side dedup are assumed.

Runner generation change remains failure boundary and does not resume old generation operation.

### 16. Provider command operation is short-lived command acceptance

Provider command also uses request/reply stream because requester Control replica and Provider-owning Control replica can differ.

Provider command response is not long durable job. It confirms Provider accepted/rejected command and moved observed state to starting/stopping/resetting or equivalent. Actual backend completion converges through later Provider state events and reconciliation.

### 17. Agent Workspace path is Provider metadata

Agent Workspace absolute path reported by Provider is single source for:

- system prompt
- tool context
- bash default working directory
- file API path validation
- UI file browser/path display

NoIntern code and prompts must not hardcode `/home/sandbox` as Agent Workspace. Provider can report `/workspace/agent`, `/home/sandbox`, or another absolute path depending on implementation.

Runner validates paths relative to Provider-reported Agent Workspace. If Runner reports path inconsistent with Provider/Control metadata, Control surfaces `workspace_path_mismatch` or `workspace_path_invalid`.

### 18. Kubernetes Provider is external and uses PVC persistence

Kubernetes Provider is external component deployed separately from server. It may have replicas >= 2 with Kubernetes Lease leader election. Only one active owner exists; standby acquires Lease and reconnects with new generation on leader loss.

Provider creates backend resources for Runtime. Initial canonical persistence is EBS-backed PVC per Runtime. EFS is not default due to capacity/cost/performance concerns. S3 checkpoint is archive/export/backup capability, not canonical persistence.

Kubernetes Pod/container condition can contribute to observed state but final Runner usability is computed with Runner connection/generation.

EBS PVC AZ pinning, quota, idle cost are mitigated through capacity reporting, workspace size limit, retention/archive policy, and StorageClass `WaitForFirstConsumer`.

### 19. Docker Provider is local/dev single-host provider

Docker Provider is external component for local/dev, single-host, small deployments. Multi-host HA, host failure recovery, and strong multi-tenant isolation are out of default scope.

One Runtime maps to one Docker container. Runner runs inside container and connects outbound to Control.

Agent Workspace persistence is provider-managed host directory bind mount. stop removes container but keeps host directory. start mounts existing directory. restart recreates container and preserves directory. reset removes container and deletes/recreates host directory.

On Provider process restart, Docker Provider scans Docker API, labels, and host workspace directories and re-reports observed state to Control. S3 checkpoint/restore is not canonical persistence.

### 20. Delivery is part of the architecture

Provider and Runner are external artifacts and must be independently built, pushed, deployed, and versioned. They are not implicit code inside `nointern-server` image.

Initial images:

- `nointern-server`
- `nointern-runtime-runner`
- `nointern-runtime-provider-kubernetes`
- `nointern-runtime-provider-docker`

ECR repositories are managed by Terraform/Terragrunt, not created by GitHub Actions. PR builds images and validates Helm templates; main merge pushes immutable `${github.sha}` tags to ECR.

Helm chart must expose values for Control/Provider registry, Coordination Store, Runner auth secret, Provider image, Runner image, RBAC/ServiceAccount/IRSA, leader election, storage defaults, PVC size, retention policy.

Runtime Pods/PVCs are not rendered by Helm directly. Kubernetes Provider creates them dynamically.

ArgoCD manages Provider as separate Application from server. Legacy `nointern-sandbox` path is replaced or disabled/pruned. Production done condition requires image push, GitOps values, ArgoCD root graph, Provider deployment, Runner image reference, and new Runtime path active without manual image push/kubectl.

## Error Taxonomy

User-facing error codes remain short and stable:

- provider_not_found
- provider_disconnected
- provider_capability_mismatch
- provider_config_invalid
- runtime_start_failed
- runtime_stop_failed
- runtime_reset_failed
- runner_unavailable
- operation_lost
- operation_interrupted
- operation_expired
- workspace_path_invalid
- workspace_path_mismatch

Expected domain states such as provider disconnected, runner unavailable, operation expired, user cancel are not Sentry errors. Protocol violation, generation invariant violation, storage invariant violation are errors.

Logs/metrics/traces include agent id, runtime id, operation id, desired generation, provider generation, runner generation.

## Consequences

### Positive

- Runtime lifecycle and in-runtime operations have separate state and ownership.
- Query APIs become side-effect free.
- Control replicas can roll out without being source of truth.
- Provider/Runner reconnection is handled through generation fencing.
- Worker can resume long-running foreground operations by reply cursor.
- Background completion survives Worker rollout through Worker input queue.
- Agent Workspace persistence is Provider contract rather than leaked `/home/sandbox` assumption.
- Kubernetes and Docker implementations can evolve independently behind Provider protocol.
- Production delivery path is explicit for Provider/Runner images and GitOps deployment.

### Negative / Trade-offs

- Clean-state replacement has large blast radius.
- Legacy sandbox/session workspace compatibility is intentionally not preserved.
- New Coordination Store abstraction and operation stream semantics must be implemented.
- Provider/Runner protocols and generation fencing add complexity.
- UI must stop combining raw states and depend on server summary/actions.
- Delivery requires coordinated changes to ECR, GitHub Actions, Helm, ArgoCD, IAM/secrets.

## Alternatives Considered

### Keep existing Sandbox concept and refine it

Rejected. Sandbox is implementation detail but was used as top-level domain concept, continuously blurring Provider, Runner, Workspace, and lifecycle responsibility.

### Add Runtime Profile layer

Rejected. At current stage it adds unnecessary depth: Agent settings → Runtime Profile → Provider settings. Put Provider id and provider-specific config directly on Agent settings first.

### Provider fallback

Rejected. Automatically switching to another Provider when configured Provider is disconnected makes incident analysis, data location, and network policy expectation unclear.

### Direct Control replica routing

Rejected. Routing request by looking up which replica owns connection is vulnerable to stale registry, rollout, reconnect timing. Publisher should not know consumer replica.

### Store stdout/stderr durably in Control

Rejected. Reply stream is active operation relay. Durable user-visible result belongs in session history with bounded retention/truncation policy defined by each operation.

### Keep S3 checkpoint as Kubernetes canonical persistence

Rejected. S3 dump/restore is slow and has lost data when dump failed inside Pod termination window. Kubernetes Provider v1 uses EBS-backed PVC as canonical persistence.

### EFS as default persistence

Rejected. EFS has capacity/accounting problems and performance issues for metadata-heavy workload such as git.

## Remaining Discussions

- Product UX for issuing/revoking workspace-provided Provider credentials.
- Minimum common fields in Runtime capability schema.
- Output truncation/retention per operation type.
- Kubernetes Provider PVC cleanup/archive policy and quota enforcement.
- Exact support boundary for in-memory Coordination Store in standalone deployment.
- Whether ArgoCD image tag update should be PR-based manifest update or image updater automation.

## References

- Related follow-up design: `docs/azents/design/sandbox-260525-sandbox-redesign.md`
- Related specs: `docs/azents/spec/flow/agent-runtime-control.md`, `docs/azents/spec/flow/agent-runtime-persistence.md`

## Migration provenance

- Historical source filename: `0038-sandbox-system-redesign.md`
- Source date basis: `adr.created`
- This ADR was reconstructed as a historical record; no new requester confirmation is implied.
